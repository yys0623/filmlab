import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { parseStdCube } from '../src/lut.ts'
import { bakeTimingCube, blendExposure, clampShift, filmCastShift, formatShift, parseAdapterCube, parseTimingPack, sameShift, serializeCube, shiftCode, shiftWeights } from '../src/printTiming.ts'
import type { Catalog } from '../src/types.ts'

const catalog: Catalog = JSON.parse(readFileSync(new URL('../public/catalog.json', import.meta.url), 'utf8'))
const ID = 'fujifilm_c200__fujifilm_crystal_archive_typeii'
const file = (path: string) => readFileSync(new URL(`../public${path}`, import.meta.url))
const arrayBuffer = (bytes: Buffer) => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer
const pack = parseTimingPack(arrayBuffer(file(catalog.printTiming!.packs[ID].asset.path)), ID)
const base = catalog.combinations.find(combo => combo.id === ID)!

function error(a: ArrayLike<number>, b: ArrayLike<number>) {
  const per: number[] = []
  for (let i = 0; i < a.length; i += 3) per.push(Math.max(Math.abs(a[i] - b[i]), Math.abs(a[i + 1] - b[i + 1]), Math.abs(a[i + 2] - b[i + 2])))
  per.sort((x, y) => x - y)
  return { mean: per.reduce((s, v) => s + v, 0) / per.length, p99: per[Math.floor(per.length * 0.99)] }
}

test('biquadratic weights reproduce the baked nodes and sum to one', () => {
  for (const [m, y] of [[-30, -30], [0, 0], [30, 0], [0, -30]]) {
    const w = shiftWeights(m, y, 30)
    assert.equal(w.filter(v => Math.abs(v - 1) < 1e-12).length, 1)
    assert.equal(w.filter(v => Math.abs(v) < 1e-12).length, 8)
  }
  for (const [m, y] of [[-17, 4], [12.5, -29], [3, 3]]) assert.ok(Math.abs(shiftWeights(m, y, 30).reduce((s, v) => s + v, 0) - 1) < 1e-12)
  assert.throws(() => shiftWeights(31, 0, 30))
  assert.deepEqual(Array.from(blendExposure(pack, 0, 0)), Array.from(pack.a[4]))
})

test('pack identity and format are validated before use', () => {
  assert.equal(pack.size, 33); assert.deepEqual(pack.gridCC, [-30, 0, 30])
  assert.throws(() => parseTimingPack(arrayBuffer(file(catalog.printTiming!.packs[ID].asset.path)), 'kodak_gold_200__kodak_2383'))
  assert.throws(() => parseTimingPack(new ArrayBuffer(64)))
})

test('the neutral V-Log chain matches the published VLOG cube within LUT precision', () => {
  const published = parseStdCube(file(base.files!.vlog.path).toString('utf8').replace('#LUMIXPHOTOSTYLE VLOG', '#LUMIXPHOTOSTYLE STD'))
  const e = error(bakeTimingCube(pack, 0, 0).table, published.table)
  assert.ok(e.mean < 0.004 && e.p99 < 0.03, JSON.stringify(e))
})

test('the camera STD chain matches the published S1II STD cube within LUT precision', () => {
  const model = catalog.cameraAdapters!.models.find(item => item.id === 'S1II')!
  const adapter = parseAdapterCube(file(model.asset.path).toString('utf8'))
  const published = parseStdCube(file(base.files!.std.path).toString('utf8'))
  const e = error(bakeTimingCube(pack, 0, 0, adapter).table, published.table)
  assert.ok(e.mean < 0.004 && e.p99 < 0.03, JSON.stringify(e))
})

test('shifted V-Log cubes match direct spektrafilm runs at the same filter shift', () => {
  const reference = JSON.parse(readFileSync(new URL('./fixtures/print-timing-reference.json', import.meta.url), 'utf8'))
  assert.equal(reference.id, ID)
  for (const [shift, { indices, engine }] of Object.entries(reference.shifts) as [string, { indices: number[]; engine: number[][] }][]) {
    const [m, y] = shift.split(',').map(Number)
    const cube = bakeTimingCube(pack, m, y)
    const got = indices.flatMap(i => [cube.table[i * 3], cube.table[i * 3 + 1], cube.table[i * 3 + 2]])
    const e = error(got, engine.flat())
    assert.ok(e.mean < 0.005 && e.p99 < 0.03, `${shift}: ${JSON.stringify(e)}`)
  }
})

test('serialized cubes are camera-loadable and named by their shift', () => {
  const text = serializeCube(bakeTimingCube(pack, 5, -10), 'STD', 'S1II Standard - test', 'test')
  assert.equal(parseStdCube(text).size, 33)
  assert.match(text, /^TITLE "S1II Standard - test"\n#LUMIXPHOTOSTYLE STD\nLUT_3D_SIZE 33\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n/)
  assert.equal(shiftCode(5, -10), 'MP05YN10'); assert.equal(shiftCode(-3.4, 0), 'MN03p4YP00'); assert.equal(shiftCode(-0.04, 12.3), 'MP00YP12p3')
  assert.equal(formatShift(-5), '−5'); assert.equal(formatShift(0), '±0'); assert.equal(clampShift(44), 30); assert.equal(clampShift(-3.24), -3.2)
  assert.ok(sameShift({ m: -3.21, y: 5.7 }, { m: -3.2, y: 5.68 })); assert.ok(!sameShift({ m: 0, y: 0 }, { m: 0.1, y: 0 }))
})

test('a film-cast variant maps to a filter shift from its base neutral filters', () => {
  const cast = catalog.combinations.find(combo => combo.castBaseId === ID)!.filmCast!
  const { m, y } = filmCastShift(cast)
  assert.ok(Math.abs(m - (cast.appliedCC[1] - cast.filmCC[1])) < 1e-12 && Math.abs(y - (cast.appliedCC[2] - cast.filmCC[2])) < 1e-12)
  assert.ok(Math.abs(m) <= 30 && Math.abs(y) <= 30)
  assert.deepEqual(filmCastShift(undefined), { m: 0, y: 0 })
})
