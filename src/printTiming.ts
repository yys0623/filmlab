import type { Cube } from './lut'

/**
 * Interactive print filter timing (Y/M CC shift, like spektrafilm's GUI).
 *
 * A pack holds A[m][y] (V-Log RGB -> log10 paper exposure code) baked at
 * gridCC x gridCC filter shifts and B (paper exposure code -> sRGB), all 33^3
 * in .cube row order (red fastest). A shift is blended from the nine A tables
 * with biquadratic Lagrange weights; the browser then composes
 * STD -> camera adapter (trilinear) -> A (tetrahedral) -> B (tetrahedral).
 */
export const PRINT_TIMING_METHOD = 'spektrafilm-print-filter-timing-v1'
const MAGIC = 'SFPT1\n'

export interface TimingPack {
  id: string; size: number; gridCC: number[]
  a: Float32Array[] // 9 tables, index m * 3 + y
  b: Float32Array
}

export function parseTimingPack(buffer: ArrayBuffer, expectedId?: string): TimingPack {
  const bytes = new Uint8Array(buffer)
  const magic = new TextDecoder().decode(bytes.subarray(0, MAGIC.length))
  if (magic !== MAGIC) throw new Error('인화 필터 데이터 형식을 읽지 못했습니다.')
  const view = new DataView(buffer)
  const length = view.getUint32(MAGIC.length, true)
  const start = MAGIC.length + 4
  const header = JSON.parse(new TextDecoder().decode(bytes.subarray(start, start + length)))
  const size: number = header.resolution
  const gridCC: number[] = header.gridCC
  if (header.method !== PRINT_TIMING_METHOD || size !== 33 || gridCC?.length !== 3 || gridCC[1] !== 0 || gridCC[0] !== -gridCC[2]) throw new Error('지원하지 않는 인화 필터 데이터입니다.')
  if (expectedId && header.id !== expectedId) throw new Error('다른 조합의 인화 필터 데이터입니다.')
  const count = size ** 3 * 3
  const offset = start + length
  if (buffer.byteLength !== offset + 10 * count * 2) throw new Error('인화 필터 데이터가 손상되었습니다.')
  // The body may not be 2-byte aligned after the JSON header; copy once.
  const raw = new Uint16Array(buffer.slice(offset))
  const table = (index: number) => {
    const out = new Float32Array(count)
    for (let i = 0; i < count; i++) out[i] = raw[index * count + i] / 65535
    return out
  }
  return { id: header.id, size, gridCC, a: Array.from({ length: 9 }, (_, i) => table(i)), b: table(9) }
}

/** Camera Standard -> V-Log adapter cube (any photo style tag, values in 0..1). */
export function parseAdapterCube(text: string): Cube {
  let size = 0
  const values: number[] = []
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim()
    if (!line || line.startsWith('#') || line.startsWith('TITLE ') || line.startsWith('DOMAIN_')) continue
    const [tag, ...parts] = line.split(/\s+/)
    if (tag === 'LUT_3D_SIZE') { size = Number(parts[0]); continue }
    const row = [tag, ...parts].map(Number)
    if (row.length !== 3 || row.some(n => !Number.isFinite(n))) throw new Error('카메라 변환 LUT를 읽지 못했습니다.')
    values.push(...row)
  }
  if (size < 2 || values.length !== size ** 3 * 3) throw new Error('카메라 변환 LUT 크기가 올바르지 않습니다.')
  return { size, table: new Float64Array(values) }
}

/** Clamp to the baked range at 0.1 CC, the slider resolution. */
export function clampShift(value: number, span = 30) {
  return Math.max(-span, Math.min(span, Math.round(value * 10) / 10))
}

function lagrange(t: number): [number, number, number] {
  return [t * (t - 1) / 2, (1 - t) * (1 + t), t * (t + 1) / 2]
}

/** Nine weights, index m * 3 + y, for shifts inside the baked range. */
export function shiftWeights(m: number, y: number, span: number): number[] {
  if (Math.abs(m) > span || Math.abs(y) > span) throw new Error('인화 필터 조정 범위를 벗어났습니다.')
  const wm = lagrange(m / span), wy = lagrange(y / span)
  return wm.flatMap(a => wy.map(b => a * b))
}

export function blendExposure(pack: TimingPack, m: number, y: number): Float32Array {
  const weights = shiftWeights(m, y, pack.gridCC[2])
  const out = new Float32Array(pack.b.length)
  weights.forEach((weight, k) => {
    if (!weight) return
    const table = pack.a[k]
    for (let i = 0; i < out.length; i++) out[i] += weight * table[i]
  })
  return out
}

const clamp01 = (v: number) => v < 0 ? 0 : v > 1 ? 1 : v

