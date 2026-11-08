import { useEffect, useMemo, useRef, useState } from 'react'
import type { Asset, Sample } from './types'
import type { Cube } from './lut'

/** A catalog asset, or a cube baked in the page with a stable identity key. */
export type LookSource = Asset | { key: string; cube: Cube }
const sourceKey = (source: LookSource) => 'cube' in source ? source.key : source.sha256

export interface Photo { sample: Sample; pixels: Uint8ClampedArray<ArrayBuffer>; originalWidth: number; originalHeight: number }
export const PHOTO_ACCEPT = 'image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp'
const MAX_BYTES = 30 * 1024 * 1024
const MAX_EDGE = 2048

function canvasBlob(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('미리보기 이미지를 만들지 못했습니다.')), 'image/png'))
}

export function usePhotoUpload(onSelected: () => void) {
  const [photo, setPhoto] = useState<Photo | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const sequence = useRef(0)
  const liveUrl = useRef('')
  useEffect(() => () => { sequence.current++; URL.revokeObjectURL(liveUrl.current) }, [])

  function clear() {
    sequence.current++
    URL.revokeObjectURL(liveUrl.current); liveUrl.current = ''
    setPhoto(null); setError(''); setLoading(false)
  }
  async function upload(file: File) {
    const request = ++sequence.current
    setError(''); setLoading(true)
    let bitmap: ImageBitmap | undefined
    try {
      if (!/\.(jpe?g|png|webp)$/i.test(file.name) || (file.type && !['image/jpeg', 'image/png', 'image/webp'].includes(file.type))) throw new Error('JPG, PNG, WebP 사진을 선택해 주세요. HEIC·RAW는 JPG로 변환한 뒤 사용할 수 있습니다.')
      if (file.size > MAX_BYTES) throw new Error('사진 한 장은 30 MB까지 선택할 수 있습니다.')
      if (!file.size) throw new Error('비어 있는 파일입니다. 다른 사진을 선택해 주세요.')
      try { bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' }) }
      catch { throw new Error('사진을 읽지 못했습니다. 손상되지 않은 JPG, PNG, WebP 파일을 선택해 주세요.') }
      if (request !== sequence.current) return
      if (bitmap.width * bitmap.height > 80_000_000) throw new Error('8,000만 화소 이하의 사진을 선택해 주세요.')
      const originalWidth = bitmap.width, originalHeight = bitmap.height
      const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height))
      const canvas = document.createElement('canvas')
      canvas.width = Math.max(1, Math.round(bitmap.width * scale)); canvas.height = Math.max(1, Math.round(bitmap.height * scale))
      const context = canvas.getContext('2d', { colorSpace: 'srgb', willReadFrequently: true })
      if (!context) throw new Error('이 브라우저에서 사진 미리보기를 지원하지 않습니다.')
      context.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
      const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data
      const blob = await canvasBlob(canvas)
      if (request !== sequence.current) return
      const path = URL.createObjectURL(blob)
      URL.revokeObjectURL(liveUrl.current); liveUrl.current = path
      setPhoto({ sample: { id: `upload-${request}`, name: file.name, category: '내 사진 · STD 미리보기', credit: '내 기기에서 처리한 사진 · 서버 전송 없음', source: null, path, width: canvas.width, height: canvas.height, inputKind: 'uploaded-srgb', previewLut: 'std' }, pixels, originalWidth, originalHeight })
      onSelected()
    } catch (e) { if (request === sequence.current) setError(e instanceof Error ? e.message : '사진을 불러오지 못했습니다.') }
    finally { bitmap?.close(); if (request === sequence.current) setLoading(false) }
  }
  return { photo, loading, error, upload, clear }
}

