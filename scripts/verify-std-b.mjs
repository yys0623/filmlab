import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { extractZipEntry } from '../src/assets.ts';
import { parseStdCube } from '../src/lut.ts';

const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const privatePath = /(?:\/(?:Users|home|Volumes|private|tmp)\/|file:\/\/|[A-Z]:[\\/]+Users[\\/]|(?:^|[\/\\])(?:sample-study|std-precurve-baseline)(?:[\/\\]|$))/i;
const oldVariants = /(?:legacy-v3|refined-v3|\d{4}(?:STD|STR|STL)\.cube)/;

export function zipEntries(bytes) {
  let end = -1;
  for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 22 - 65535); i--) {
    if (bytes.readUInt32LE(i) === 0x06054b50 && i + 22 + bytes.readUInt16LE(i + 20) === bytes.length) { end = i; break; }
  }
  assert(end >= 0, 'ZIP directory missing');
  const entries = [];
  let cursor = bytes.readUInt32LE(end + 16);
  for (let i = 0; i < bytes.readUInt16LE(end + 10); i++) {
    assert(cursor + 46 <= end && bytes.readUInt32LE(cursor) === 0x02014b50, 'Invalid ZIP directory');
    const nameLength = bytes.readUInt16LE(cursor + 28);
    assert(cursor + 46 + nameLength <= end, 'Invalid ZIP filename');
    entries.push({ name: bytes.subarray(cursor + 46, cursor + 46 + nameLength).toString('utf8'), bytes: bytes.readUInt32LE(cursor + 24) });
    cursor += 46 + nameLength + bytes.readUInt16LE(cursor + 30) + bytes.readUInt16LE(cursor + 32);
  }
  assert.equal(cursor, end, 'ZIP directory length');
  return entries;
}

export function assertBContract(combo) {
  assert.equal(combo.stdVariant, 'B', `Wrong STD variant: ${combo.id}`);
  assert(!combo.stdVariants && !combo.files.stdB && !combo.files.stdLegacy && !combo.files.stdRefined, 'Alternate STD variant remains');
  assert.deepEqual(Object.keys(combo.files).sort(), ['provenance', 'qa', 'std', 'vlog', 'zip']);
  assert.equal(combo.files.std.name, `${String(combo.number).padStart(4, '0')}STB.cube`);
  assert.equal(combo.qa.stdVariant, 'B');
  assert.equal(combo.qa.stdGeneration, 'exported-vlog-single-tone-precurve-v4');
  assert.equal(combo.qa.singleTonePrecurve.variant, 'B');
  assert.equal(combo.qa.singleTonePrecurve.method, 'film-lab-single-tone-precurve-v1');
  for (const key of ['perImageAdaptation', 'vlogModified', 'outputColourEdits', 'neutralCastRemoval', 'chromaGain']) {
    assert.equal(combo.qa.singleTonePrecurve[key], false);
  }
  assert.equal(combo.qa.singleTonePrecurve.source.sha256, combo.files.vlog.sha256);
  assert(!combo.qa.stdVariants && !combo.qa.stdBVsDirectEngine && !combo.qa.photoPixelFidelityB);
  assert(combo.qa.stdVsDirectEngine.tetrahedral && combo.qa.stdVsDirectEngine.trilinear);
  assert.equal(combo.qa.grayResponse.rgb.length, 129);
  assert(!('A' in combo.qa.grayResponse) && !('B' in combo.qa.grayResponse));
  assert.deepEqual(combo.qa.grayResponse.inputCodes, Array.from({ length: 129 }, (_, index) => index / 128 * 255));
  assert(combo.qa.grayResponse.rgb.every(rgb => rgb.length === 3 && rgb.every(value => Number.isFinite(value) && value >= 0 && value <= 255)));
  assert(combo.qa.warnings.every(warning => !warning.startsWith('STD A ')));
  assert.equal(combo.previewMode, 'runtime-std');
  assert.deepEqual(combo.previews, {});
}

