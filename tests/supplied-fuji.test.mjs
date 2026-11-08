import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { assertSuppliedFujiContract, verifySuppliedFuji } from '../scripts/verify-supplied-fuji.mjs';

const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const catalogPath = new URL('../public/catalog.json', import.meta.url);

test('supplied FUJIFILM remains a separate nine-look STD-only catalog', async () => {
  const catalog = JSON.parse(await fs.readFile(catalogPath, 'utf8'));
  assertSuppliedFujiContract(catalog);
  for (const mutate of [
    value => { value.suppliedFuji.looks.pop(); },
    value => { value.suppliedFuji.cameraId = 'S5II'; },
    value => { value.suppliedFuji.looks[0].stock.recommendedPrint = 'paper'; },
    value => { value.suppliedFuji.looks[0].vlog = {}; },
    value => { value.suppliedFuji.looks[0].stdByCamera = {}; },
    value => { value.suppliedFuji.looks[0].std.encoding = 'zip-entry'; },
    value => { value.suppliedFuji.looks[0].sourceFile = '/Users/private/file.cube'; },
    value => { value.combinations[0].film = value.suppliedFuji.looks[0].stock.id; },
    value => { value.fujiStudy = {}; },
  ]) {
    const changed = structuredClone(catalog); mutate(changed);
    assert.throws(() => assertSuppliedFujiContract(changed));
  }
});

test('supplied LUT verification authenticates original bytes and rejects color edits even after output hashes are refreshed', async () => {
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'sosang-supplied-fuji-'));
  const catalog = JSON.parse(await fs.readFile(catalogPath, 'utf8'));
  try {
    await fs.cp(new URL('../public/supplied-fuji/', import.meta.url), path.join(temporary, 'supplied-fuji'), { recursive: true });
    const result = await verifySuppliedFuji(temporary, catalog);
    assert.equal(result.luts, 9); assert.equal(result.originalFilesAuthenticated, 9);
    assert.equal(result.numericRows, 9 * 33 ** 3); assert.equal(result.additionalTransforms, 0);
    await fs.writeFile(path.join(temporary, 'supplied-fuji/extra.cube'), 'stale copy');
    await assert.rejects(verifySuppliedFuji(temporary, catalog), /file inventory/);
    await fs.rm(path.join(temporary, 'supplied-fuji/extra.cube'));
    const look = catalog.suppliedFuji.looks[0], cubePath = path.join(temporary, look.std.path);
    const original = await fs.readFile(cubePath, 'utf8');
    const changed = original.replace(/^([0-9]+\.[0-9]+)(\s+[0-9])/m, (_, number, rest) => `${Number(number) < 0.5 ? '0.75' : '0.25'}${rest}`);
    assert.notEqual(changed, original);
    await fs.writeFile(cubePath, changed);
    look.std.bytes = Buffer.byteLength(changed); look.std.sha256 = hash(changed);
    const provenancePath = path.join(temporary, catalog.suppliedFuji.provenance.path);
    const provenance = JSON.parse(await fs.readFile(provenancePath, 'utf8'));
    provenance.looks.find(record => record.id === look.stock.id).distributed = { ...look.std };
    const updatedProvenance = JSON.stringify(provenance);
    await fs.writeFile(provenancePath, updatedProvenance);
    catalog.suppliedFuji.provenance.bytes = Buffer.byteLength(updatedProvenance);
    catalog.suppliedFuji.provenance.sha256 = hash(updatedProvenance);
    await assert.rejects(verifySuppliedFuji(temporary, catalog), /Original cube (byte count|content) changed/);
  } finally { await fs.rm(temporary, { recursive: true, force: true }); }
});
