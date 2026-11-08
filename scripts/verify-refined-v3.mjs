import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { extractZipEntry } from '../src/assets.ts';
import { parseStdCube } from '../src/lut.ts';
import { assertNoPrivatePaths, textEntries } from './verify-legacy-v3.mjs';

const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const METHOD = 'legacy-v3-soft-gamut-v1';
export async function verifyRefinedV3(rootDir, catalog) {
  const root = path.resolve(rootDir), directory = path.join(root, 'refined-v3');
  const info = await fs.lstat(directory).catch(error => { if (error.code === 'ENOENT') return null; throw error; });
  if (!info) return { present: false, combinations: 0, luts: 0, archives: 0 };
  assert(info.isDirectory() && !info.isSymbolicLink(), 'Refined sidecar must be a real directory');
  const manifestPath = path.join(directory, 'manifest.json'), manifestInfo = await fs.lstat(manifestPath);
  assert(manifestInfo.isFile() && !manifestInfo.isSymbolicLink(), 'Refined manifest must be a real file');
  const manifest = JSON.parse(await fs.readFile(manifestPath, 'utf8'));
  const legacy = JSON.parse(await fs.readFile(path.join(root, 'legacy-v3/manifest.json'), 'utf8'));
  assert.equal(manifest.schemaVersion, 1);
  assert.equal(manifest.method, METHOD);
  assert.match(manifest.baselineCatalogSha256, /^[a-f0-9]{64}$/, 'Invalid refined baseline catalog hash');
  assert.equal(manifest.baselineCatalogSha256, legacy.baselineCatalogSha256, 'Refined baseline catalog differs from legacy');
  assert.equal(manifest.knee, .9, 'Unexpected refined gamut knee');
  assertNoPrivatePaths(manifest, 'refined manifest');
  const expected = catalog.combinations.filter(combo => combo.processMode !== 'reference_interpretation' && !combo.id.endsWith('__reference'));
  assert.equal(expected.length, 238, 'Refined requires all 238 active looks');
  assert.deepEqual(manifest.combinations.map(record => record.id).sort(), expected.map(combo => combo.id).sort(), 'Refined combination IDs differ from the active catalog');
  assert.deepEqual((await fs.readdir(directory)).sort(), ['manifest.json', ...expected.map(combo => combo.id)].sort(), 'Refined directory inventory differs from the manifest');
  const currentById = new Map(expected.map(combo => [combo.id, combo]));
  const legacyById = new Map(legacy.combinations.map(record => [record.id, record]));
  const parsed = new Set();
  for (const record of manifest.combinations) {
    assert.match(record.id, /^[a-z0-9_]+$/, 'Unsafe refined combination id');
    const current = currentById.get(record.id), original = legacyById.get(record.id), number = String(current.number).padStart(4, '0');
    assert.equal(current.status, 'ready');
    assert(original, `Missing legacy source for refined look: ${record.id}`);
    assert.equal(record.sourceVlogSha256, current.files.vlog.sha256, `Changed refined V-Log source: ${record.id}`);
    assert.equal(record.sourceLegacySha256, original.files.stdLegacy.sha256, `Changed refined legacy source: ${record.id}`);
    assert.deepEqual(Object.keys(record.files).sort(), ['stdRefined', 'zipRefined']);
    const std = record.files.stdRefined, zip = record.files.zipRefined;
    assert.equal(record.qa.method, METHOD);
    assert(Array.isArray(record.qa.warnings) && record.qa.warnings.every(warning => typeof warning === 'string'));
    assert(record.qa.stdVsDirectEngine?.tetrahedral, 'Refined QA metric is missing');
    for (const key of ['mean', 'p99', 'max']) assert(Number.isFinite(record.qa.stdVsDirectEngine.tetrahedral[key]), `Invalid refined QA ${key}`);
    assert.equal(std.encoding, 'zip-entry');
    assert.equal(zip.encoding, undefined);
    assert.equal(std.name, `${number}STR.cube`);
    assert.equal(zip.name, `${number}V3R.zip`);
    for (const asset of [std, zip]) if (asset.downloadName !== undefined) assert.equal(asset.downloadName, asset.name);
    assert.equal(zip.path, `/refined-v3/${record.id}/${zip.name}`, 'Unsafe refined ZIP path');
    assert.equal(std.path, zip.path);
    assert.equal(std.transferBytes, zip.bytes);
    assert.equal(std.transferSha256, zip.sha256);
    const comboDirectory = path.join(directory, record.id), comboInfo = await fs.lstat(comboDirectory);
    assert(comboInfo.isDirectory() && !comboInfo.isSymbolicLink(), 'Refined combination must be a real directory');
    assert.deepEqual(await fs.readdir(comboDirectory), [zip.name], 'Unexpected refined sidecar file');
    const zipPath = path.join(comboDirectory, zip.name), zipInfo = await fs.lstat(zipPath);
    assert(zipInfo.isFile() && !zipInfo.isSymbolicLink(), 'Refined ZIP must be a real file');
    const bytes = await fs.readFile(zipPath), buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    assert.equal(bytes.length, zip.bytes, `Refined ZIP size: ${record.id}`);
    assert.equal(hash(bytes), zip.sha256, `Refined ZIP hash: ${record.id}`);
    for (const [asset, tag] of [[std, 'STD'], [current.files.vlog, 'VLOG']]) {
      const raw = Buffer.from(await extractZipEntry(buffer, asset.name, asset.bytes));
      assert.equal(hash(raw), asset.sha256, `Refined ${tag} hash: ${record.id}`);
      const cacheKey = `${tag}:${asset.sha256}`;
      if (!parsed.has(cacheKey)) {
        const text = raw.toString('utf8');
        assert.equal(text.split(/\r?\n/)[1], `#LUMIXPHOTOSTYLE ${tag}`, `Refined ${tag} tag: ${record.id}`);
        parseStdCube(tag === 'STD' ? text : text.replace('#LUMIXPHOTOSTYLE VLOG', '#LUMIXPHOTOSTYLE STD'));
        parsed.add(cacheKey);
      }
    }
    let qaFound = false;
    for (const entry of textEntries(bytes)) {
      assert(entry.bytes <= 2 * 1024 * 1024, 'Refined text metadata is unexpectedly large');
      const text = new TextDecoder().decode(await extractZipEntry(buffer, entry.name, entry.bytes));
      const value = entry.name.endsWith('.json') ? JSON.parse(text) : text;
      assertNoPrivatePaths(value, `refined ZIP ${record.id}/${entry.name}`);
      if (entry.name === 'qa.json') { assert.deepEqual(value, record.qa, `Refined QA differs from archive: ${record.id}`); qaFound = true; }
    }
    assert(qaFound, `Refined QA is missing from archive: ${record.id}`);
  }
  return { present: true, combinations: expected.length, luts: expected.length, archives: expected.length };
}
