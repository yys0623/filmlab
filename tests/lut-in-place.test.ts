import { test } from 'node:test'
import assert from 'node:assert/strict'
import { applyStdLut } from '../src/lut.ts'

test('in-place LUT processing matches the non-mutating path for all tetrahedra and alpha values', () => {
  const table = Float64Array.from({ length: 3 * 3 * 3 * 3 }, (_, i) => ((i * 17) % 101) / 100)
  const cube = { size: 3, table }
  const pixels = new Uint8ClampedArray([
    10, 90, 220, 0, 10, 220, 90, 32, 90, 10, 220, 64,
    90, 220, 10, 128, 220, 10, 90, 192, 220, 90, 10, 255,
    0, 255, 128, 7, 255, 255, 255, 254,
  ])
  const expected = applyStdLut(pixels, cube)
  const input = pixels.slice()
  const result = applyStdLut(input, cube, true)
  assert.equal(result, input)
  assert.deepEqual(result, expected)
})