// Tetrahedral lookup on a [b][g][r] table; writes 3 values into out at o.
function tetrahedral(t: ArrayLike<number>, n: number, r: number, g: number, b: number, out: Float64Array) {
  r = clamp01(r) * (n - 1); g = clamp01(g) * (n - 1); b = clamp01(b) * (n - 1)
  const r0 = Math.min(Math.floor(r), n - 2), g0 = Math.min(Math.floor(g), n - 2), b0 = Math.min(Math.floor(b), n - 2)
  const fr = r - r0, fg = g - g0, fb = b - b0
  const sr = 3, sg = n * 3, sb = n * n * 3
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
    out[c] = t[base + c] * (1 - high) + t[base + first + c] * (high - middle) + t[base + second + c] * (middle - low) + t[base + sr + sg + sb + c] * low
  }
}

function trilinear(t: ArrayLike<number>, n: number, r: number, g: number, b: number, out: Float64Array) {
  r = clamp01(r) * (n - 1); g = clamp01(g) * (n - 1); b = clamp01(b) * (n - 1)
  const r0 = Math.min(Math.floor(r), n - 2), g0 = Math.min(Math.floor(g), n - 2), b0 = Math.min(Math.floor(b), n - 2)
  const fr = r - r0, fg = g - g0, fb = b - b0
  const sr = 3, sg = n * 3, sb = n * n * 3
  const base = r0 * sr + g0 * sg + b0 * sb
  for (let c = 0; c < 3; c++) {
    const i = base + c
    const c00 = t[i] * (1 - fr) + t[i + sr] * fr, c10 = t[i + sg] * (1 - fr) + t[i + sg + sr] * fr
    const c01 = t[i + sb] * (1 - fr) + t[i + sb + sr] * fr, c11 = t[i + sb + sg] * (1 - fr) + t[i + sb + sg + sr] * fr
    out[c] = (c00 * (1 - fg) + c10 * fg) * (1 - fb) + (c01 * (1 - fg) + c11 * fg) * fb
  }
}

/** Bake a 33^3 cube for V-Log input (adapter omitted) or a camera's Standard input. */
export function bakeTimingCube(pack: TimingPack, m: number, y: number, adapter?: Cube): Cube {
  const n = pack.size, exposure = blendExposure(pack, m, y)
  const table = new Float64Array(n ** 3 * 3)
  const v = new Float64Array(3), e = new Float64Array(3), o = new Float64Array(3)
  let k = 0
  for (let bi = 0; bi < n; bi++) for (let gi = 0; gi < n; gi++) for (let ri = 0; ri < n; ri++) {
    const r = ri / (n - 1), g = gi / (n - 1), b = bi / (n - 1)
    if (adapter) trilinear(adapter.table, adapter.size, r, g, b, v)
    else { v[0] = r; v[1] = g; v[2] = b }
    tetrahedral(exposure, n, v[0], v[1], v[2], e)
    tetrahedral(pack.b, n, e[0], e[1], e[2], o)
    table[k++] = clamp01(o[0]); table[k++] = clamp01(o[1]); table[k++] = clamp01(o[2])
  }
  return { size: n, table }
}

/** Lumix-compatible 33^3 cube text, nine decimals, full range. */
export function serializeCube(cube: Cube, tag: 'STD' | 'VLOG', title: string, comment: string): string {
  const rows: string[] = [`TITLE "${title.replace(/"/g, '')}"`, `#LUMIXPHOTOSTYLE ${tag}`, `LUT_3D_SIZE ${cube.size}`, 'DOMAIN_MIN 0 0 0', 'DOMAIN_MAX 1 1 1', `# ${comment}`]
  const t = cube.table
  for (let i = 0; i < t.length; i += 3) rows.push(`${t[i].toFixed(9)} ${t[i + 1].toFixed(9)} ${t[i + 2].toFixed(9)}`)
  return rows.join('\n') + '\n'
}

/** Shift between a film's own neutral filters and the film-cast variant's blended pack. */
export function filmCastShift(cast: { filmCC: number[]; appliedCC: number[] } | undefined): { m: number; y: number } {
  if (!cast) return { m: 0, y: 0 }
  return { m: cast.appliedCC[1] - cast.filmCC[1], y: cast.appliedCC[2] - cast.filmCC[2] }
}

/** Filename code: M+5 / Y-10 -> MP05YN10; tenths use p (M-3.2 -> MN03p2). */
export function shiftCode(m: number, y: number) {
  const part = (label: string, v: number) => {
    const tenths = Math.abs(Math.round(v * 10)), whole = String(Math.floor(tenths / 10)).padStart(2, '0')
    return `${label}${v < 0 && tenths ? 'N' : 'P'}${whole}${tenths % 10 ? `p${tenths % 10}` : ''}`
  }
  return part('M', m) + part('Y', y)
}

/** True when two shifts are the same slider position (0.1 CC). */
export function sameShift(a: { m: number; y: number }, b: { m: number; y: number }) {
  return Math.abs(a.m - b.m) < 0.05 && Math.abs(a.y - b.y) < 0.05
}

export function formatShift(v: number) {
  const r = Math.round(v * 10) / 10
  return `${r > 0 ? '+' : r < 0 ? '−' : '±'}${Math.abs(r)}`
}
