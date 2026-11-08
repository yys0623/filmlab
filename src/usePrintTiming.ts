import { useEffect, useState } from 'react'
import { fetchVerifiedAsset } from './assets'
import type { Cube } from './lut'
import { bakeTimingCube, clampShift, parseAdapterCube, parseTimingPack, serializeCube, type TimingPack } from './printTiming'
import type { Asset, Catalog, Combination } from './types'

// Packs and camera adapters are verified once and kept for the session.
const packs = new Map<string, Promise<TimingPack>>()
const adapters = new Map<string, Promise<Cube>>()

function loadPack(id: string, asset: Asset) {
  if (!packs.has(asset.sha256)) {
    const promise = fetchVerifiedAsset(asset).then(buffer => parseTimingPack(buffer, id))
    promise.catch(() => packs.delete(asset.sha256))
    packs.set(asset.sha256, promise)
  }
  return packs.get(asset.sha256)!
}

function loadAdapter(asset: Asset) {
  if (!adapters.has(asset.sha256)) {
    const promise = fetchVerifiedAsset(asset).then(buffer => parseAdapterCube(new TextDecoder().decode(buffer)))
    promise.catch(() => adapters.delete(asset.sha256))
    adapters.set(asset.sha256, promise)
  }
  return adapters.get(asset.sha256)!
}

export interface PrintTiming {
  available: boolean; active: boolean; span: number
  /** Total shift from the film's database neutral filters (film-cast preset + sliders). */
  total: { m: number; y: number }
  preview?: { key: string; cube: Cube }
  loading: boolean; error?: string
  bake(format: 'std' | 'vlog', cameraId: string): Promise<string>
}

/**
 * m / y are the total shift from the film's database neutral filters, exactly
 * like spektrafilm's GUI. The film-cast variant is one such position, so the
 * page sets the sliders to it; whenever the sliders sit on a published
 * position (0 / 0 or the film-cast preset) the verified cubes are used and
 * nothing is baked here (`published`).
 */
export function usePrintTiming(catalog: Catalog | null, base: Combination | undefined,
  m: number, y: number, previewCameraId: string, enabled: boolean, published: boolean): PrintTiming {
  const info = catalog?.printTiming
  const entry = base && base.processMode === 'negative_print' && !base.castBaseId ? info?.packs[base.id] : undefined
  const span = info?.rangeCC?.[1] ?? 30
  const total = { m: clampShift(m, span), y: clampShift(y, span) }
  const available = !!entry && !!catalog?.cameraAdapters
  const active = available && enabled && !published
  const adapterAsset = catalog?.cameraAdapters?.models.find(model => model.id === previewCameraId)?.asset
  // The preview object must keep its identity between renders, or the photo
  // worker restarts on every render and never finishes.
  const [state, setState] = useState<{ key: string; preview?: { key: string; cube: Cube }; error?: string }>({ key: '' })
  const key = active && entry && adapterAsset ? `${base!.id}:${previewCameraId}:${total.m.toFixed(2)}:${total.y.toFixed(2)}` : ''

  useEffect(() => {
    if (!key || !entry || !adapterAsset) return
    let live = true
    // Debounce while a slider is being dragged; the bake itself takes ~50 ms.
    const timer = window.setTimeout(() => {
      Promise.all([loadPack(base!.id, entry.asset), loadAdapter(adapterAsset)])
        .then(([pack, adapter]) => { if (live) setState({ key, preview: { key, cube: bakeTimingCube(pack, total.m, total.y, adapter) } }) })
        .catch(e => { if (live) setState({ key, error: e instanceof Error ? e.message : '인화 필터 데이터를 불러오지 못했습니다.' }) })
    }, 120)
    return () => { live = false; window.clearTimeout(timer) }
  }, [key])

  async function bake(format: 'std' | 'vlog', cameraId: string) {
    if (!active || !entry || !catalog?.cameraAdapters) throw new Error('인화 필터 조정값이 없습니다.')
    const pack = await loadPack(base!.id, entry.asset)
    const model = catalog.cameraAdapters.models.find(item => item.id === cameraId)
    if (format === 'std' && !model) throw new Error('이 카메라용 STD 변환이 없습니다.')
    const cube = bakeTimingCube(pack, total.m, total.y, format === 'std' ? await loadAdapter(model!.asset) : undefined)
    const label = `M ${total.m.toFixed(1)} Y ${total.y.toFixed(1)} CC`
    return serializeCube(cube, format === 'std' ? 'STD' : 'VLOG', `${format === 'std' ? `${cameraId} Standard` : 'V-Log'} - ${base!.id} - print filter ${label}`,
      `sosang print filter timing (experimental): spektrafilm enlarger shift ${label} from the database neutral filters, ${info!.method}.`)
  }

  const ready = state.key === key && key !== ''
  return { available, active, span, total, preview: ready ? state.preview : undefined,
    loading: active && !ready, error: ready ? state.error : undefined, bake }
}
