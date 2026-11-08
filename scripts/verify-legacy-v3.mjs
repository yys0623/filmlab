import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { extractZipEntry } from '../src/assets.ts';
import { parseStdCube } from '../src/lut.ts';

const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const privatePath = /(?:\/(?:Users|home|Volumes|private|tmp)\/|file:\/\/|[A-Z]:[\\/]+Users[\\/]|(?:^|[\/\\])(?:sample-study|std-precurve-baseline)(?:[\/\\]|$))/i;
const active = combo => combo.processMode !== 'reference_interpretation' && !combo.id.endsWith('__reference');
const qaFields = ['stdGeneration', 'jpgToneProtection', 'stdVsDirectEngine', 'stdVsContinuousComposition', 'warnings'];
export function assertNoPrivatePaths(value, location) {
  if (typeof value === 'string') assert(!privatePath.test(value), `Private baseline path in ${location}`);
  else if (Array.isArray(value)) value.forEach(child => assertNoPrivatePaths(child, location));
  else if (value && typeof value === 'object') Object.values(value).forEach(child => assertNoPrivatePaths(child, location));
}

// The shared ZIP extractor has already validated the full directory. Read its
// text-entry sizes so provenance can also be checked without unpacking to disk.
export function textEntries(bytes) {
  let end = -1;
  for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 22 - 65535); i--) {
    if (bytes.readUInt32LE(i) === 0x06054b50 && i + 22 + bytes.readUInt16LE(i + 20) === bytes.length) { end = i; break; }
  }
  assert(end >= 0, 'Legacy ZIP directory is missing');
  const entries = [];
  let cursor = bytes.readUInt32LE(end + 16);
  for (let i = 0; i < bytes.readUInt16LE(end + 10); i++) {
    const nameLength = bytes.readUInt16LE(cursor + 28);
    const name = bytes.subarray(cursor + 46, cursor + 46 + nameLength).toString('utf8');
    if (/\.(json|txt)$/i.test(name)) entries.push({ name, bytes: bytes.readUInt32LE(cursor + 24) });
    cursor += 46 + nameLength + bytes.readUInt16LE(cursor + 30) + bytes.readUInt16LE(cursor + 32);
  }
  return entries;
}

