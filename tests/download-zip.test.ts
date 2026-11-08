import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import { deflateRawSync } from 'node:zlib'
import { renameZipEntries } from '../src/downloadZip.ts'
import { extractZipEntry } from '../src/assets.ts'

const arrayBuffer = (value: Uint8Array): ArrayBuffer => new Uint8Array(value).buffer
const mapping = { '0001STD.cube': 'C200CA.cube', '0001VLOG.cube': 'C200CAVLOG.cube' }
const crc32 = (value: Uint8Array) => {
  let crc = 0xffffffff
  for (const byte of value) { crc ^= byte; for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0) }
  return (crc ^ 0xffffffff) >>> 0
}
type FixtureFile = { name: string; data: Buffer; method: 0 | 8; descriptor?: 'signed' | 'unsigned' }
const files: FixtureFile[] = [
  { name: '0001STD.cube', data: Buffer.from('STD cube data\n'.repeat(40)), method: 8, descriptor: 'signed' },
  { name: '0001VLOG.cube', data: Buffer.from('VLOG cube data\n'), method: 0, descriptor: 'unsigned' },
  { name: 'README.txt', data: Buffer.from('Original metadata stays unchanged.\n'), method: 8 },
]
function fixture(input = files): Buffer {
  const local: Buffer[] = [], central: Buffer[] = []
  let offset = 0
  for (const file of input) {
    const name = Buffer.from(file.name), compressed = file.method === 8 ? deflateRawSync(file.data) : file.data, crc = crc32(file.data)
    const extra = Buffer.from([0xfe, 0xca, 2, 0, 3, 4]), comment = Buffer.from('entry comment'), flags = 0x800 | (file.descriptor ? 8 : 0)
    const header = Buffer.alloc(30)
    header.writeUInt32LE(0x04034b50); header.writeUInt16LE(20, 4); header.writeUInt16LE(flags, 6); header.writeUInt16LE(file.method, 8)
    if (!file.descriptor) { header.writeUInt32LE(crc, 14); header.writeUInt32LE(compressed.length, 18); header.writeUInt32LE(file.data.length, 22) }
    header.writeUInt16LE(name.length, 26); header.writeUInt16LE(extra.length, 28)
    const descriptor = Buffer.alloc(file.descriptor === 'signed' ? 16 : file.descriptor ? 12 : 0)
    if (file.descriptor) { const at = descriptor.length - 12; if (at) descriptor.writeUInt32LE(0x08074b50); descriptor.writeUInt32LE(crc, at); descriptor.writeUInt32LE(compressed.length, at + 4); descriptor.writeUInt32LE(file.data.length, at + 8) }
    const part = Buffer.concat([header, name, extra, compressed, descriptor]); local.push(part)
    const directory = Buffer.alloc(46)
    directory.writeUInt32LE(0x02014b50); directory.writeUInt16LE(20, 4); directory.writeUInt16LE(20, 6); directory.writeUInt16LE(flags, 8); directory.writeUInt16LE(file.method, 10)
    directory.writeUInt32LE(crc, 16); directory.writeUInt32LE(compressed.length, 20); directory.writeUInt32LE(file.data.length, 24)
    directory.writeUInt16LE(name.length, 28); directory.writeUInt16LE(extra.length, 30); directory.writeUInt16LE(comment.length, 32); directory.writeUInt32LE(offset, 42)
    central.push(Buffer.concat([directory, name, extra, comment])); offset += part.length
  }
  const directory = Buffer.concat(central), comment = Buffer.from('archive comment'), end = Buffer.alloc(22)
  end.writeUInt32LE(0x06054b50); end.writeUInt16LE(input.length, 8); end.writeUInt16LE(input.length, 10); end.writeUInt32LE(directory.length, 12); end.writeUInt32LE(offset, 16); end.writeUInt16LE(comment.length, 20)
  return Buffer.concat([...local, directory, end, comment])
}

// Independent directory inspection for unchanged compressed bytes and metadata.
function records(zip: Buffer) {
  let end = zip.length - 22
  while (end >= 0 && zip.readUInt32LE(end) !== 0x06054b50) end--
  const records = []
  let offset = zip.readUInt32LE(end + 16)
  for (let i = 0; i < zip.readUInt16LE(end + 10); i++) {
    const nameLength = zip.readUInt16LE(offset + 28), extra = zip.readUInt16LE(offset + 30), comment = zip.readUInt16LE(offset + 32), local = zip.readUInt32LE(offset + 42)
    const localNameLength = zip.readUInt16LE(local + 26), data = local + 30 + localNameLength + zip.readUInt16LE(local + 28), compressed = zip.readUInt32LE(offset + 20)
    records.push({ name: zip.subarray(offset + 46, offset + 46 + nameLength).toString(), offset, local, data, compressed, size: zip.readUInt32LE(offset + 24), crc: zip.readUInt32LE(offset + 16), payload: zip.subarray(data, data + compressed), extra: zip.subarray(offset + 46 + nameLength, offset + 46 + nameLength + extra), comment: zip.subarray(offset + 46 + nameLength + extra, offset + 46 + nameLength + extra + comment) })
    offset += 46 + nameLength + extra + comment
  }
  return { records, end }
}

