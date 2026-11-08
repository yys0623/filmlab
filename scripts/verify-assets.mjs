import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { gunzipSync } from 'node:zlib';
import assert from 'node:assert/strict';
import { extractZipEntry } from '../src/assets.ts';
import { verifyCameraStd } from './verify-camera-std.mjs';
import { verifyPrintTiming } from './verify-print-timing.mjs';
import { verifyGallery } from './verify-gallery.mjs';
import { verifySuppliedFuji } from './verify-supplied-fuji.mjs';
import { assertLookInventory } from './look-inventory.mjs';
const root = path.resolve(process.argv[2] || 'public');
const catalog = JSON.parse(await fs.readFile(path.join(root, 'catalog.json'), 'utf8'));
assert.equal(catalog.schemaVersion, 2);
assertLookInventory(catalog);
const seenIds = new Set(), seenNames = new Set();
let assets = 0;
const hash = data => createHash('sha256').update(data).digest('hex');
for (const sample of catalog.samples) {
  assert.equal(sample.previewLut, 'std');
  const bytes = await fs.readFile(path.join(root, sample.path));
  if (sample.preparedSha256) assert.equal(hash(bytes), sample.preparedSha256);
}
for (const combo of catalog.combinations) {
  assert(!seenIds.has(combo.id)); seenIds.add(combo.id);
  const film = catalog.films.find(f => f.id === combo.film); assert(film);
  assert.notEqual(film.type, 'official', 'Retired official FUJIFILM film remains');
  if (film.type === 'positive') {
    assert.equal(combo.paper, null); assert.equal(combo.processMode, 'positive_direct');
  } else if (combo.processMode === 'negative_digital') {
    assert.equal(combo.paper, null); assert(combo.id.endsWith('__digital_scan'));
    assert(combo.qa.referenceModel?.startsWith('film-lab-'));
  } else {
    assert(catalog.papers.some(p => p.id === combo.paper)); assert.equal(combo.processMode, 'negative_print');
  }
  assert.equal(combo.status, 'ready');
  for (const asset of Object.values(combo.files)) {
    const local = path.join(root, asset.path);
    assert(local.startsWith(root + path.sep));
    const bytes = await fs.readFile(local);
    if (asset.encoding === 'zip-entry') {
      assert.equal(asset.path, combo.files.zip.path);
      assert.equal(bytes.length, asset.transferBytes); assert.equal(hash(bytes), asset.transferSha256);
      const raw = Buffer.from(await extractZipEntry(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength), asset.name, asset.bytes));
      assert.equal(raw.length, asset.bytes); assert.equal(hash(raw), asset.sha256);
    } else if (asset.encoding === 'gzip') {
      assert.equal(bytes.length, asset.transferBytes); assert.equal(hash(bytes), asset.transferSha256);
      const raw = gunzipSync(bytes); assert.equal(raw.length, asset.bytes); assert.equal(hash(raw), asset.sha256);
    } else { assert.equal(bytes.length, asset.bytes); assert.equal(hash(bytes), asset.sha256); }
    assets++;
  }
  assert.notEqual(combo.files.vlog.sha256, combo.files.std.sha256);
  for (const key of ['std', 'vlog']) {
    const file = combo.files[key]; assert(!seenNames.has(file.name)); seenNames.add(file.name);
    assert(file.name.split('.')[0].length <= 8);
  }
}
for (const film of catalog.films) {
  // Optional cast variants are paired and counted separately by assertLookInventory.
  const choices = catalog.combinations.filter(c => c.film === film.id && !c.castBaseId);
  assert.equal(choices.length, film.type === 'positive' ? 1 : catalog.papers.length + 1);
  assert.equal(new Set(choices.map(c => `${c.processMode}:${c.paper}`)).size, choices.length);
}
for (const [status, count] of Object.entries(catalog.counts)) assert.equal(count, catalog.combinations.filter(c => c.status === status).length);
const gallery = await verifyGallery(root, catalog);
const suppliedFuji = await verifySuppliedFuji(root, catalog);
const cameraStd = await verifyCameraStd(root, catalog);
const printTiming = await verifyPrintTiming(root, catalog);
console.log(JSON.stringify({ passed: true, combinations: seenIds.size, cubes: cameraStd.luts + suppliedFuji.luts, assets, counts: catalog.counts, cameraStd, printTiming, suppliedFuji, gallery }, null, 2));
