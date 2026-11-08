import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { gzipSync } from 'node:zlib'
import { createHash } from 'node:crypto'
import { applyStdLut, parseStdCube } from '../src/lut.ts'
import { extractZipEntry, fetchVerifiedAsset } from '../src/assets.ts'
import type { Asset } from '../src/types.ts'

const reference = JSON.parse(await readFile(new URL('./fixtures/colour-reference.json', import.meta.url), 'utf8'))
for (const fixture of reference.fixtures) {
  test(`matches independent colour-science tetrahedral output: ${fixture.path}`, async () => {
    const text = await readFile(new URL(`../public/${fixture.path}`, import.meta.url), 'utf8')
    assert.equal(createHash('sha256').update(text).digest('hex'), fixture.sourceSha256, 'independent reference is tied to this cube')
    const pixels = new Uint8ClampedArray(reference.pixels)
    const result = applyStdLut(pixels, parseStdCube(text))
    assert.deepEqual([...result], fixture.expected)
    assert.deepEqual([...pixels], reference.pixels, 'source pixels stay unchanged')
  })
}
const text = await readFile(new URL(`../public/${reference.fixtures[0].path}`, import.meta.url), 'utf8')
test('rejects V-Log, malformed dimensions, rows, domain and non-finite data', () => {
  for (const invalid of [text.replace('PHOTOSTYLE STD', 'PHOTOSTYLE VLOG'), text.replace('LUT_3D_SIZE 33', 'LUT_3D_SIZE 32'), `${text.replace(/^DOMAIN_MAX .*$/m, '')}\nDOMAIN_MAX 2 2 2`, `${text}\nNaN 0 0`, text.split('\n').slice(0, -3).join('\n')]) assert.throws(() => parseStdCube(invalid))
})
test('identity cube preserves channels, alpha and endpoints', () => {
  const table = new Float64Array(33 ** 3 * 3)
  let i = 0
  for (let b = 0; b < 33; b++) for (let g = 0; g < 33; g++) for (let r = 0; r < 33; r++) { table[i++] = r / 32; table[i++] = g / 32; table[i++] = b / 32 }
  const pixels = new Uint8ClampedArray(reference.pixels)
  assert.deepEqual(applyStdLut(pixels, { size: 33, table }), pixels)
})
test('reads raw, packed gzip and host-decoded LUTs; rejects corrupt bytes and HTTP failures', async () => {
  const originalFetch = globalThis.fetch
  const buffer = Buffer.from(text)
  const asset = { name: 'testSTD.cube', path: '/test.cube.gz', bytes: buffer.length, sha256: createHash('sha256').update(buffer).digest('hex'), encoding: 'gzip' as const }
  try {
    for (const data of [buffer, gzipSync(buffer)]) {
      globalThis.fetch = async () => new Response(data)
      assert.equal(new TextDecoder().decode(await fetchVerifiedAsset(asset)), text)
    }
    globalThis.fetch = async () => new Response('broken')
    await assert.rejects(fetchVerifiedAsset(asset), /검증/)
    globalThis.fetch = async () => new Response('', { status: 404 })
    await assert.rejects(fetchVerifiedAsset(asset), /가져오지/)
  } finally { globalThis.fetch = originalFetch }
})

const catalog = JSON.parse(await readFile(new URL('../public/catalog.json', import.meta.url), 'utf8'))
const zipCombo = catalog.combinations.find((c: { id: string }) => c.id === 'kodak_portra_400__kodak_portra_endura')
const zipBytes = await readFile(new URL(`../public${zipCombo.files.zip.path}`, import.meta.url))
const asArrayBuffer = (bytes: Uint8Array): ArrayBuffer => new Uint8Array(bytes).buffer
const digest = (bytes: Uint8Array) => createHash('sha256').update(bytes).digest('hex')
const zipAsset = (kind: 'std' | 'vlog', bytes = zipBytes): Asset => ({ ...zipCombo.files[kind], path: zipCombo.files.zip.path, encoding: 'zip-entry', transferBytes: bytes.length, transferSha256: digest(bytes) })

test('ZIP-entry transport extracts the selected camera STD and unchanged VLOG byte-for-byte', async () => {
  const originalFetch = globalThis.fetch
  try {
    globalThis.fetch = async () => new Response(zipBytes)
    const kinds: ('std' | 'vlog')[] = ['std', 'vlog'];
    assert.equal(zipCombo.stdMethod, 'camera-vlog-alchemy-v1');
    assert.deepEqual(zipCombo.stdByCamera[catalog.cameraAdapters.defaultCamera].std, zipCombo.files.std);
    assert.equal(zipCombo.files.stdB, undefined);
    for (const kind of kinds) {
      const original = await readFile(new URL(`../public${zipCombo.files[kind].path}`, import.meta.url))
      assert.deepEqual(new Uint8Array(await fetchVerifiedAsset(zipAsset(kind))), new Uint8Array(original))
      if(kind!=='vlog') assert.equal(parseStdCube(original.toString('utf8')).size,33)
    }
  } finally { globalThis.fetch = originalFetch }
})