test('renames both LUTs while preserving compressed payloads, descriptors, extras and comments', async () => {
  const original = fixture(), untouched = Buffer.from(original), result = Buffer.from(renameZipEntries(arrayBuffer(original), mapping))
  assert.deepEqual(original, untouched)
  const before = records(original), after = records(result)
  assert.deepEqual(after.records.map(entry => entry.name), ['C200CA.cube', 'C200CAVLOG.cube', 'README.txt'])
  for (let i = 0; i < files.length; i++) {
    const a = before.records[i], b = after.records[i]
    assert.equal(a.crc, b.crc); assert.equal(a.size, b.size); assert.deepEqual(a.payload, b.payload); assert.deepEqual(a.extra, b.extra); assert.deepEqual(a.comment, b.comment)
    const descriptorLength = files[i].descriptor === 'signed' ? 16 : files[i].descriptor ? 12 : 0
    assert.deepEqual(original.subarray(a.data + a.compressed, a.data + a.compressed + descriptorLength), result.subarray(b.data + b.compressed, b.data + b.compressed + descriptorLength))
    assert.deepEqual(Buffer.from(await extractZipEntry(arrayBuffer(result), b.name, files[i].data.length)), files[i].data)
  }
  assert.deepEqual(original.subarray(before.end + 22), result.subarray(after.end + 22))
})

test('real camera ZIP preserves every LUT byte and all licensing/provenance files', async () => {
  const path = new URL('../public/luts/fujifilm_c200__fujifilm_crystal_archive_typeii/0001LUTS.zip', import.meta.url)
  const original = await fs.readFile(path), renamed = renameZipEntries(arrayBuffer(original), mapping), output = records(Buffer.from(renamed))
  for (const before of records(original).records) {
    const nextName = mapping[before.name as keyof typeof mapping] || before.name, after = output.records.find(entry => entry.name === nextName)!
    assert(after); assert.deepEqual(after.payload, before.payload); assert.equal(after.crc, before.crc)
    assert.deepEqual(Buffer.from(await extractZipEntry(renamed, nextName, before.size)), Buffer.from(await extractZipEntry(arrayBuffer(original), before.name, before.size)))
  }
})

test('rejects unsafe, missing, non-LUT, long and case-insensitively colliding mappings', () => {
  const original = arrayBuffer(fixture())
  for (const names of [
    {}, { '0001STD.cube': '../BAD.cube' }, { '0001STD.cube': `${'A'.repeat(251)}.cube` }, { '0001STD.cube': 'HAS SPACE.cube' },
    { 'README.txt': 'README.cube' }, { 'MISSING.cube': 'VALID.cube' }, { '../0001STD.cube': 'VALID.cube' },
    { '0001STD.cube': 'C200CA.cube', '0001VLOG.cube': 'c200ca.cube' }, { '0001STD.cube': '0001VLOG.cube' },
  ]) assert.throws(() => renameZipEntries(original, names), /ZIP/)
  assert.doesNotThrow(() => renameZipEntries(original, { '0001STD.cube': 'Vision3200TCA.cube' }))
})

test('rejects malformed headers, size/offset mismatches, descriptors, encryption and ZIP64', () => {
  const original = fixture(), { records: entries, end } = records(original), first = entries[0], second = entries[1]
  const mutations: ((zip: Buffer) => void)[] = [
    zip => { zip.writeUInt16LE(1, end + 4) },
    zip => { zip.writeUInt32LE(0xffffffff, end + 12) },
    zip => { zip.writeUInt32LE(1, first.offset + 42) },
    zip => { zip.writeUInt32LE(first.local, second.offset + 42) },
    zip => { zip.writeUInt16LE(0x801, first.offset + 8) },
    zip => { zip.writeUInt16LE(99, first.offset + 10) },
    zip => { zip.writeUInt16LE(45, first.offset + 6) },
    zip => { zip.writeUInt32LE(0xffffffff, first.offset + 20) },
    zip => { zip[first.local + 30] ^= 1 },
    zip => { zip.writeUInt16LE(1, first.offset + 46 + '0001STD.cube'.length) },
    zip => { zip.writeUInt16LE(0x7075, first.offset + 46 + '0001STD.cube'.length) },
    zip => { zip.writeUInt32LE(0, first.data + first.compressed + 4) },
    zip => { zip.writeUInt32LE(1, first.local + 18) },
    zip => { zip.writeUInt16LE(65535, first.offset + 28) },
  ]
  for (const mutate of mutations) { const bad = Buffer.from(original); mutate(bad); assert.throws(() => renameZipEntries(arrayBuffer(bad), mapping), /ZIP/) }
  for (const truncated of [original.subarray(0, 5), original.subarray(0, -1)]) assert.throws(() => renameZipEntries(arrayBuffer(truncated), mapping), /ZIP/)
})
