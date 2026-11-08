import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { extractZipEntry } from '../src/assets.ts';
import { parseStdCube } from '../src/lut.ts';
import { assertLookInventory, publicLookCount, FILM_CAST_METHOD } from './look-inventory.mjs';

export const CAMERA_STD_METHOD = 'camera-vlog-alchemy-v1';
export const ALCHEMY_COMMIT = 'e51ba9a23458ff5c316f630b860eb0201139d126';
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const privatePath = /(?:\/(?:Users|home|Volumes|private|tmp)\/|file:\/\/|[A-Z]:[\\/]+Users[\\/]|(?:^|[\/\\])(?:sample-study|std-precurve-baseline)(?:[\/\\]|$))/i;
const retiredAssets = /(?:legacy-v3|refined-v3|\d{4}(?:STB|STR|STL)\.cube)/;

export function localAssetPath(root, url) {
  assert(typeof url === 'string' && url.startsWith('/') && !url.startsWith('//'), `Invalid local asset path: ${url}`);
  const decoded = decodeURIComponent(url.split(/[?#]/, 1)[0]);
  assert(!decoded.split('/').includes('..') && !decoded.includes('\\'), `Unsafe local asset path: ${url}`);
  const file = path.resolve(root, '.' + decoded);
  assert(file.startsWith(path.resolve(root) + path.sep), `Unsafe local asset path: ${url}`);
  return file;
}

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
    const length = bytes.readUInt16LE(cursor + 28);
    assert(cursor + 46 + length <= end, 'Invalid ZIP filename');
    entries.push({ name: bytes.subarray(cursor + 46, cursor + 46 + length).toString('utf8'), bytes: bytes.readUInt32LE(cursor + 24) });
    cursor += 46 + length + bytes.readUInt16LE(cursor + 30) + bytes.readUInt16LE(cursor + 32);
  }
  assert.equal(cursor, end, 'ZIP directory length');
  assert.equal(new Set(entries.map(entry => entry.name)).size, entries.length, 'Duplicate ZIP entry');
  return entries;
}

function assertMetric(metric) {
  assert(metric && ['mean', 'p95', 'p99', 'max'].every(key => Number.isFinite(metric[key]) && metric[key] >= 0), 'Missing or invalid composition metric');
  assert(Number.isInteger(metric.samples) && metric.samples > 0, 'Missing composition samples');
  assert(metric.mean <= metric.max && metric.p95 <= metric.p99 && metric.p99 <= metric.max, 'Inconsistent composition metric');
}
function assertAsset(asset) {
  assert(asset && typeof asset.name === 'string' && asset.name.length && Number.isInteger(asset.bytes) && asset.bytes > 0 && /^[0-9a-f]{64}$/.test(asset.sha256), 'Invalid asset metadata');
}
function assertNoRetiredNeutralMetadata(document) {
  assert(!('printNeutralCorrection' in document) && !('baseline' in document), 'Retired neutral rendering metadata remains');
  assert.notEqual(document.sourceRenderingMethod, 'spektrafilm-print-neutral-density-v1');
  assert.notEqual(document.referenceModel, 'spektrafilm-print-neutral-density-v1');
  for (const profile of Object.values(document.bundle?.params_snapshot || {})) {
    assert(!profile || typeof profile !== 'object' || !('neutralPrint' in profile), 'Retired neutral engine parameters remain');
  }
}

export function assertCameraStdContract(combo, adapters) {
  assert.equal(adapters.method, CAMERA_STD_METHOD);
  assert.equal(combo.stdMethod, CAMERA_STD_METHOD, `Wrong STD method: ${combo.id}`);
  assert(!('printNeutralAmount' in combo) && !('neutralBaseId' in combo) && !combo.id.endsWith('__neutral30'), 'Retired neutral variant remains');
  assertNoRetiredNeutralMetadata(combo.qa);
  if ('castBaseId' in combo) {
    assert.equal(combo.qa.referenceModel, FILM_CAST_METHOD, `Film-cast QA model differs: ${combo.id}`);
    assert.deepEqual(combo.qa.filmCast, combo.filmCast, `Film-cast recipe differs between catalog and QA: ${combo.id}`);
  } else {
    assert(!('filmCast' in combo.qa), `Base look acquired film-cast QA metadata: ${combo.id}`);
  }
  assert(!combo.stdVariant && !combo.stdVariants && !combo.files.stdB && !combo.files.stdLegacy && !combo.files.stdRefined, 'Retired STD variant remains');
  assert.deepEqual(Object.keys(combo.files).sort(), ['provenance', 'qa', 'std', 'vlog', 'zip']);
  const cameras = adapters.models.map(model => model.id).sort();
  assert.deepEqual(Object.keys(combo.stdByCamera).sort(), cameras, 'Missing or unexpected camera STD');
  assert(cameras.includes(adapters.defaultCamera), 'Unknown default camera');
  assert.equal(combo.files.std.name, `${String(combo.number).padStart(4, '0')}STD.cube`);
  assert.equal(combo.files.vlog.name, `${String(combo.number).padStart(4, '0')}VLOG.cube`);
  assert.deepEqual(combo.files.std, combo.stdByCamera[adapters.defaultCamera].std, 'Default STD alias differs');
  assert.deepEqual(combo.files.zip, combo.stdByCamera[adapters.defaultCamera].zip, 'Default ZIP alias differs');
  assert.equal(combo.qa.stdMethod, CAMERA_STD_METHOD);
  assert.equal(combo.qa.stdGeneration, CAMERA_STD_METHOD);
  assert.equal(combo.qa.camera, adapters.defaultCamera);
  assert.equal(combo.qa.sourceVlogSha256, combo.files.vlog.sha256);
  assert.equal(combo.qa.sourceAdapterSha256, adapters.models.find(model => model.id === adapters.defaultCamera).asset.sha256);
  assert.equal(combo.qa.cameraVerified, false, 'Do not label every regenerated look as camera verified');
  assert(!combo.qa.singleTonePrecurve && !combo.qa.stdVariants, 'Retired tone metadata remains');
  for (const entry of Object.values(combo.stdByCamera)) {
    assertAsset(entry.std); assertAsset(entry.zip);
    assert.equal(entry.std.name, combo.files.std.name);
    assertMetric(entry.qa.tetrahedral); assertMetric(entry.qa.trilinear);
    assert(Array.isArray(entry.warnings) && entry.warnings.every(value => typeof value === 'string'));
  }
  assert.deepEqual(combo.stdByCamera[adapters.defaultCamera].qa, combo.qa.stdVsDirectEngine, 'Default camera diagnostics differ');
  assert.equal(combo.previewMode, 'runtime-std');
  assert.deepEqual(combo.previews, {});
}

export async function verifyCameraStd(rootDir, catalog, expectedCount, expectedCameras = 10) {
  const root = path.resolve(rootDir), adapters = catalog.cameraAdapters;
  // A caller may explicitly verify a small fixture or diagnostic subset. Full
  // builds must also satisfy the complete film/paper matrix and its variants.
  const full = expectedCount === undefined;
  if (full) expectedCount = publicLookCount(catalog);
  assert.equal(catalog.combinations.length, expectedCount, 'Camera STD look count');
  if (full) assertLookInventory(catalog);
  assert.equal(adapters?.method, CAMERA_STD_METHOD);
  assert.equal(adapters.defaultCamera, 'S1II');
  assert.equal(adapters.models.length, expectedCameras, 'Camera adapter count');
  assert.equal(new Set(adapters.models.map(model => model.id)).size, expectedCameras, 'Duplicate camera adapter');
  assert.equal(adapters.commit, ALCHEMY_COMMIT, 'Camera adapter source must match the reviewed pinned commit');
  assert(adapters.sourceUrl.startsWith('https://github.com/shenmintao/V-Log-Alchemy'), 'Unexpected adapter source');
  assert(!catalog.referenceStudy && !catalog.stdVariant && !catalog.fujiStudy, 'Retired interpretation remains');
  assert(catalog.combinations.every(combo => !combo.officialSource && !['official_direct', 'official_print'].includes(combo.processMode)), 'Retired official FUJIFILM combination remains');
  assert(!privatePath.test(JSON.stringify(adapters)), 'Private path in adapter catalog');
  const source = JSON.parse(await fs.readFile(path.join(root, 'camera-adapters/source.json'), 'utf8'));
  assert.equal(source.commit, ALCHEMY_COMMIT);
  assert.equal(source.repository, 'https://github.com/shenmintao/V-Log-Alchemy');
  assert.equal(source.filesUnmodified, true);
  const manifest = JSON.parse(await fs.readFile(path.join(root, 'camera-adapters/manifest.json'), 'utf8'));
  const sourceHashes = new Map();
  for (const model of adapters.models) {
    assert(['controlled', 'field', 'pending'].includes(model.validation));
    assert(['in-camera', 'post-only'].includes(model.cameraUse));
    assertAsset(model.asset);
    const pinned = manifest.luts.find(entry => entry.path.split('/').at(-1) === model.asset.name);
    assert(pinned, `Missing source manifest entry: ${model.id}`);
    assert.equal(model.asset.sha256, pinned.sha256, `Source manifest hash differs: ${model.id}`);
    assert(!model.asset.encoding, 'Source adapters must retain original bytes');
    const bytes = await fs.readFile(localAssetPath(root, model.asset.path));
    assert.equal(bytes.length, model.asset.bytes); assert.equal(hash(bytes), model.asset.sha256, `Changed source adapter: ${model.id}`);
    sourceHashes.set(model.id, model.asset.sha256);
  }
  for (const name of ['legacy-v3', 'refined-v3', 'audit', 'research/reference-looks.json']) {
    assert(!(await fs.lstat(path.join(root, name)).catch(error => { if (error.code === 'ENOENT') return null; throw error; })), `Retired asset tree remains: ${name}`);
  }
  assert.deepEqual((await fs.readdir(path.join(root, 'luts'))).sort(), catalog.combinations.map(combo => combo.id).sort(), 'LUT inventory differs from camera catalog');
  const parsed = new Set();
  let archives = 0;
  for (const combo of catalog.combinations) {
    assertCameraStdContract(combo, adapters);
    assert(!privatePath.test(JSON.stringify(combo)), `Private path in ${combo.id}`);
    assert(!retiredAssets.test(JSON.stringify(combo)), `Retired STD reference in ${combo.id}`);
    const directory = path.join(root, 'luts', combo.id), expectedFiles = new Set(['metadata.json']);
    for (const model of adapters.models) {
      const camera = model.id, record = combo.stdByCamera[camera], zip = record.zip;
      assert.equal(path.dirname(zip.path), `/luts/${combo.id}`, 'Camera ZIP belongs to another look');
      assert.equal(path.basename(zip.path), zip.name);
      const bytes = await fs.readFile(localAssetPath(root, zip.path));
      assert.equal(bytes.length, zip.bytes); assert.equal(hash(bytes), zip.sha256);
      expectedFiles.add(zip.name); archives++;
      const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
      const entries = zipEntries(bytes);
      const names = [record.std.name, combo.files.vlog.name, 'README.txt', 'CHANGELOG.txt', 'qa.json', 'provenance.json', 'SPEKTRAFILM_LICENSE.txt', 'spektrafilm-LICENSE.txt', 'V-Log-Alchemy-LICENSE.txt', ...(combo.officialSource ? ['FUJIFILM_NOTICE.txt'] : [])].sort();
      assert.deepEqual(entries.map(entry => entry.name).sort(), names, `Unexpected/retired ZIP entry: ${combo.id}/${camera}`);
      for (const [asset, tag] of [[record.std, 'STD'], [combo.files.vlog, 'VLOG']]) {
        const raw = Buffer.from(await extractZipEntry(buffer, asset.name, asset.bytes));
        assert.equal(hash(raw), asset.sha256, `Changed ${tag} cube: ${combo.id}/${camera}`);
        if (!parsed.has(asset.sha256)) {
          const text = raw.toString('utf8');
          assert(text.split(/\r?\n/).includes(`#LUMIXPHOTOSTYLE ${tag}`), `Wrong cube Photo Style: ${combo.id}/${camera}`);
          assert.equal(parseStdCube(tag === 'STD' ? text : text.replace('#LUMIXPHOTOSTYLE VLOG', '#LUMIXPHOTOSTYLE STD')).size, 33);
          parsed.add(asset.sha256);
        }
        // The shared VLOG record refers to the default bundle, even while we
        // independently authenticate the identical VLOG in another camera ZIP.
        if (tag === 'STD' || camera === adapters.defaultCamera) {
          if (!asset.encoding) {
            assert.equal(camera, adapters.defaultCamera, 'Non-default camera has duplicate raw LUT');
            assert((await fs.readFile(localAssetPath(root, asset.path))).equals(raw), `Raw/ZIP ${tag} disagreement`);
            expectedFiles.add(asset.name);
          } else {
            assert.equal(asset.encoding, 'zip-entry'); assert.equal(asset.path, zip.path);
            assert.equal(asset.transferBytes, zip.bytes); assert.equal(asset.transferSha256, zip.sha256);
          }
        }
      }
      for (const entry of entries.filter(entry => !entry.name.endsWith('.cube'))) {
        assert(entry.bytes < 2 * 1024 * 1024);
        const raw = Buffer.from(await extractZipEntry(buffer, entry.name, entry.bytes)), text = raw.toString('utf8');
        assert(!privatePath.test(text) && !retiredAssets.test(text), `Private or retired reference: ${combo.id}/${camera}/${entry.name}`);
        if (camera === adapters.defaultCamera) {
          assert((await fs.readFile(path.join(directory, entry.name))).equals(raw), `Text/ZIP disagreement: ${combo.id}/${entry.name}`);
          expectedFiles.add(entry.name);
        }
        if (entry.name === 'qa.json') {
          const qa = JSON.parse(text);
          assertNoRetiredNeutralMetadata(qa);
          assert.equal(qa.stdMethod, CAMERA_STD_METHOD); assert.equal(qa.stdGeneration, CAMERA_STD_METHOD);
          assert.equal(qa.camera, camera); assert.equal(qa.cameraVerified, false);
          assert.equal(qa.sourceVlogSha256, combo.files.vlog.sha256);
          assert.equal(qa.sourceAdapterSha256, sourceHashes.get(camera));
          assert.deepEqual(qa.stdVsDirectEngine, record.qa, 'Camera QA/catalog disagreement');
          if (camera === adapters.defaultCamera) assert.deepEqual(qa, combo.qa, 'Default QA/catalog disagreement');
        }
        if (entry.name === 'provenance.json') {
          const provenance = JSON.parse(text), source = provenance.cameraAdapter;
          assertNoRetiredNeutralMetadata(provenance);
          if ('castBaseId' in combo) {
            assert.equal(provenance.sourceRenderingMethod, FILM_CAST_METHOD, `Film-cast provenance method: ${combo.id}`);
            assert.deepEqual(provenance.filmCast, combo.filmCast, `Film-cast provenance recipe: ${combo.id}`);
            assert.equal(provenance.castBase?.id, combo.castBaseId, `Film-cast provenance base: ${combo.id}`);
            assert.equal(provenance.castBase?.preserved, true);
            for (const paper of Object.values(provenance.bundle?.params_snapshot || {})) assert.deepEqual(paper.filmCast?.appliedCC, combo.filmCast.appliedCC, `Baked filters differ from the recipe: ${combo.id}`);
          }
          assert.equal(source.id, camera); assert.equal(source.commit, adapters.commit);
          assert.equal(source.sha256, sourceHashes.get(camera));
          assert.equal(source.validation, model.validation); assert.equal(source.cameraUse, model.cameraUse);
          assert.equal(provenance.sourceVlog.sha256, combo.files.vlog.sha256);
          assert.equal(provenance.sourceVlog.name, combo.files.vlog.name);
          assert.equal(provenance.composition.method, CAMERA_STD_METHOD);
          assert.deepEqual(provenance.composition.interpolation, { adapter: 'trilinear', creative: 'tetrahedral' });
          assert.equal(provenance.composition.outputResolution, 33);
          assert.equal(provenance.distribution.stdMethod, CAMERA_STD_METHOD);
          assert.equal(provenance.distribution.camera, camera);
          assert.equal(provenance.distribution.stdSha256, record.std.sha256);
          assert.equal(provenance.distribution.vlogSha256, combo.files.vlog.sha256);
          assert(!provenance.stdVariant && !provenance.singleTonePrecurve, 'Retired provenance remains');
        }
      }
    }
    assert.deepEqual((await fs.readdir(directory)).sort(), [...expectedFiles].sort(), `Unexpected/retired raw asset: ${combo.id}`);
    assert.deepEqual(JSON.parse(await fs.readFile(path.join(directory, 'metadata.json'), 'utf8')), combo);
  }
  return { method: CAMERA_STD_METHOD, cameras: adapters.models.length, combinations: catalog.combinations.length, stdLuts: catalog.combinations.length * adapters.models.length, luts: catalog.combinations.length * (adapters.models.length + 1), archives, sourceAdapters: sourceHashes.size };
}