test('non-default camera downloads use their own archive despite sharing the cube entry name', async () => {
  const originalFetch = globalThis.fetch
  const selected = zipCombo.stdByCamera.S5II
  assert.equal(selected.std.name, zipCombo.files.std.name)
  assert.notEqual(selected.std.sha256, zipCombo.files.std.sha256)
  assert.notEqual(selected.zip.path, zipCombo.files.zip.path)
  const bytes = await readFile(new URL(`../public${selected.zip.path}`, import.meta.url))
  try {
    globalThis.fetch = async input => { assert.equal(input, selected.zip.path); return new Response(bytes) }
    const cube = await fetchVerifiedAsset(selected.std)
    assert.equal(digest(new Uint8Array(cube)), selected.std.sha256)
    assert.equal(parseStdCube(new TextDecoder().decode(cube)).size, 33)
    globalThis.fetch = async () => new Response(zipBytes)
    await assert.rejects(fetchVerifiedAsset(selected.std), /검증/)
  } finally { globalThis.fetch = originalFetch }
})

test('ZIP-entry transport authenticates container and extracted file, rejecting corrupt or missing data', async () => {
  const originalFetch = globalThis.fetch
  try {
    const corrupt = Buffer.from(zipBytes); corrupt[80] ^= 1
    globalThis.fetch = async () => new Response(corrupt)
    await assert.rejects(fetchVerifiedAsset(zipAsset('std')), /검증/)
    globalThis.fetch = async () => new Response(zipBytes)
    await assert.rejects(fetchVerifiedAsset({ ...zipAsset('std'), transferBytes: zipBytes.length - 1 }), /검증/)
    await assert.rejects(fetchVerifiedAsset({ ...zipAsset('std'), transferSha256: undefined }), /검증/)
    await assert.rejects(fetchVerifiedAsset({ ...zipAsset('std'), name: 'missingSTD.cube' }), /찾지/)
    await assert.rejects(fetchVerifiedAsset({ ...zipAsset('std'), bytes: zipCombo.files.std.bytes - 1 }), /검증/)
    await assert.rejects(fetchVerifiedAsset({ ...zipAsset('std'), sha256: '0'.repeat(64) }), /검증/)
  } finally { globalThis.fetch = originalFetch }
})

test('ZIP32 parser rejects encrypted, unsupported, out-of-bounds and inconsistent archives', async () => {
  const end = zipBytes.length - 22
  assert.equal(zipBytes.readUInt32LE(end), 0x06054b50)
  const central = zipBytes.readUInt32LE(end + 16)
  const nameLength = zipBytes.readUInt16LE(central + 28)
  const firstName = zipBytes.subarray(central + 46, central + 46 + nameLength).toString('utf8')
  const expectedSize = zipBytes.readUInt32LE(central + 24)
  const local = zipBytes.readUInt32LE(central + 42)
  const changes: ((value: Buffer) => void)[] = [
    value => value.writeUInt16LE(1, central + 8), // encryption
    value => value.writeUInt16LE(12, central + 10), // unsupported BZIP2
    value => value.writeUInt32LE(0xffffffff, central + 24), // ZIP64 sentinel
    value => value.writeUInt16LE(1, end + 4), // split archive
    value => value.writeUInt32LE(zipBytes.length, end + 16), // directory bounds
    value => value.writeUInt16LE(0xffff, central + 28), // filename bounds
    value => value.writeUInt32LE(central, central + 42), // local header overlaps directory
    value => value.writeUInt32LE(expectedSize - 1, local + 22), // size disagreement
    value => { value[local + 30] ^= 1 }, // filename disagreement
  ]
  for (const change of changes) {
    const changed = Buffer.from(zipBytes); change(changed)
    await assert.rejects(extractZipEntry(asArrayBuffer(changed), firstName, expectedSize), /검증/)
  }
  for (const truncated of [zipBytes.subarray(0, 10), zipBytes.subarray(0, -1)]) await assert.rejects(extractZipEntry(asArrayBuffer(truncated), firstName, expectedSize), /검증/)
})

test('ZIP32 stored entries work and deflate support failures are explicit', async () => {
  // Independent minimal stored ZIP fixture, with matching local/central fields.
  const name = Buffer.from('test.cube'), payload = Buffer.from('stored LUT bytes')
  const local = Buffer.alloc(30); local.writeUInt32LE(0x04034b50); local.writeUInt16LE(20, 4); local.writeUInt32LE(payload.length, 18); local.writeUInt32LE(payload.length, 22); local.writeUInt16LE(name.length, 26)
  const directory = Buffer.alloc(46); directory.writeUInt32LE(0x02014b50); directory.writeUInt16LE(20, 6); directory.writeUInt32LE(payload.length, 20); directory.writeUInt32LE(payload.length, 24); directory.writeUInt16LE(name.length, 28)
  const end = Buffer.alloc(22); end.writeUInt32LE(0x06054b50); end.writeUInt16LE(1, 8); end.writeUInt16LE(1, 10); end.writeUInt32LE(directory.length + name.length, 12); end.writeUInt32LE(local.length + name.length + payload.length, 16)
  const stored = Buffer.concat([local, name, payload, directory, name, end])
  assert.deepEqual(new Uint8Array(await extractZipEntry(asArrayBuffer(stored), 'test.cube', payload.length)), new Uint8Array(payload))
  const originalDecompressor = globalThis.DecompressionStream
  try {
    globalThis.DecompressionStream = class { constructor() { throw new TypeError('unsupported format') } } as unknown as typeof DecompressionStream
    await assert.rejects(extractZipEntry(asArrayBuffer(zipBytes), zipCombo.files.std.name, zipCombo.files.std.bytes), /브라우저.*지원하지/)
  } finally { globalThis.DecompressionStream = originalDecompressor }
})
