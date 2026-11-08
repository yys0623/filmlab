const invalidZip = () => new Error('ZIP 다운로드 파일명을 변경하지 못했습니다. 페이지를 새로고침해 주세요.')

/**
 * Rename LUT members only after fetchVerifiedAsset authenticates the archive.
 * ZIP32 stored/deflated payloads, CRCs, descriptors and ancillary files remain
 * byte-for-byte unchanged. Only names and the corresponding offsets change.
 */
export function renameZipEntries(buffer: ArrayBuffer, names: Record<string, string>): ArrayBuffer {
  const view = new DataView(buffer), bytes = new Uint8Array(buffer)
  const within = (offset: number, size: number, limit = bytes.length) => {
    if (!Number.isSafeInteger(offset) || !Number.isSafeInteger(size) || offset < 0 || size < 0 || offset + size > limit) throw invalidZip()
  }
  if (!names || typeof names !== 'object' || Array.isArray(names)) throw invalidZip()
  const mappings = Object.entries(names)
  if (!mappings.length || mappings.some(([from, to]) => !/^[A-Za-z0-9]+\.cube$/.test(from) || typeof to !== 'string' || !/^[A-Za-z0-9]{1,250}\.cube$/.test(to))) throw invalidZip()
  const replacements = new Map(mappings)
  const utf8 = new TextDecoder('utf-8', { fatal: true }), encoder = new TextEncoder()
  const nameAt = (offset: number, length: number) => {
    try { return utf8.decode(bytes.subarray(offset, offset + length)) }
    catch { throw invalidZip() }
  }
  const extraAt = (offset: number, length: number, renamed: boolean) => {
    const stop = offset + length
    while (offset < stop) {
      within(offset, 4, stop)
      const id = view.getUint16(offset, true), size = view.getUint16(offset + 2, true)
      // ZIP64 and alternate Unicode paths would need their own rewriting.
      if (id === 1 || (renamed && id === 0x7075)) throw invalidZip()
      offset += 4
      within(offset, size, stop)
      offset += size
    }
  }
  let end = -1
  for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 22 - 65535); i--) {
    if (view.getUint32(i, true) === 0x06054b50 && i + 22 + view.getUint16(i + 20, true) === bytes.length) { end = i; break }
  }
  if (end < 0) throw invalidZip()
  const count = view.getUint16(end + 10, true), directorySize = view.getUint32(end + 12, true), directoryOffset = view.getUint32(end + 16, true)
  if (!count || count === 0xffff || view.getUint16(end + 4, true) || view.getUint16(end + 6, true) || view.getUint16(end + 8, true) !== count || directorySize === 0xffffffff || directoryOffset === 0xffffffff || directoryOffset + directorySize !== end) throw invalidZip()
  within(directoryOffset, directorySize, end)
  type Entry = { name: string; replacement: Uint8Array; renamed: boolean; central: number; centralEnd: number; nameLength: number; local: number; localEnd: number; localNameLength: number; newLocal: number; flags: number; method: number; crc: number; compressed: number; size: number }
  const entries: Entry[] = [], originalNames = new Set<string>(), outputNames = new Set<string>()
  let cursor = directoryOffset
  for (let i = 0; i < count; i++) {
    within(cursor, 46, end)
    if (view.getUint32(cursor, true) !== 0x02014b50) throw invalidZip()
    const flags = view.getUint16(cursor + 8, true), method = view.getUint16(cursor + 10, true), crc = view.getUint32(cursor + 16, true)
    const compressed = view.getUint32(cursor + 20, true), size = view.getUint32(cursor + 24, true), local = view.getUint32(cursor + 42, true)
    const nameLength = view.getUint16(cursor + 28, true), extraLength = view.getUint16(cursor + 30, true), commentLength = view.getUint16(cursor + 32, true)
    if ((flags & ~0x080e) || (method !== 0 && method !== 8) || view.getUint16(cursor + 6, true) > 20 || view.getUint16(cursor + 34, true) || compressed === 0xffffffff || size === 0xffffffff || local === 0xffffffff || local >= directoryOffset || (method === 0 && compressed !== size)) throw invalidZip()
    within(cursor + 46, nameLength + extraLength + commentLength, end)
    const name = nameAt(cursor + 46, nameLength), output = replacements.get(name) || name, renamed = replacements.has(name)
    if (!name || /[\x00-\x1f\\/]/.test(name) || name === '.' || name === '..' || originalNames.has(name.toLowerCase()) || outputNames.has(output.toLowerCase())) throw invalidZip()
    originalNames.add(name.toLowerCase()); outputNames.add(output.toLowerCase())
    extraAt(cursor + 46 + nameLength, extraLength, renamed)
    const centralEnd = cursor + 46 + nameLength + extraLength + commentLength
    entries.push({ name, replacement: encoder.encode(output), renamed, central: cursor, centralEnd, nameLength, local, localEnd: 0, localNameLength: 0, newLocal: 0, flags, method, crc, compressed, size })
    cursor = centralEnd
  }
  if (cursor !== end || mappings.some(([name]) => !entries.some(entry => entry.name === name))) throw invalidZip()

  // Validate every local record, including descriptors and unrenamed files.
  const localEntries = [...entries].sort((a, b) => a.local - b.local)
  let localCursor = 0
  for (const entry of localEntries) {
    const local = entry.local
    if (local !== localCursor) throw invalidZip() // No overlapping/hidden records or executable prefix.
    within(local, 30, directoryOffset)
    if (view.getUint32(local, true) !== 0x04034b50 || view.getUint16(local + 4, true) > 20 || view.getUint16(local + 6, true) !== entry.flags || view.getUint16(local + 8, true) !== entry.method) throw invalidZip()
    const nameLength = view.getUint16(local + 26, true), extraLength = view.getUint16(local + 28, true)
    within(local + 30, nameLength + extraLength, directoryOffset)
    if (nameLength !== entry.nameLength || !bytes.subarray(local + 30, local + 30 + nameLength).every((value, index) => value === bytes[entry.central + 46 + index])) throw invalidZip()
    extraAt(local + 30 + nameLength, extraLength, entry.renamed)
    const data = local + 30 + nameLength + extraLength
    within(data, entry.compressed, directoryOffset)
    localCursor = data + entry.compressed
    if (entry.flags & 8) {
      for (const [offset, expected] of [[14, entry.crc], [18, entry.compressed], [22, entry.size]]) {
        const value = view.getUint32(local + offset, true)
        if (value !== 0 && value !== expected) throw invalidZip()
      }
      within(localCursor, 12, directoryOffset)
      // A CRC may equal the optional descriptor signature: match all fields.
      const descriptorMatches = (offset: number) => offset + 12 <= directoryOffset && view.getUint32(offset, true) === entry.crc && view.getUint32(offset + 4, true) === entry.compressed && view.getUint32(offset + 8, true) === entry.size
      if (view.getUint32(localCursor, true) === 0x08074b50 && descriptorMatches(localCursor + 4)) localCursor += 16
      else if (descriptorMatches(localCursor)) localCursor += 12
      else throw invalidZip()
    } else if (view.getUint32(local + 14, true) !== entry.crc || view.getUint32(local + 18, true) !== entry.compressed || view.getUint32(local + 22, true) !== entry.size) throw invalidZip()
    entry.localNameLength = nameLength; entry.localEnd = localCursor
  }
  if (localCursor !== directoryOffset) throw invalidZip()

  const chunks: Uint8Array[] = []
  let size = 0
  const append = (chunk: Uint8Array) => { chunks.push(chunk); size += chunk.length; if (size >= 0xffffffff) throw invalidZip() }
  for (const entry of localEntries) {
    entry.newLocal = size
    const header = bytes.slice(entry.local, entry.local + 30)
    new DataView(header.buffer).setUint16(26, entry.replacement.length, true)
    append(header); append(entry.replacement)
    append(bytes.subarray(entry.local + 30 + entry.localNameLength, entry.localEnd))
  }
  const newDirectoryOffset = size
  for (const entry of entries) {
    const header = bytes.slice(entry.central, entry.central + 46), headerView = new DataView(header.buffer)
    headerView.setUint16(28, entry.replacement.length, true); headerView.setUint32(42, entry.newLocal, true)
    append(header); append(entry.replacement)
    append(bytes.subarray(entry.central + 46 + entry.nameLength, entry.centralEnd))
  }
  const newDirectorySize = size - newDirectoryOffset, trailer = bytes.slice(end), trailerView = new DataView(trailer.buffer)
  trailerView.setUint32(12, newDirectorySize, true); trailerView.setUint32(16, newDirectoryOffset, true)
  append(trailer)
  const result = new Uint8Array(size)
  let offset = 0
  for (const chunk of chunks) { result.set(chunk, offset); offset += chunk.length }
  return result.buffer
}
