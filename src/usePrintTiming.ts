import { useEffect, useRef, useState } from 'react'
import { fetchVerifiedAsset } from './assets'
import type { Cube } from './lut'
import { clampShift, parseAdapterCube, parseTimingPack, type TimingPack } from './printTiming'
import type { Asset, Catalog, Combination } from './types'

// Limit retained packs: each decoded pack occupies roughly 4 MiB.
const packs = new Map<string, Promise<TimingPack>>()
const adapters = new Map<string, Promise<Cube>>()
const MAX_PACKS = 4

function loadPack(id: string, asset: Asset) {
  const key = `${id}:${asset.sha256}`
  const cached = packs.get(key)
  if (cached) { packs.delete(key); packs.set(key, cached); return cached }
  {
    const promise = fetchVerifiedAsset(asset).then(buffer => parseTimingPack(buffer, id))
    promise.catch(() => { if (packs.get(key) === promise) packs.delete(key) })
    packs.set(key, promise)
    while (packs.size > MAX_PACKS) packs.delete(packs.keys().next().value!)
    return promise
  }
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
  retry(): void
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
  const workerRef = useRef<Worker | null>(null)
  const pending = useRef(new Map<number, { resolve: (value: { cube?: Cube; text?: string }) => void; reject: (error: Error) => void }>())
  const nextId = useRef(0)
  useEffect(() => () => {
    workerRef.current?.terminate(); workerRef.current = null
    for (const task of pending.current.values()) task.reject(new Error('인화 필터 처리가 중단되었습니다.'))
    pending.current.clear()
  }, [])
  function runBake(pack: TimingPack, adapter: Cube | undefined, m: number, y: number, output?: { tag: 'STD' | 'VLOG'; title: string; comment: string }) {
    return new Promise<{ cube?: Cube; text?: string }>((resolve, reject) => {
      try {
        const worker = workerRef.current ?? new Worker(new URL('./printTiming.worker.ts', import.meta.url), { type: 'module' })
        if (!workerRef.current) {
          workerRef.current = worker
          worker.onmessage = event => {
            const task = pending.current.get(event.data.id)
            if (!task) return
            pending.current.delete(event.data.id)
            if (event.data.error) task.reject(new Error(event.data.error)); else task.resolve(event.data)
          }
          worker.onerror = worker.onmessageerror = () => {
            worker.terminate(); workerRef.current = null
            for (const task of pending.current.values()) task.reject(new Error('인화 필터 처리가 중단되었습니다.'))
            pending.current.clear()
          }
        }
        const id = ++nextId.current
        pending.current.set(id, { resolve, reject })
        try { worker.postMessage({ id, pack, adapter, m, y, output }) } catch (error) { pending.current.delete(id); throw error }
      } catch (error) { reject(error instanceof Error ? error : new Error('인화 필터 처리를 시작하지 못했습니다.')) }
    })
  }
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
  const [attempt, setAttempt] = useState(0)
  const key = active && entry && adapterAsset ? `${base!.id}:${previewCameraId}:${total.m.toFixed(2)}:${total.y.toFixed(2)}` : ''

  useEffect(() => {
    if (!key || !entry || !adapterAsset) return
    let live = true
    // Debounce while a slider is being dragged; the bake itself takes ~50 ms.
    const timer = window.setTimeout(() => {
      Promise.all([loadPack(base!.id, entry.asset), loadAdapter(adapterAsset)])
        .then(([pack, adapter]) => live ? runBake(pack, adapter, total.m, total.y) : null)
        .then(result => { if (live && result?.cube) setState({ key, preview: { key, cube: result.cube } }) })
        .catch(e => { if (live) setState({ key, error: e instanceof Error ? e.message : '인화 필터 데이터를 불러오지 못했습니다.' }) })
    }, 120)
    return () => { live = false; window.clearTimeout(timer) }
  }, [key, attempt])

  async function bake(format: 'std' | 'vlog', cameraId: string) {
    if (!active || !entry || !catalog?.cameraAdapters) throw new Error('인화 필터 조정값이 없습니다.')
    const pack = await loadPack(base!.id, entry.asset)
    const model = catalog.cameraAdapters.models.find(item => item.id === cameraId)
    if (format === 'std' && !model) throw new Error('이 카메라용 STD 변환이 없습니다.')
    const adapter = format === 'std' ? await loadAdapter(model!.asset) : undefined
    const label = `M ${total.m.toFixed(1)} Y ${total.y.toFixed(1)} CC`
    const result = await runBake(pack, adapter, total.m, total.y, { tag: format === 'std' ? 'STD' : 'VLOG', title: `${format === 'std' ? `${cameraId} Standard` : 'V-Log'} - ${base!.id} - print filter ${label}`,
      comment: `sosang print filter timing (experimental): spektrafilm enlarger shift ${label} from the database neutral filters, ${info!.method}.` })
    if (result.text === undefined) throw new Error('인화 필터 파일을 만들지 못했습니다.')
    return result.text
  }

  const ready = state.key === key && key !== ''
  return { available, active, span, total, preview: ready ? state.preview : undefined,
    loading: active && !ready, error: ready ? state.error : undefined, bake,
    retry: () => { setState({ key: '' }); setAttempt(n => n + 1) } }
}