export async function verifyLegacyV3(rootDir, catalog) {
  const root = path.resolve(rootDir), directory = path.join(root, 'legacy-v3');
  const info = await fs.lstat(directory).catch(error => { if (error.code === 'ENOENT') return null; throw error; });
  if (!info) return { present: false, combinations: 0, luts: 0, archives: 0 };
  assert(info.isDirectory() && !info.isSymbolicLink(), 'Legacy sidecar must be a real directory');
  const manifestPath = path.join(directory, 'manifest.json');
  const manifestInfo = await fs.lstat(manifestPath);
  assert(manifestInfo.isFile() && !manifestInfo.isSymbolicLink(), 'Legacy manifest must be a real file');
  const manifest = JSON.parse(await fs.readFile(manifestPath, 'utf8'));
  assert.equal(manifest.schemaVersion, 1, 'Legacy manifest schema');
  assert.equal(manifest.method, 'legacy-v3-baseline', 'Legacy manifest method');
  assertNoPrivatePaths(manifest, 'legacy manifest');
  const expected = catalog.combinations.filter(active);
  assert.equal(expected.length, 238, 'Legacy baseline requires all 238 active looks');
  assert.equal(new Set(expected.map(combo => combo.id)).size, expected.length);
  assert.deepEqual(manifest.combinations.map(combo => combo.id).sort(), expected.map(combo => combo.id).sort(), 'Legacy combination IDs differ from the active catalog');
  assert.deepEqual((await fs.readdir(directory)).sort(), ['manifest.json', ...expected.map(combo => combo.id)].sort(), 'Legacy sidecar directory inventory differs from the manifest');
  const currentById = new Map(expected.map(combo => [combo.id, combo]));
  const parsed = new Set();
  for (const record of manifest.combinations) {
    assert.match(record.id, /^[a-z0-9_]+$/, 'Unsafe legacy combination id');
    const current = currentById.get(record.id), number = String(current.number).padStart(4, '0');
    const std = record.files.stdLegacy, zip = record.files.zipLegacy;
    assert.equal(current.status, 'ready');
    assert.equal(record.sourceVlogSha256, current.files.vlog.sha256, `Changed source V-Log: ${record.id}`);
    assert.equal(record.qa.jpgToneProtection.method, 'film-lab-jpg-tone-protection-v1');
    assert.equal(record.qa.jpgToneProtection.vlogModified, false);
    assert.equal(std.encoding, 'zip-entry');
    assert.equal(zip.encoding, undefined, 'Legacy ZIP must be a raw archive');
    assert.equal(std.name, `${number}STD.cube`);
    assert.equal(std.downloadName, `${number}STL.cube`);
    assert.equal(zip.name, `${number}LUTS.zip`);
    assert.equal(zip.downloadName, `${number}V3.zip`);
    assert.equal(zip.path, `/legacy-v3/${record.id}/${zip.name}`, 'Unsafe legacy ZIP path');
    assert.equal(std.path, zip.path);
    assert.equal(std.transferBytes, zip.bytes);
    assert.equal(std.transferSha256, zip.sha256);
    const comboDirectory = path.join(directory, record.id);
    const comboInfo = await fs.lstat(comboDirectory);
    assert(comboInfo.isDirectory() && !comboInfo.isSymbolicLink(), 'Legacy combination must be a real directory');
    assert.deepEqual(await fs.readdir(comboDirectory), [zip.name], 'Unexpected legacy sidecar file');
    const zipPath = path.join(comboDirectory, zip.name), zipInfo = await fs.lstat(zipPath);
    assert(zipInfo.isFile() && !zipInfo.isSymbolicLink(), 'Legacy ZIP must be a real file');
    const bytes = await fs.readFile(zipPath), buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    assert.equal(bytes.length, zip.bytes, `Legacy ZIP size: ${record.id}`);
    assert.equal(hash(bytes), zip.sha256, `Legacy ZIP hash: ${record.id}`);
    for (const [asset, tag] of [[std, 'STD'], [current.files.vlog, 'VLOG']]) {
      const raw = Buffer.from(await extractZipEntry(buffer, asset.name, asset.bytes));
      assert.equal(hash(raw), asset.sha256, `Legacy ${tag} hash: ${record.id}`);
      const cacheKey = `${tag}:${asset.sha256}`;
      if (!parsed.has(cacheKey)) {
        const text = raw.toString('utf8');
        assert.equal(text.split(/\r?\n/)[1], `#LUMIXPHOTOSTYLE ${tag}`, `Legacy ${tag} tag: ${record.id}`);
        parseStdCube(tag === 'STD' ? text : text.replace('#LUMIXPHOTOSTYLE VLOG', '#LUMIXPHOTOSTYLE STD'));
        parsed.add(cacheKey);
      }
    }
    let qaFound = false;
    for (const entry of textEntries(bytes)) {
      assert(entry.bytes <= 2 * 1024 * 1024, 'Legacy text metadata is unexpectedly large');
      const text = new TextDecoder().decode(await extractZipEntry(buffer, entry.name, entry.bytes));
      const value = entry.name.endsWith('.json') ? JSON.parse(text) : text;
      assertNoPrivatePaths(value, `legacy ZIP ${record.id}/${entry.name}`);
      if (entry.name === 'qa.json') {
        const subset = Object.fromEntries(qaFields.map(key => [key, value[key] ?? null]));
        assert.deepEqual(subset, record.qa, `Legacy QA differs from archive: ${record.id}`);
        qaFound = true;
      }
    }
    assert(qaFound, `Legacy QA is missing from archive: ${record.id}`);
  }
  return { present: true, combinations: expected.length, luts: expected.length, archives: expected.length };
}
