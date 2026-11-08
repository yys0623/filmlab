import type { Asset } from './types'

const invalidZip = () => new Error('ZIP LUT 파일 검증에 실패했습니다. 페이지를 새로고침해 주세요.')

async function verifyBytes(buffer: ArrayBuffer, bytes: number | undefined, sha256: string | undefined): Promise<void> {
  if (!Number.isSafeInteger(bytes) || bytes !== buffer.byteLength || !sha256 || !/^[0-9a-f]{64}$/.test(sha256)) throw new Error('LUT 파일 검증에 실패했습니다. 페이지를 새로고침해 주세요.')
  const digest = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', buffer))).map(n => n.toString(16).padStart(2, '0')).join('')
  if (digest !== sha256) throw new Error('LUT 파일 검증에 실패했습니다. 페이지를 새로고침해 주세요.')
}

// ZIP32 only. The archive is authenticated before this parser is used by the
// fetcher; the extracted file is authenticated again against its raw SHA-256.
export async function extractZipEntry(buffer: ArrayBuffer, name: string, expectedBytes: number): Promise<ArrayBuffer> {
  if (!name || !Number.isSafeInteger(expectedBytes) || expectedBytes < 0) throw invalidZip()
  const view = new DataView(buffer)
  const bytes = new Uint8Array(buffer)
  const length = buffer.byteLength
  const within = (offset: number, size: number, limit = length) => {
    if (!Number.isSafeInteger(offset) || !Number.isSafeInteger(size) || offset < 0 || size < 0 || offset + size > limit) throw invalidZip()
  }
  let end = -1
  for (let i = length - 22; i >= Math.max(0, length - 22 - 65535); i--) {
    if (view.getUint32(i, true) === 0x06054b50 && i + 22 + view.getUint16(i + 20, true) === length) { end = i; break }
  }
  if (end < 0) throw invalidZip()
  const count = view.getUint16(end + 10, true)
  const directorySize = view.getUint32(end + 12, true)
  const directoryOffset = view.getUint32(end + 16, true)
  if (view.getUint16(end + 4, true) !== 0 || view.getUint16(end + 6, true) !== 0 || view.getUint16(end + 8, true) !== count || count === 0xffff || directorySize === 0xffffffff || directoryOffset === 0xffffffff || directoryOffset + directorySize !== end) throw invalidZip()
  within(directoryOffset, directorySize, end)
  const decodeName = (offset: number, size: number) => {
    try { return new TextDecoder('utf-8', { fatal: true }).decode(bytes.subarray(offset, offset + size)) }
    catch { throw invalidZip() }
  }
  const checkExtra = (offset: number, size: number) => {
    const stop = offset + size
    while (offset < stop) {
      within(offset, 4, stop)
      const id = view.getUint16(offset, true), fieldSize = view.getUint16(offset + 2, true)
      if (id === 1) throw invalidZip() // ZIP64 is not supported.
      offset += 4
      within(offset, fieldSize, stop)
      offset += fieldSize
    }
  }
  type Entry = { nameOffset: number; nameLength: number; flags: number; method: number; crc: number; compressed: number; size: number; localOffset: number }
  let chosen: Entry | undefined
  let cursor = directoryOffset
  const names = new Set<string>()
  for (let i = 0; i < count; i++) {
    within(cursor, 46, end)
    if (view.getUint32(cursor, true) !== 0x02014b50) throw invalidZip()
    const flags = view.getUint16(cursor + 8, true), method = view.getUint16(cursor + 10, true)
    const compressed = view.getUint32(cursor + 20, true), size = view.getUint32(cursor + 24, true)
    const nameLength = view.getUint16(cursor + 28, true), extraLength = view.getUint16(cursor + 30, true), commentLength = view.getUint16(cursor + 32, true)
    const localOffset = view.getUint32(cursor + 42, true)
    // Permit UTF-8, deflate options and a data descriptor; reject encryption
    // and every unsupported flag, compression method, disk or ZIP64 marker.
    if ((flags & ~0x080e) !== 0 || (method !== 0 && method !== 8) || view.getUint16(cursor + 6, true) > 20 || view.getUint16(cursor + 34, true) !== 0 || compressed === 0xffffffff || size === 0xffffffff || localOffset === 0xffffffff || localOffset >= directoryOffset || (method === 0 && compressed !== size)) throw invalidZip()
    within(cursor + 46, nameLength + extraLength + commentLength, end)
    const filename = decodeName(cursor + 46, nameLength)
    if (names.has(filename)) throw invalidZip()
    names.add(filename)
    checkExtra(cursor + 46 + nameLength, extraLength)
    if (filename === name) chosen = { nameOffset: cursor + 46, nameLength, flags, method, crc: view.getUint32(cursor + 16, true), compressed, size, localOffset }
    cursor += 46 + nameLength + extraLength + commentLength
  }
  if (cursor !== end) throw invalidZip()
  if (!chosen) throw new Error('ZIP에서 요청한 LUT 파일을 찾지 못했습니다. 페이지를 새로고침해 주세요.')
  if (chosen.size !== expectedBytes) throw invalidZip()
  const local = chosen.localOffset
  within(local, 30, directoryOffset)
  if (view.getUint32(local, true) !== 0x04034b50 || view.getUint16(local + 4, true) > 20 || view.getUint16(local + 6, true) !== chosen.flags || view.getUint16(local + 8, true) !== chosen.method) throw invalidZip()
  const localNameLength = view.getUint16(local + 26, true), localExtraLength = view.getUint16(local + 28, true)
  within(local + 30, localNameLength + localExtraLength, directoryOffset)
  if (localNameLength !== chosen.nameLength || !bytes.subarray(local + 30, local + 30 + localNameLength).every((value, i) => value === bytes[chosen.nameOffset + i])) throw invalidZip()
  checkExtra(local + 30 + localNameLength, localExtraLength)
  const start = local + 30 + localNameLength + localExtraLength
  within(start, chosen.compressed, directoryOffset)
  if (!(chosen.flags & 8)) {
    if (view.getUint32(local + 14, true) !== chosen.crc || view.getUint32(local + 18, true) !== chosen.compressed || view.getUint32(local + 22, true) !== chosen.size) throw invalidZip()
  } else {
    let descriptor = start + chosen.compressed
    within(descriptor, 12, directoryOffset)
    if (view.getUint32(descriptor, true) === 0x08074b50) descriptor += 4
    within(descriptor, 12, directoryOffset)
    if (view.getUint32(descriptor, true) !== chosen.crc || view.getUint32(descriptor + 4, true) !== chosen.compressed || view.getUint32(descriptor + 8, true) !== chosen.size) throw invalidZip()
  }
  const compressed = buffer.slice(start, start + chosen.compressed)
  if (chosen.method === 0) return compressed
  let decompressor: DecompressionStream
  try { decompressor = new DecompressionStream('deflate-raw') }
  catch { throw new Error('이 브라우저는 ZIP LUT 압축 해제를 지원하지 않습니다. 최신 브라우저로 다시 시도해 주세요.') }
  try {
    const reader = new Blob([compressed]).stream().pipeThrough(decompressor).getReader()
    const chunks: Uint8Array[] = []
    let total = 0
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      total += value.byteLength
      if (total > expectedBytes) { await reader.cancel(); throw invalidZip() }
      chunks.push(value)
    }
    if (total !== expectedBytes) throw invalidZip()
    const result = new Uint8Array(total)
    let offset = 0
    for (const chunk of chunks) { result.set(chunk, offset); offset += chunk.length }
    return result.buffer
  } catch { throw invalidZip() }
}

// Shared by downloads and the upload renderer, including packed production LUTs.
export async function fetchVerifiedAsset(asset: Asset): Promise<ArrayBuffer> {
  const response = await fetch(asset.path)
  if (!response.ok) throw new Error('LUT 파일을 가져오지 못했습니다. 다시 시도해 주세요.')
  let buffer = await response.arrayBuffer()
  if (asset.encoding === 'zip-entry') {
    await verifyBytes(buffer, asset.transferBytes, asset.transferSha256)
    buffer = await extractZipEntry(buffer, asset.name, asset.bytes)
  }
  const magic = new Uint8Array(buffer, 0, Math.min(2, buffer.byteLength))
  if (asset.encoding === 'gzip' && magic[0] === 0x1f && magic[1] === 0x8b) {
    buffer = await new Response(new Blob([buffer]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer()
  }
  await verifyBytes(buffer, asset.bytes, asset.sha256)
  return buffer
}
