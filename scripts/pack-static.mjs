// Store each LUT in its existing camera-specific ZIP. Preserve original cube
// and archive bytes; browser downloads authenticate the ZIP and selected entry.
import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import assert from 'node:assert/strict';

const method = 'camera-vlog-alchemy-v1';
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
function localPath(root, url) {
  assert(typeof url === 'string' && url.startsWith('/') && !url.startsWith('//') && !url.includes('\\'), 'Invalid asset path');
  const file = path.resolve(root, '.' + url);
  assert(file.startsWith(root + path.sep), 'Invalid asset path');
  return file;
}
export async function packStatic(rootDir = 'dist') {
  const root = path.resolve(rootDir);
  const catalog = JSON.parse(await fs.readFile(path.join(root, 'catalog.json'), 'utf8'));
  assert.equal(catalog.cameraAdapters?.method, method, 'Generate the camera STD catalog before packing');
  const defaultCamera = catalog.cameraAdapters.defaultCamera;
  const cameras = catalog.cameraAdapters.models.map(model => model.id).sort();
  assert(cameras.includes(defaultCamera) && new Set(cameras).size === cameras.length, 'Invalid camera inventory');
  const pending = [];
  // Validate the complete inventory before deleting any duplicate raw assets.
  for (const combo of catalog.combinations) {
    if (combo.status !== 'ready') continue;
    assert.equal(combo.stdMethod, method, 'Generate the camera STD catalog before packing');
    assert(!combo.stdVariant && !combo.stdVariants, 'Retired STD variant remains');
    assert.deepEqual(Object.keys(combo.files).sort(), ['provenance', 'qa', 'std', 'vlog', 'zip']);
    assert.deepEqual(Object.keys(combo.stdByCamera).sort(), cameras, 'Incomplete camera STD inventory');
    const selected = combo.stdByCamera[defaultCamera];
    assert.deepEqual(selected.std, combo.files.std, 'Default camera STD alias differs');
    assert.deepEqual(selected.zip, combo.files.zip, 'Default camera ZIP alias differs');
    const zip = combo.files.zip;
    for (const camera of cameras) {
      const entry = combo.stdByCamera[camera];
      const bytes = await fs.readFile(localPath(root, entry.zip.path));
      assert.equal(bytes.length, entry.zip.bytes, 'ZIP asset size mismatch');
      assert.equal(hash(bytes), entry.zip.sha256, 'ZIP asset hash mismatch');
      if (camera !== defaultCamera) {
        assert.equal(entry.std.encoding, 'zip-entry', 'Non-default STD must use its camera ZIP');
        assert.equal(entry.std.path, entry.zip.path);
        assert.equal(entry.std.transferSha256, entry.zip.sha256);
        assert.equal(entry.std.transferBytes, entry.zip.bytes);
      }
    }
    const remove = [];
    for (const key of ['vlog', 'std']) {
      const asset = combo.files[key];
      assert(!asset.encoding, 'The deployment is already packed');
      const file = localPath(root, asset.path), raw = await fs.readFile(file);
      assert.equal(raw.length, asset.bytes, 'Source asset size mismatch');
      assert.equal(hash(raw), asset.sha256, 'Source asset hash mismatch');
      remove.push({ file, bytes: raw.length });
    }
    for (const asset of Object.values(combo.previews || {})) {
      const file = localPath(root, asset.path);
      assert(file.startsWith(path.join(root, 'luts', combo.id) + path.sep), 'Invalid preview path');
      const bytes = await fs.readFile(file);
      assert.equal(bytes.length, asset.bytes, 'Preview source size mismatch');
      assert.equal(hash(bytes), asset.sha256, 'Preview source hash mismatch');
      remove.push({ file, bytes: 0 });
    }
    pending.push({ combo, zip, remove });
  }
  let removedTotal = 0, count = 0;
  for (const { combo, zip, remove } of pending) {
    for (const item of remove) { await fs.unlink(item.file); removedTotal += item.bytes; }
    for (const key of ['vlog', 'std']) {
      Object.assign(combo.files[key], { path: zip.path, encoding: 'zip-entry', transferBytes: zip.bytes, transferSha256: zip.sha256 });
      count++;
    }
    // JSON does not preserve object identity: rewrite both default STD aliases.
    combo.stdByCamera[defaultCamera].std = { ...combo.files.std };
    combo.previews = {};
    combo.previewMode = 'runtime-std';
    await fs.writeFile(path.join(root, 'luts', combo.id, 'metadata.json'), JSON.stringify(combo, null, 2) + '\n');
  }
  await fs.writeFile(path.join(root, 'catalog.json'), JSON.stringify(catalog, null, 2) + '\n');
  console.log(`Lossless camera ZIP transport: ${count} raw LUT copies removed (${(removedTotal / 1048576).toFixed(1)} MiB)`);
  return { luts: count, removedBytes: removedTotal };
}
if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) await packStatic(process.argv[2]);