export function useSamplePhoto(sample: Sample | null) {
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState<{ key: string; photo?: Photo; error?: string }>({ key: '' })
  const cache = useRef(new Map<string, Photo>())
  const sampleKey = sample ? `${sample.id}:${sample.path}:${sample.width}x${sample.height}` : ''
  const key = sampleKey ? `${sampleKey}:${attempt}` : ''
  useEffect(() => {
    if (!sample) return
    const controller = new AbortController()
    let active = true
    const cached = cache.current.get(sampleKey)
    if (cached) {
      cache.current.delete(sampleKey); cache.current.set(sampleKey, cached)
      setState({ key, photo: cached })
      return () => { active = false }
    }
    setState({ key })
    void (async () => {
      let bitmap: ImageBitmap | undefined
      try {
        const response = await fetch(sample.path, { signal: controller.signal })
        if (!response.ok) throw new Error(`샘플 사진을 불러오지 못했습니다 (${response.status}).`)
        const blob = await response.blob()
        if (!blob.size || blob.size > MAX_BYTES) throw new Error('샘플 이미지의 크기를 확인해 주세요.')
        bitmap = await createImageBitmap(blob, { imageOrientation: 'from-image' })
        if (!active) return
        if (bitmap.width !== sample.width || bitmap.height !== sample.height || bitmap.width * bitmap.height > 80_000_000) throw new Error('샘플 이미지의 해상도가 카탈로그와 다릅니다.')
        const canvas = document.createElement('canvas'); canvas.width = bitmap.width; canvas.height = bitmap.height
        const context = canvas.getContext('2d', { colorSpace: 'srgb', willReadFrequently: true })
        if (!context) throw new Error('이 브라우저에서 사진 미리보기를 지원하지 않습니다.')
        context.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
        const photo: Photo = { sample, pixels: context.getImageData(0, 0, canvas.width, canvas.height).data, originalWidth: bitmap.width, originalHeight: bitmap.height }
        cache.current.set(sampleKey, photo)
        while (cache.current.size > 3 || [...cache.current.values()].reduce((sum, item) => sum + item.pixels.byteLength, 0) > 32 * 1024 * 1024) cache.current.delete(cache.current.keys().next().value!)
        setState({ key, photo })
      } catch (e) { if (active) setState({ key, error: e instanceof Error ? e.message : '샘플 사진을 읽지 못했습니다.' }) }
      finally { bitmap?.close() }
    })()
    return () => { active = false; controller.abort() }
  }, [sample, sampleKey, key])
  return { photo: key && state.key === key ? state.photo || null : null, error: key && state.key === key ? state.error : undefined, retry: () => { cache.current.delete(sampleKey); setAttempt(n => n + 1) } }
}

export function usePhotoLook(photo: Photo | null, asset: LookSource | undefined) {
  const [attempt, setAttempt] = useState(0)
  const [state, setState] = useState<{ request: object | null; path?: string; error?: string }>({ request: null })
  const key = photo && asset ? `${photo.sample.id}-${sourceKey(asset)}-${attempt}` : ''
  // A → B → A must start a new request: the first A's object URL was revoked
  // when B started, even if A's photo/LUT key is identical on the return trip.
  const request = useMemo(() => ({ key }), [photo, asset, key])
  useEffect(() => {
    if (!photo || !asset) return
    let active = true, resultUrl = ''
    let worker: Worker | undefined
    const fail = (message: string) => { if (active) setState({ request, error: message }) }
    try {
      worker = new Worker(new URL('./lut.worker.ts', import.meta.url), { type: 'module' })
      worker.onmessage = async (event: MessageEvent<{ pixels?: Uint8ClampedArray<ArrayBuffer>; error?: string }>) => {
        if (!active) return
        if (event.data.error) { fail(event.data.error); return }
        try {
          if (!event.data.pixels) throw new Error('LUT 처리 결과를 읽지 못했습니다.')
          const canvas = document.createElement('canvas'); canvas.width = photo.sample.width; canvas.height = photo.sample.height
          const context = canvas.getContext('2d', { colorSpace: 'srgb' })
          if (!context) throw new Error('미리보기를 만들지 못했습니다.')
          context.putImageData(new ImageData(event.data.pixels, canvas.width, canvas.height), 0, 0)
          const blob = await canvasBlob(canvas)
          if (active) { resultUrl = URL.createObjectURL(blob); setState({ request, path: resultUrl }) }
        } catch (e) { fail(e instanceof Error ? e.message : '미리보기를 만들지 못했습니다.') }
      }
      worker.onerror = () => fail('LUT 처리 중 문제가 생겼습니다. 다시 시도해 주세요.')
      const pixels = photo.pixels.slice()
      worker.postMessage('cube' in asset ? { pixels, cube: asset.cube } : { pixels, asset }, [pixels.buffer])
    } catch { fail('이 브라우저에서 LUT 처리를 시작하지 못했습니다.') }
    return () => { active = false; worker?.terminate(); URL.revokeObjectURL(resultUrl) }
  }, [photo, asset, request])
  return { path: key && state.request === request ? state.path : undefined, error: key && state.request === request ? state.error : undefined, retry: () => setAttempt(n => n + 1) }
}
