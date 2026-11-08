import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { packStatic } from '../scripts/pack-static.mjs';

const method = 'camera-vlog-alchemy-v1';
const cameraAdapters = { method, defaultCamera: 'S1II', models: [{ id: 'S1II' }, { id: 'S5II' }] };
async function fixture(root) {
  const id = 'film__paper', directory = path.join(root, 'luts', id);
  await fs.mkdir(directory, { recursive: true });
  async function asset(name) {
    const bytes = Buffer.from(`Distinct test ${name} bytes`);
    await fs.writeFile(path.join(directory, name), bytes);
    return { path: `/luts/${id}/${name}`, name, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex') };
  }
  const files = {};
  for (const [key, name] of [['std', '0001STD.cube'], ['vlog', '0001VLOG.cube'], ['zip', '0001LUTS.zip'], ['qa', 'qa.json'], ['provenance', 'provenance.json']]) files[key] = await asset(name);
  const otherZip = await asset('0001S5II.zip');
  const otherStd = { ...files.std, path: otherZip.path, sha256: 'a'.repeat(64), encoding: 'zip-entry', transferBytes: otherZip.bytes, transferSha256: otherZip.sha256 };
  const preview = await asset('sample.webp');
  const combo = { id, stdMethod: method, processMode: 'negative_print', status: 'ready', files, previews: { sample: preview }, stdByCamera: { S1II: { std: { ...files.std }, zip: { ...files.zip } }, S5II: { std: otherStd, zip: otherZip } } };
  await fs.mkdir(path.join(root, 'supplied-fuji'));
  const suppliedBytes = Buffer.from('Supplied STD must remain unchanged');
  await fs.writeFile(path.join(root, 'supplied-fuji/supplied.cube'), suppliedBytes);
  const suppliedFuji = { methodId: 'supplied-fuji-std-v1', cameraId: 'S1II', looks: [{ stock: { id: 'fuji_sim_test', type: 'supplied' }, std: { path: '/supplied-fuji/supplied.cube', name: 'supplied.cube', bytes: suppliedBytes.length, sha256: createHash('sha256').update(suppliedBytes).digest('hex') } }] };
  const catalog = { cameraAdapters, combinations: [combo], suppliedFuji };
  await fs.writeFile(path.join(root, 'catalog.json'), JSON.stringify(catalog));
  return { catalog, combo, directory, preview };
}

test('packing rewrites both default camera aliases and preserves other camera archives and direct supplied LUTs', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'film-lab-pack-'));
  try {
    const { catalog, combo, directory, preview } = await fixture(root);
    const packed = await packStatic(root);
    assert.equal(packed.luts, 2);
    const packedCatalog = JSON.parse(await fs.readFile(path.join(root, 'catalog.json'), 'utf8'));
    const updated = packedCatalog.combinations[0];
    assert.deepEqual(packedCatalog.suppliedFuji, catalog.suppliedFuji);
    const supplied = catalog.suppliedFuji.looks[0].std;
    assert.equal(createHash('sha256').update(await fs.readFile(path.join(root, supplied.path))).digest('hex'), supplied.sha256);
    for (const key of ['std', 'vlog']) {
      assert.equal(updated.files[key].encoding, 'zip-entry');
      assert.equal(updated.files[key].path, combo.files.zip.path);
      assert.equal(updated.files[key].name, combo.files[key].name);
      assert.equal(updated.files[key].sha256, combo.files[key].sha256);
      assert.equal(updated.files[key].transferSha256, combo.files.zip.sha256);
      assert.equal(updated.files[key].transferBytes, combo.files.zip.bytes);
      await assert.rejects(fs.access(path.join(directory, combo.files[key].name)));
    }
    assert.deepEqual(updated.stdByCamera.S1II.std, updated.files.std);
    assert.deepEqual(updated.stdByCamera.S5II, combo.stdByCamera.S5II);
    assert.deepEqual(updated.previews, {});
    assert.equal(updated.previewMode, 'runtime-std');
    await assert.rejects(fs.access(path.join(directory, preview.name)));
    assert.deepEqual(JSON.parse(await fs.readFile(path.join(directory, 'metadata.json'), 'utf8')), updated);
    for (const entry of Object.values(combo.stdByCamera)) assert.equal(createHash('sha256').update(await fs.readFile(path.join(directory, entry.zip.name))).digest('hex'), entry.zip.sha256);
    await assert.rejects(packStatic(root), /already packed/);
  } finally { await fs.rm(root, { recursive: true, force: true }); }
});

test('packing rejects missing models, mismatched aliases, retired methods and corrupt archives before deleting raw cubes', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'film-lab-pack-guard-'));
  try {
    const { catalog, directory } = await fixture(root);
    for (const mutate of [
      value => { delete value.cameraAdapters; },
      value => { value.combinations[0].stdVariant = 'B'; },
      value => { delete value.combinations[0].stdByCamera.S5II; },
      value => { value.combinations[0].stdByCamera.S1II.std.sha256 = '0'.repeat(64); },
      value => { value.combinations[0].stdByCamera.S5II.std.transferSha256 = '0'.repeat(64); },
      value => { value.combinations[0].files.stdB = {}; },
      value => { value.combinations[0].stdByCamera.S5II.zip.sha256 = '0'.repeat(64); },
    ]) {
      const changed = structuredClone(catalog); mutate(changed);
      await fs.writeFile(path.join(root, 'catalog.json'), JSON.stringify(changed));
      await assert.rejects(packStatic(root));
      await fs.access(path.join(directory, '0001STD.cube'));
      await fs.access(path.join(directory, '0001VLOG.cube'));
    }
  } finally { await fs.rm(root, { recursive: true, force: true }); }
});
