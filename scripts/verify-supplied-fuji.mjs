import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { parseStdCube } from '../src/lut.ts';
import { localAssetPath } from './verify-camera-std.mjs';

export const SUPPLIED_FUJI_METHOD = 'supplied-fuji-std-v1';
export const SUPPLIED_FUJI_COUNT = 9;
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const sha256 = /^[0-9a-f]{64}$/;
const privatePath = /(?:\/(?:Users|home|Volumes|private|tmp)\/|file:\/\/|[A-Z]:[\\/]+Users[\\/])/i;
const allowedMetadata = new Set(['#LUMIXPHOTOSTYLE STD', 'DOMAIN_MIN 0.0 0.0 0.0', 'DOMAIN_MAX 1.0 1.0 1.0']);

function assertAsset(asset) {
  assert(asset && typeof asset.name === 'string' && asset.name.length > 0, 'Missing supplied asset name');
  assert.equal(asset.path, `/supplied-fuji/${asset.name}`, 'Supplied asset must be in its dedicated directory');
  assert.equal(path.basename(asset.name), asset.name, 'Unsafe supplied asset name');
  assert(!asset.encoding && !asset.transferBytes && !asset.transferSha256, 'Supplied LUT must remain a direct file');
  assert(Number.isInteger(asset.bytes) && asset.bytes > 0 && sha256.test(asset.sha256), 'Invalid supplied asset digest');
}

export function assertSuppliedFujiContract(catalog) {
  const supplied = catalog.suppliedFuji;
  assert.equal(supplied?.methodId, SUPPLIED_FUJI_METHOD, 'Wrong supplied FUJIFILM method');
  assert.equal(supplied.cameraId, 'S1II', 'Do not claim calibration for another supplied LUT camera');
  assert.equal(supplied.looks.length, SUPPLIED_FUJI_COUNT, 'Expected nine supplied FUJIFILM looks');
  assert.equal(new Set(supplied.looks.map(look => look.stock.id)).size, SUPPLIED_FUJI_COUNT, 'Duplicate supplied look');
  assert.equal(new Set(supplied.looks.map(look => look.std.path)).size, SUPPLIED_FUJI_COUNT, 'Duplicate supplied LUT file');
  assert(!catalog.fujiStudy, 'Retired official FUJIFILM metadata remains');
  assert((catalog.films || []).every(film => !['official', 'supplied'].includes(film.type)), 'Supplied and retired official films must stay outside engine films');
  const suppliedIds = new Set(supplied.looks.map(look => look.stock.id));
  assert((catalog.combinations || []).every(combo => !suppliedIds.has(combo.film) && !combo.officialSource && !['official_direct', 'official_print'].includes(combo.processMode)), 'Supplied or retired FUJIFILM look entered the engine pipeline');
  assert(!privatePath.test(JSON.stringify(supplied)), 'Private path in supplied FUJIFILM catalog');
  for (const look of supplied.looks) {
    assert.match(look.stock.id, /^fuji_sim_[a-z0-9_]+$/);
    assert.equal(look.stock.type, 'supplied');
    assert.equal(look.stock.recommendedPrint, null, 'Supplied LUT must not select an additional paper');
    assert.equal(look.stock.sha256, look.sourceSha256, 'Source stock hash differs');
    assert(sha256.test(look.sourceSha256), 'Missing source cube hash');
    assert.equal(path.basename(look.sourceFile), look.sourceFile, 'Source filename must not expose a directory');
    assert(look.sourceFile.endsWith('.cube'), 'Missing original cube filename');
    for (const key of ['paper', 'vlog', 'zip', 'stdByCamera', 'files', 'cameraAdapter', 'stdMethod']) assert(!(key in look), `Supplied LUT has an extra transform: ${key}`);
    assertAsset(look.std);
    assert(look.std.name.endsWith('.cube'));
  }
  assertAsset(supplied.provenance); assert.equal(supplied.provenance.name, 'provenance.json');
  assertAsset(supplied.notice); assert.equal(supplied.notice.name, 'NOTICE.txt');
}

