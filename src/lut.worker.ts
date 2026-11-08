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

self.onmessage = async (event: MessageEvent<{ id: number; asset?: Asset; cube?: Cube; pixels: Uint8ClampedArray }>) => {
  latestId = event.data.id
  try {
    const cube = event.data.cube ?? await loadCube(event.data.asset!)
    if (event.data.id !== latestId) return
    const result = applyStdLut(event.data.pixels, cube)
    self.postMessage({ id: event.data.id, pixels: result }, { transfer: [result.buffer] })
  } catch (error) {
    self.postMessage({ id: event.data.id, error: error instanceof Error ? error.message : '사진에 LUT를 적용하지 못했습니다.' })
  }
}