export async function verifyStdB(rootDir, catalog, expectedCount = 238) {
  const root = path.resolve(rootDir);
  assert.equal(catalog.combinations.length, expectedCount, 'B-only look count');
  assert(!catalog.referenceStudy, 'Retired reference interpretations remain');
  for (const name of ['legacy-v3', 'refined-v3', 'audit', 'research/reference-looks.json']) {
    assert(!(await fs.lstat(path.join(root, name)).catch(error => { if (error.code === 'ENOENT') return null; throw error; })), `Retired asset tree remains: ${name}`);
  }
  assert.deepEqual((await fs.readdir(path.join(root, 'luts'))).sort(), catalog.combinations.map(combo => combo.id).sort(), 'LUT inventory differs from B catalog');
  const parsed = new Set();
  for (const combo of catalog.combinations) {
    assertBContract(combo);
    assert(!privatePath.test(JSON.stringify(combo)), `Private path in ${combo.id}`);
    assert(!oldVariants.test(JSON.stringify(combo)), `Retired STD reference in ${combo.id}`);
    const zip = combo.files.zip;
    assert.equal(zip.path, `/luts/${combo.id}/${String(combo.number).padStart(4, '0')}LUTS.zip`);
    const bytes = await fs.readFile(path.join(root, zip.path));
    assert.equal(bytes.length, zip.bytes); assert.equal(hash(bytes), zip.sha256);
    const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    // The full extractor validates ZIP flags, entry bounds and local headers.
    for (const [key, tag] of [['std', 'STD'], ['vlog', 'VLOG']]) {
      const asset = combo.files[key];
      const raw = Buffer.from(await extractZipEntry(buffer, asset.name, asset.bytes));
      assert.equal(hash(raw), asset.sha256, `Changed ${tag} cube: ${combo.id}`);
      if (!parsed.has(asset.sha256)) {
        const text = raw.toString('utf8');
        assert.equal(text.split(/\r?\n/)[1], `#LUMIXPHOTOSTYLE ${tag}`);
        parseStdCube(tag === 'STD' ? text : text.replace('#LUMIXPHOTOSTYLE VLOG', '#LUMIXPHOTOSTYLE STD'));
        parsed.add(asset.sha256);
      }
      if (!asset.encoding) assert((await fs.readFile(path.join(root, asset.path))).equals(raw), `Raw/ZIP ${tag} disagreement`);
      else {
        assert.equal(asset.encoding, 'zip-entry'); assert.equal(asset.path, zip.path);
        assert.equal(asset.transferBytes, zip.bytes); assert.equal(asset.transferSha256, zip.sha256);
      }
    }
    const entries = zipEntries(bytes);
    const expected = [combo.files.std.name, combo.files.vlog.name, 'README.txt', 'CHANGELOG.txt', 'qa.json', 'provenance.json', 'SPEKTRAFILM_LICENSE.txt', ...(combo.officialSource ? ['FUJIFILM_NOTICE.txt'] : [])].sort();
    assert.deepEqual(entries.map(entry => entry.name).sort(), expected, `Unexpected/retired ZIP entry: ${combo.id}`);
    const expectedDirectory = [...expected.filter(name => !name.endsWith('.cube') || !combo.files.std.encoding), zip.name, 'metadata.json'].sort();
    assert.deepEqual((await fs.readdir(path.join(root, 'luts', combo.id))).sort(), expectedDirectory, `Unexpected/retired raw asset: ${combo.id}`);
    for (const entry of entries.filter(entry => !entry.name.endsWith('.cube'))) {
      assert(entry.bytes < 2 * 1024 * 1024);
      const raw = Buffer.from(await extractZipEntry(buffer, entry.name, entry.bytes));
      assert((await fs.readFile(path.join(root, 'luts', combo.id, entry.name))).equals(raw), `Text/ZIP disagreement: ${combo.id}/${entry.name}`);
      const text = raw.toString('utf8');
      assert(!privatePath.test(text) && !oldVariants.test(text), `Private or retired reference: ${combo.id}/${entry.name}`);
      if (entry.name === 'qa.json') assert.deepEqual(JSON.parse(text), combo.qa, `QA/catalog disagreement: ${combo.id}`);
      if (entry.name === 'provenance.json') {
        const provenance = JSON.parse(text);
        assert.equal(provenance.stdVariant, 'B');
        assert.equal(provenance.singleTonePrecurve.variant, 'B');
        assert(!provenance.stdVariants);
        assert.equal(provenance.distribution.stdSha256, combo.files.std.sha256);
        assert.equal(provenance.distribution.vlogSha256, combo.files.vlog.sha256);
        assert.equal(provenance.distribution.colourDataRecomputed, false);
      }
    }
    assert.deepEqual(JSON.parse(await fs.readFile(path.join(root, 'luts', combo.id, 'metadata.json'), 'utf8')), combo);
  }
  return { variant: 'B', combinations: catalog.combinations.length, luts: catalog.combinations.length * 2, archives: catalog.combinations.length };
}