export async function verifySuppliedFuji(rootDir, catalog) {
  const root = path.resolve(rootDir);
  assertSuppliedFujiContract(catalog);
  const supplied = catalog.suppliedFuji;
  const expectedFiles = [...supplied.looks.map(look => look.std.name), supplied.provenance.name, supplied.notice.name].sort();
  assert.deepEqual((await fs.readdir(path.join(root, 'supplied-fuji'))).sort(), expectedFiles, 'Unexpected supplied FUJIFILM file inventory');
  assert(!(await fs.lstat(path.join(root, 'research/fujifilm-official.json')).catch(error => { if (error.code === 'ENOENT') return null; throw error; })), 'Retired official FUJIFILM research remains');
  async function readAsset(asset) {
    const file = localAssetPath(root, asset.path), stat = await fs.lstat(file);
    assert(stat.isFile() && !stat.isSymbolicLink(), 'Supplied asset must be a regular file');
    const bytes = await fs.readFile(file);
    assert.equal(bytes.length, asset.bytes, `Supplied asset size differs: ${asset.name}`);
    assert.equal(hash(bytes), asset.sha256, `Supplied asset hash differs: ${asset.name}`);
    return bytes;
  }
  const provenance = JSON.parse((await readAsset(supplied.provenance)).toString('utf8'));
  const notice = (await readAsset(supplied.notice)).toString('utf8');
  assert(!privatePath.test(JSON.stringify(provenance)) && !privatePath.test(notice), 'Private path in supplied FUJIFILM provenance');
  assert.equal(provenance.methodId, supplied.methodId); assert.equal(provenance.cameraId, supplied.cameraId);
  assert.equal(provenance.sourceKind, 'user-supplied-edited-luts');
  assert.equal(provenance.paper, null); assert.equal(provenance.additionalTransform, null);
  assert.equal(provenance.officialUnmodifiedProduct, false);
  assert.equal(provenance.interpolation, 'tetrahedral');
  assert.deepEqual(provenance.looks.map(look => look.id).sort(), supplied.looks.map(look => look.stock.id).sort());
  let numericRows = 0;
  for (const look of supplied.looks) {
    const record = provenance.looks.find(value => value.id === look.stock.id);
    assert.deepEqual(record.distributed, look.std); assert.equal(record.sourceFile, look.sourceFile);
    assert.equal(record.sourceSha256, look.sourceSha256); assert.equal(record.numericRowsUnchanged, true);
    assert.equal(record.resolution, 33); assert.equal(record.rows, 33 ** 3);
    assert.deepEqual(record.domainMin, [0, 0, 0]); assert.deepEqual(record.domainMax, [1, 1, 1]);
    assert(Array.isArray(record.metadataAdded) && record.metadataAdded.every(line => allowedMetadata.has(line)), 'Unexpected supplied LUT metadata alteration');
    assert.equal(new Set(record.metadataAdded).size, record.metadataAdded.length);
    const bytes = await readAsset(look.std), text = bytes.toString('utf8');
    const cube = parseStdCube(text);
    // Undo only the explicitly recorded header insertion, then authenticate
    // every original byte. This verifies more than a numeric equivalence claim.
    const headerEnd = bytes.indexOf(10) + 1;
    assert(headerEnd > 0 && text.startsWith('TITLE '), 'Missing source title');
    const additions = Buffer.from(record.metadataAdded.map(line => `${line}\n`).join(''), 'ascii');
    assert(bytes.subarray(headerEnd, headerEnd + additions.length).equals(additions), 'Recorded metadata insertion differs');
    const original = Buffer.concat([bytes.subarray(0, headerEnd), bytes.subarray(headerEnd + additions.length)]);
    assert.equal(original.length, record.sourceBytes, 'Original cube byte count changed');
    assert.equal(hash(original), look.sourceSha256, 'Original cube content changed');
    const rows = text.split(/\r?\n/).map(line => line.trim()).filter(line => line && !/^(?:#|TITLE\s|LUT_3D_SIZE\s|DOMAIN_(?:MIN|MAX)\s)/.test(line));
    assert.equal(rows.length, record.rows);
    assert.equal(hash(rows.map(line => line.split(/\s+/).join(' ') + '\n').join('')), record.numericRowsSha256, 'Supplied numeric rows changed');
    let minimum = Infinity, maximum = -Infinity;
    for (const value of cube.table) { minimum = Math.min(minimum, value); maximum = Math.max(maximum, value); }
    assert.equal(minimum, record.minimum); assert.equal(maximum, record.maximum);
    numericRows += rows.length;
  }
  return { method: supplied.methodId, camera: supplied.cameraId, luts: supplied.looks.length, originalFilesAuthenticated: supplied.looks.length, numericRows, additionalTransforms: 0 };
}
