import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { publicCatalog, EXTERNAL_SAMPLE_MANIFEST, EMPTY_EXTERNAL_SAMPLES } from './prepare-cloudflare.mjs';
import { publicLookCount } from './look-inventory.mjs';
import { verifyCameraStd } from './verify-camera-std.mjs';
import { verifyPrintTiming } from './verify-print-timing.mjs';
import { verifyGallery } from './verify-gallery.mjs';
import { verifySuppliedFuji } from './verify-supplied-fuji.mjs';

export const MAX_FILES = 20_000;
export const MAX_FILE_BYTES = 25 * 1024 * 1024;
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const privateData = /(?:\/Users\/|\/home\/|file:\/\/|[A-Z]:[\\/]+Users[\\/]|(?:^|[\/\\])sample-study(?:[\/\\]|$))/i;

export function assetRelativePath(url) {
  assert(typeof url === 'string' && url.startsWith('/') && !url.startsWith('//'), `Invalid local asset path: ${url}`);
  const pathname = decodeURIComponent(url.split(/[?#]/, 1)[0]);
  assert(!pathname.split('/').includes('..') && !pathname.includes('\\'), `Unsafe asset path: ${url}`);
  return pathname.slice(1);
}

export async function verifyCloudflare(rootDir = 'dist-cloudflare', sourceDir = 'dist') {
  const root = path.resolve(rootDir), source = path.resolve(sourceDir);
  const sourceCatalog = JSON.parse(await fs.readFile(path.join(source, 'catalog.json'), 'utf8'));
  const { catalog: expected, removedIds } = publicCatalog(sourceCatalog);
  const catalog = JSON.parse(await fs.readFile(path.join(root, 'catalog.json'), 'utf8'));
  const { sourceCode, ...publicSubset } = catalog;
  assert.deepEqual(publicSubset, expected, 'Public catalog differs from the permitted subset of the personal build');
  const publicLooks = publicLookCount(catalog);
  assert.equal(catalog.combinations.length, publicLooks);
  assert(!('referenceStudy' in catalog));
  assert(!catalog.fujiStudy, 'Retired official FUJIFILM metadata remains');
  assert.equal(catalog.combinations.filter(combo => combo.processMode === 'official_direct' || combo.processMode === 'official_print').length, 0);
  assert.equal(catalog.suppliedFuji?.looks.length, 9, 'The nine supplied FUJIFILM STD looks must remain available');
  assert(catalog.combinations.every(combo => combo.processMode !== 'reference_interpretation' && !combo.id.endsWith('__reference')));
  assert(catalog.samples.every(sample => ['camera-std', 'synthetic-srgb'].includes(sample.inputKind) && sample.source === null), 'Only user photos and the synthetic chart belong in the public build');

  const files = new Map();
  async function walk(directory) {
    for (const entry of await fs.readdir(directory, { withFileTypes: true })) {
      const filename = path.join(directory, entry.name), relative = path.relative(root, filename).split(path.sep).join('/');
      assert(!entry.isSymbolicLink(), `Symlink in public build: ${relative}`);
      assert(!relative.split('/').some(part => ['sample-study', '.cache', '.git', 'legacy-v3', 'refined-v3', 'audit'].includes(part)), `Private or retired directory in public build: ${relative}`);
      if (relative.startsWith('samples/external/')) {
        assert(relative === EXTERNAL_SAMPLE_MANIFEST && entry.isFile(), `External review sample in public build: ${relative}`);
      }
      if (entry.isDirectory()) await walk(filename);
      else {
        assert(entry.isFile(), `Non-file in public build: ${relative}`);
        const size = (await fs.stat(filename)).size;
        assert(size <= MAX_FILE_BYTES, `Cloudflare file limit exceeded: ${relative}`);
        files.set(relative, size);
      }
    }
  }
  await walk(root);
  assert(files.size <= MAX_FILES, 'Cloudflare file count limit exceeded');
  assert(files.has(EXTERNAL_SAMPLE_MANIFEST), 'Empty external sample manifest is missing');
  assert.deepEqual(JSON.parse(await fs.readFile(path.join(root, EXTERNAL_SAMPLE_MANIFEST), 'utf8')), EMPTY_EXTERNAL_SAMPLES, 'Public external sample manifest must be empty');
  assert(!files.has('research/reference-looks.json'), 'Removed reference research data is still deployed');
  assert(!files.has('research/fujifilm-official.json'), 'Retired official FUJIFILM research data remains');
  const lutDirectories = await fs.readdir(path.join(root, 'luts'));
  assert.deepEqual(lutDirectories.sort(), catalog.combinations.map(combo => combo.id).sort(), 'Public LUT directory inventory differs from the catalog');
  for (const name of files.keys()) assert(!name.startsWith('luts/') || !removedIds.has(name.split('/')[1]), `Removed reference LUT remains: ${name}`);

  let references = 0;
  for (const [relative] of files) {
    if (!/\.(json|txt|html|js|css|svg)$/.test(relative)) continue;
    const content = await fs.readFile(path.join(root, relative), 'utf8');
    assert(!privateData.test(content), `Private local path in public data: ${relative}`);
    if (!relative.endsWith('.json')) continue;
    const document = JSON.parse(content);
    function checkPaths(value) {
      if (Array.isArray(value)) value.forEach(checkPaths);
      else if (value && typeof value === 'object') {
        for (const [key, child] of Object.entries(value)) {
          // Relative paths in provenance describe engine inputs, not web assets.
          if (['path', 'thumbnailPath'].includes(key) && typeof child === 'string' && child.startsWith('/')) {
            assert(files.has(assetRelativePath(child)), `Missing JSON asset ${child} referenced by ${relative}`);
            references++;
          }
          checkPaths(child);
        }
      }
    }
    checkPaths(document);
  }
  let luts = 0, assets = 0;
  const checked = new Map();
  async function verifyAsset(asset) {
    const relative = assetRelativePath(asset.path);
    let digest = checked.get(relative);
    if (!digest) {
      const bytes = await fs.readFile(path.join(root, relative));
      digest = { bytes: bytes.length, sha256: hash(bytes) };
      checked.set(relative, digest);
    }
    assert.equal(digest.bytes, asset.encoding ? asset.transferBytes : asset.bytes, `Asset size: ${relative}`);
    assert.equal(digest.sha256, asset.encoding ? asset.transferSha256 : asset.sha256, `Asset hash: ${relative}`);
    assets++;
  }
  for (const combo of catalog.combinations) {
    assert.equal(combo.status, 'ready');
    for (const key of ['std', 'vlog']) {
      assert.equal(combo.files[key].encoding, 'zip-entry');
      assert.equal(combo.files[key].path, combo.files.zip.path);
      luts++;
    }
    for (const asset of [...Object.values(combo.files), ...Object.values(combo.previews)]) await verifyAsset(asset);
    for (const entry of Object.values(combo.stdByCamera)) {
      assert.equal(entry.std.encoding, 'zip-entry');
      assert.equal(entry.std.path, entry.zip.path);
      await verifyAsset(entry.std); await verifyAsset(entry.zip);
    }
  }
  for (const model of catalog.cameraAdapters.models) await verifyAsset(model.asset);
  for (const look of catalog.suppliedFuji.looks) await verifyAsset(look.std);
  for (const asset of [catalog.suppliedFuji.provenance, catalog.suppliedFuji.notice]) await verifyAsset(asset);
  if (sourceCode) await verifyAsset(sourceCode);
  assert.equal(luts, publicLooks * 2);
  for (const sample of catalog.samples) if (sample.preparedSha256) {
    const bytes = await fs.readFile(path.join(root, assetRelativePath(sample.path)));
    assert.equal(hash(bytes), sample.preparedSha256, `Changed sample: ${sample.id}`);
  }
  const gallery = await verifyGallery(root, catalog);
  const suppliedFuji = await verifySuppliedFuji(root, catalog);
  const cameraStd = await verifyCameraStd(root, catalog);
  const printTiming = await verifyPrintTiming(root, catalog);
  const largest = [...files].sort((a, b) => b[1] - a[1])[0];
  return { passed: true, combinations: publicLooks, luts: cameraStd.luts + suppliedFuji.luts, assets, cameraStd, printTiming, suppliedFuji, gallery, jsonAssetReferences: references, files: files.size, bytes: [...files.values()].reduce((sum, size) => sum + size, 0), largestFile: { path: largest[0], bytes: largest[1] } };
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  console.log(JSON.stringify(await verifyCloudflare(process.argv[2], process.argv[3]), null, 2));
}
