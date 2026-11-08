import { fetchVerifiedAsset } from './assets'
import { applyStdLut, parseStdCube, type Cube } from './lut'
import type { Asset } from './types'

// A message carries either a verified catalog asset or a cube baked in the
// page (interactive print filter timing); both run the same STD application.
self.onmessage = async (event: MessageEvent<{ asset?: Asset; cube?: Cube; pixels: Uint8ClampedArray }>) => {
  try {
    const cube = event.data.cube ?? parseStdCube(new TextDecoder().decode(await fetchVerifiedAsset(event.data.asset!)))
    const result = applyStdLut(event.data.pixels, cube)
    self.postMessage({ pixels: result }, { transfer: [result.buffer] })
  } catch (error) {
    self.postMessage({ error: error instanceof Error ? error.message : '사진에 LUT를 적용하지 못했습니다.' })
  }
}
