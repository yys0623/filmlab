import { fetchVerifiedAsset } from './assets.ts'
import { applyStdLut, parseStdCube, type Cube } from './lut.ts'
import type { Asset } from './types'

// A message carries either a verified catalog asset or a cube baked in the
// page (interactive print filter timing); both run the same STD application.
const cubes = new Map<string, Promise<Cube>>()
const MAX_CUBES = 4
let latestId = 0

function loadCube(asset: Asset): Promise<Cube> {
  const key = JSON.stringify(asset)
  const cached = cubes.get(key)
  if (cached) { cubes.delete(key); cubes.set(key, cached); return cached }
  const promise = fetchVerifiedAsset(asset).then(buffer => parseStdCube(new TextDecoder().decode(buffer)))
  cubes.set(key, promise)
  promise.catch(() => { if (cubes.get(key) === promise) cubes.delete(key) })
  while (cubes.size > MAX_CUBES) cubes.delete(cubes.keys().next().value!)
  return promise
}

self.onmessage = async (event: MessageEvent<{ id: number; asset?: Asset; cube?: Cube; pixels?: Uint8ClampedArray; inPlace?: boolean; cancel?: boolean }>) => {
  latestId = event.data.id
  if (event.data.cancel || !event.data.pixels) return
  try {
    const cube = event.data.cube ?? await loadCube(event.data.asset!)
    if (event.data.id !== latestId) return
    const pixels = event.data.pixels
    // Export jobs use the synchronous path; previews yield between chunks so
    // newer selections can cancel computation without discarding the LUT cache.
    let result: Uint8ClampedArray
    if (event.data.inPlace) result = applyStdLut(pixels, cube, true)
    else {
      result = pixels
      const chunk = 256 * 1024
      for (let offset = 0; offset < pixels.length; offset += chunk) {
        applyStdLut(pixels.subarray(offset, Math.min(offset + chunk, pixels.length)), cube, true)
        if (offset + chunk < pixels.length) {
          await new Promise<void>(resolve => setTimeout(resolve, 0))
          if (event.data.id !== latestId) return
        }
      }
    }
    self.postMessage({ id: event.data.id, pixels: result }, { transfer: [result.buffer] })
  } catch (error) {
    self.postMessage({ id: event.data.id, error: error instanceof Error ? error.message : '사진에 LUT를 적용하지 못했습니다.' })
  }
}
