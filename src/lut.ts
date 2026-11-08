export interface Cube { size: number; table: Float64Array }

export function parseStdCube(text: string): Cube {
  let size = 0, style = '', min = '', max = ''
  const values: number[] = []
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim()
    if (line.startsWith('#LUMIXPHOTOSTYLE ')) style = line.split(/\s+/)[1]
    if (!line || line.startsWith('#') || line.startsWith('TITLE ')) continue
    const [tag, ...parts] = line.split(/\s+/)
    if (tag === 'LUT_3D_SIZE') size = Number(parts[0])
    else if (tag === 'DOMAIN_MIN') min = parts.map(Number).join(',')
    else if (tag === 'DOMAIN_MAX') max = parts.map(Number).join(',')
    else {
      const row = [tag, ...parts].map(Number)
      if (row.length !== 3 || row.some(n => !Number.isFinite(n) || n < 0 || n > 1)) throw new Error('잘못된 LUT 데이터입니다.')
      values.push(...row)
    }
  }
  if (style !== 'STD' || size !== 33 || min !== '0,0,0' || max !== '1,1,1' || values.length !== size ** 3 * 3) throw new Error('지원하지 않는 STD LUT입니다.')
  return { size, table: new Float64Array(values) }
}

// .cube rows run R fastest: table[B, G, R, channel]. Six tetrahedra
// share 000 → 111. No additional gamma, exposure, or V-Log conversion.
export function applyStdLut(pixels: Uint8ClampedArray, cube: Cube): Uint8ClampedArray {
  if (pixels.length % 4) throw new Error('잘못된 이미지 데이터입니다.')
  const { size: n, table: t } = cube
  const output = new Uint8ClampedArray(pixels.length)
  const sr = 3, sg = n * 3, sb = n * n * 3
  for (let i = 0; i < pixels.length; i += 4) {
    const r = pixels[i] / 255 * (n - 1), g = pixels[i + 1] / 255 * (n - 1), b = pixels[i + 2] / 255 * (n - 1)
    const r0 = Math.min(Math.floor(r), n - 2), g0 = Math.min(Math.floor(g), n - 2), b0 = Math.min(Math.floor(b), n - 2)
    const fr = r - r0, fg = g - g0, fb = b - b0
    const base = r0 * sr + g0 * sg + b0 * sb
    let first: number, second: number, high: number, middle: number, low: number
    if (fr >= fg) {
      if (fg >= fb) { first = sr; second = sr + sg; high = fr; middle = fg; low = fb }
      else if (fr >= fb) { first = sr; second = sr + sb; high = fr; middle = fb; low = fg }
      else { first = sb; second = sb + sr; high = fb; middle = fr; low = fg }
    } else {
      if (fr >= fb) { first = sg; second = sg + sr; high = fg; middle = fr; low = fb }
      else if (fg >= fb) { first = sg; second = sg + sb; high = fg; middle = fb; low = fr }
      else { first = sb; second = sb + sg; high = fb; middle = fg; low = fr }
    }
    for (let c = 0; c < 3; c++) {
      output[i + c] = Math.round(255 * (t[base + c] * (1 - high) + t[base + first + c] * (high - middle) + t[base + second + c] * (middle - low) + t[base + sr + sg + sb + c] * low))
    }
    output[i + 3] = pixels[i + 3]
  }
  return output
}
