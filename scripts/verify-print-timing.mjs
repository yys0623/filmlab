import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';

export const PRINT_TIMING_METHOD = 'spektrafilm-print-filter-timing-v1';
const MAGIC = 'SFPT1\n';

export function readPackHeader(bytes) {
  assert.equal(bytes.subarray(0, MAGIC.length).toString('utf8'), MAGIC, 'Not a print timing pack');
  const length = bytes.readUInt32LE(MAGIC.length), start = MAGIC.length + 4;
  const header = JSON.parse(bytes.subarray(start, start + length).toString('utf8'));
  assert.equal(bytes.length, start + length + 10 * header.resolution ** 3 * 3 * 2, 'Truncated print timing pack');
  return header;
}

// One pack per negative print base look; film-cast variants reuse their base pack.
export async function verifyPrintTiming(rootDir, catalog) {
  const info = catalog.printTiming;
  if (!info) return { packs: 0 };
  assert.equal(info.method, PRINT_TIMING_METHOD);
  assert.deepEqual(info.gridCC, [-30, 0, 30]);
  assert.deepEqual(info.rangeCC, [-30, 30]);
  assert.equal(info.resolution, 33);
  const bases = catalog.combinations.filter(combo => combo.processMode === 'negative_print' && !combo.castBaseId);
  assert.deepEqual(Object.keys(info.packs).sort(), bases.map(combo => combo.id).sort(), 'Print timing packs differ from the negative print looks');
  const root = path.resolve(rootDir);
  const expected = new Set();
  for (const base of bases) {
    const { asset, qa } = info.packs[base.id];
    assert.equal(asset.path, `/print-timing/${base.id}.bin`);
    const bytes = await fs.readFile(path.join(root, asset.path.slice(1)));
    assert.equal(bytes.length, asset.bytes); assert.equal(createHash('sha256').update(bytes).digest('hex'), asset.sha256, `Changed print timing pack: ${base.id}`);
    const header = readPackHeader(bytes);
    assert.equal(header.method, PRINT_TIMING_METHOD); assert.equal(header.id, base.id);
    assert.equal(header.film, base.film); assert.equal(header.paper, base.paper);
    assert.equal(header.baseVlogSha256, base.files.vlog.sha256, `Print timing pack was baked for another VLOG: ${base.id}`);
    for (const metric of Object.values(qa)) assert(metric.p99 <= 0.03 && metric.mean <= 0.006, `Print timing QA too large: ${base.id}`);
    expected.add(path.basename(asset.path));
  }
  assert.deepEqual((await fs.readdir(path.join(root, 'print-timing'))).sort(), [...expected].sort(), 'Unexpected print timing files');
  return { packs: expected.size };
}
