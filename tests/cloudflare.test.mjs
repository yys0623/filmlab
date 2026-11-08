import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { publicCatalog, prepareCloudflare, EXTERNAL_SAMPLE_MANIFEST, EMPTY_EXTERNAL_SAMPLES } from '../scripts/prepare-cloudflare.mjs';
import { assetRelativePath, verifyCloudflare } from '../scripts/verify-cloudflare.mjs';
import { assertCameraStdContract, verifyCameraStd } from '../scripts/verify-camera-std.mjs';
import { assertLookInventory, BASE_LOOKS, PUBLIC_LOOKS, FILM_CAST_METHOD, FILM_CAST_SUFFIX } from '../scripts/look-inventory.mjs';

const fixture = () => {
  const negatives = Array.from({ length: 16 }, (_, index) => ({ id: `negative_${index}`, type: 'negative' }));
  const positives = Array.from({ length: 4 }, (_, index) => ({ id: `positive_${index}`, type: 'positive' }));
  const papers = Array.from({ length: 8 }, (_, index) => ({ id: `paper_${index}` }));
  const prints = negatives.flatMap((film, filmIndex) => papers.map((paper, paperIndex) => ({
    id: `${film.id}__${paper.id}`, film: film.id, paper: paper.id, number: filmIndex * 8 + paperIndex + 1, processMode: 'negative_print', status: 'ready',
  })));
  const base = [
    ...prints,
    ...positives.map((film, index) => ({ id: `${film.id}__direct_scan`, film: film.id, paper: null, number: 129 + index, processMode: 'positive_direct', status: 'ready' })),
    ...negatives.map((film, index) => ({ id: `${film.id}__digital_scan`, film: film.id, paper: null, number: 133 + index, processMode: 'negative_digital', status: 'ready' })),
  ];
  return {
    schemaVersion: 2,
    films: [...negatives, ...positives], papers,
    combinations: [
      ...base,
      ...Array.from({ length: 4 }, (_, index) => ({ id: `film_${index}__reference`, film: 'negative_0', processMode: 'reference_interpretation', status: 'ready' })),
    ],
    counts: { ready: PUBLIC_LOOKS + 4, failed: 0, unsupported: 0, 'not-generated': 0 },
    samples: [],
    suppliedFuji: { methodId: 'supplied-fuji-std-v1', cameraId: 'S1II', looks: Array.from({ length: 9 }, (_, index) => ({ stock: { id: `supplied_${index}`, type: 'supplied' } })) },
    referenceStudy: { looks: Array.from({ length: 4 }, (_, index) => ({ film: `film_${index}` })) },
  };
};

test('public catalog removes reference interpretations and preserves the supplied FUJIFILM looks and source catalog', () => {
  const source = fixture(), before = structuredClone(source);
  const { catalog, removedIds } = publicCatalog(source);
  assert.deepEqual(source, before);
  assert.equal(catalog.combinations.length, PUBLIC_LOOKS);
  assert.equal(removedIds.size, 4);
  assert.deepEqual(catalog.films, source.films);
  assert.deepEqual(catalog.suppliedFuji, source.suppliedFuji);
  assert(!catalog.fujiStudy);
  assert(!('referenceStudy' in catalog));
  assert.deepEqual(catalog.combinations, before.combinations.slice(0, PUBLIC_LOOKS));
  assert.equal(catalog.counts.ready, PUBLIC_LOOKS);
});

test('a reference interpretation is removed even when its process metadata is mislabeled', () => {
  const source = fixture();
  source.combinations[PUBLIC_LOOKS].processMode = 'negative_print';
  assert.equal(publicCatalog(source).removedIds.size, 4);
  delete source.referenceStudy;
  assert.equal(publicCatalog(source).removedIds.size, 4);
});

test('unexpected catalog scope or unsafe LUT directory aborts the public build', () => {
  const source = fixture();
  source.combinations.splice(PUBLIC_LOOKS, 1);
  assert.throws(() => publicCatalog(source), /4 removed reference/);
  const unsafe = fixture();
  unsafe.combinations[0].id = '../outside';
  assert.throws(() => publicCatalog(unsafe), /Unsafe LUT directory/);
  for (const mutate of [
    value => { value.fujiStudy = {}; },
    value => { value.films.push({ id: 'gfx_test', type: 'official' }); },
    value => { value.combinations[0].processMode = 'official_print'; },
    value => { delete value.suppliedFuji; },
    value => { value.suppliedFuji.looks.pop(); },
  ]) {
    const changed = fixture(); mutate(changed);
    assert.throws(() => publicCatalog(changed), /FUJIFILM/);
  }
});

test('asset lookup permits cache query strings but rejects traversal and external paths', () => {
  assert.equal(assetRelativePath('/samples/photo.webp?v=123'), 'samples/photo.webp');
  for (const url of ['/../private', '/%2e%2e/private', '//host/file', 'https://host/file', '/a\\private']) assert.throws(() => assetRelativePath(url));
});

test('public preparation removes reference and external sample files, preserving supplied FUJIFILM and the personal build', async () => {
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'film-lab-public-'));
  const source = path.join(temporary, 'dist'), output = path.join(temporary, 'dist-cloudflare');
  const catalog = fixture();
  try {
    await fs.mkdir(path.join(source, 'research'), { recursive: true });
    await fs.writeFile(path.join(source, 'research/fujifilm-official.json'), '{"requested":true}');
    await fs.writeFile(path.join(source, 'research/reference-looks.json'), '{"removed":true}');
    await fs.writeFile(path.join(source, 'catalog.json'), JSON.stringify(catalog));
    await fs.mkdir(path.join(source, 'gallery/images'), { recursive: true });
    await fs.writeFile(path.join(source, 'gallery/manifest.json'), '{"source":"user-provided"}');
    await fs.writeFile(path.join(source, 'gallery/images/photo.webp'), 'authorized gallery derivative');
    const privateManifest = { schemaVersion: 1, localOnly: true, samples: [{ id: 'review-photo', path: '/samples/external/photo.jpg', source: 'https://example.com/review' }], models: ['camera'], scenes: ['outdoors'], missing: [] };
    await fs.mkdir(path.join(source, 'samples/external/nested'), { recursive: true });
    await fs.writeFile(path.join(source, EXTERNAL_SAMPLE_MANIFEST), JSON.stringify(privateManifest));
    await fs.writeFile(path.join(source, 'samples/external/photo.jpg'), 'private photo fixture');
    await fs.writeFile(path.join(source, 'samples/external/nested/notes.json'), '{"private":true}');
    for (const combo of catalog.combinations) {
      await fs.mkdir(path.join(source, 'luts', combo.id), { recursive: true });
      await fs.writeFile(path.join(source, 'luts', combo.id, 'payload.txt'), combo.id);
    }
    await assert.rejects(prepareCloudflare(source, source), /Output must be named/);
    await prepareCloudflare(source, output);
    assert.equal((await fs.readdir(path.join(source, 'luts'))).length, PUBLIC_LOOKS + 4);
    assert.equal((await fs.readdir(path.join(output, 'luts'))).length, PUBLIC_LOOKS);
    await assert.rejects(fs.access(path.join(output, 'research/reference-looks.json')));
    await assert.rejects(fs.access(path.join(output, 'research/fujifilm-official.json')));
    assert.equal(await fs.readFile(path.join(source, 'research/fujifilm-official.json'), 'utf8'), '{"requested":true}');
    assert.equal(await fs.readFile(path.join(output, 'luts/negative_0__paper_0/payload.txt'), 'utf8'), 'negative_0__paper_0');
    assert.equal(await fs.readFile(path.join(output, 'gallery/images/photo.webp'), 'utf8'), 'authorized gallery derivative');
    assert.equal(await fs.readFile(path.join(output, 'gallery/manifest.json'), 'utf8'), '{"source":"user-provided"}');
    assert.deepEqual(JSON.parse(await fs.readFile(path.join(source, 'catalog.json'), 'utf8')), catalog);
    assert.deepEqual(await fs.readdir(path.join(output, 'samples/external')), ['manifest.json']);
    assert.deepEqual(JSON.parse(await fs.readFile(path.join(output, EXTERNAL_SAMPLE_MANIFEST), 'utf8')), EMPTY_EXTERNAL_SAMPLES);
    assert.deepEqual(JSON.parse(await fs.readFile(path.join(source, EXTERNAL_SAMPLE_MANIFEST), 'utf8')), privateManifest);
    assert.equal(await fs.readFile(path.join(source, 'samples/external/photo.jpg'), 'utf8'), 'private photo fixture');
    assert.equal(await fs.readFile(path.join(source, 'samples/external/nested/notes.json'), 'utf8'), '{"private":true}');
    // Detect accidental copies after preparation, including extra empty folders
    // and a populated/relabelled manifest without any image files.
    await fs.writeFile(path.join(output, 'samples/external/photo.jpg'), 'accidental photo');
    await assert.rejects(verifyCloudflare(output, source), /External review sample/);
    await fs.rm(path.join(output, 'samples/external/photo.jpg'));
    await fs.mkdir(path.join(output, 'samples/external/nested'));
    await assert.rejects(verifyCloudflare(output, source), /External review sample/);
    await fs.rmdir(path.join(output, 'samples/external/nested'));
    for (const invalid of [privateManifest, { ...EMPTY_EXTERNAL_SAMPLES, localOnly: false }, { ...EMPTY_EXTERNAL_SAMPLES, originalUrl: 'https://example.com/private.jpg' }]) {
      await fs.writeFile(path.join(output, EXTERNAL_SAMPLE_MANIFEST), JSON.stringify(invalid));
      await assert.rejects(verifyCloudflare(output, source), /external sample manifest must be empty/);
    }
    await fs.rm(path.join(output, EXTERNAL_SAMPLE_MANIFEST));
    await assert.rejects(verifyCloudflare(output, source), /external sample manifest is missing/);
    await fs.writeFile(path.join(output, EXTERNAL_SAMPLE_MANIFEST), JSON.stringify(EMPTY_EXTERNAL_SAMPLES));
    // A removed reference directory copied back after filtering must fail verification.
    await fs.mkdir(path.join(output, 'luts', 'film_0__reference'));
    await assert.rejects(verifyCloudflare(output, source), /directory inventory/);
    await fs.rmdir(path.join(output, 'luts', 'film_0__reference'));
    await fs.writeFile(path.join(output, 'research/reference-looks.json'), '{}');
    await assert.rejects(verifyCloudflare(output, source), /Removed reference research/);
    await fs.rm(path.join(output, 'research/reference-looks.json'));
    await fs.writeFile(path.join(output, 'research/fujifilm-official.json'), '{}');
    await assert.rejects(verifyCloudflare(output, source), /Retired official FUJIFILM/);
    await fs.rm(path.join(output, 'research/fujifilm-official.json'));
    await fs.writeFile(path.join(output, 'accidental-export.json'), JSON.stringify({ originalPath: '/Users/private/photo.jpg' }));
    await assert.rejects(verifyCloudflare(output, source), /Private local path/);
    await fs.writeFile(path.join(output, 'accidental-export.json'), JSON.stringify({ path: '/missing-image.webp' }));
    await assert.rejects(verifyCloudflare(output, source), /Missing JSON asset/);
  } finally { await fs.rm(temporary, { recursive: true, force: true }); }
});


test('a finalized catalog is accepted without reintroducing removed research', () => {
  const { catalog } = publicCatalog(fixture());
  assert.deepEqual(publicCatalog(catalog).catalog, catalog);
  assert.equal(publicCatalog(catalog).removedIds.size, 0);
});

test('look inventory preserves all base modes and rejects unsupported variants', () => {
  const { catalog } = publicCatalog(fixture());
  assert.deepEqual(assertLookInventory(catalog), { baseLooks: BASE_LOOKS, filmCastLooks: 0, combinations: PUBLIC_LOOKS });
  for (const [description, mutate] of [
    ['retired correction amount', value => { value.combinations[0].printNeutralAmount = 0.3; }],
    ['unsupported correction amount', value => { value.combinations[0].printNeutralAmount = 0.7; }],
    ['retired variant metadata', value => { value.combinations[0].neutralBaseId = value.combinations[0].id; }],
    ['retired variant ID', value => { value.combinations[0].id += '__neutral30'; }],
    ['wrong base number', value => { value.combinations[0].number += 1000; }],
    ['wrong film pairing', value => { value.combinations[0].film = 'negative_1'; }],
    ['wrong paper pairing', value => { value.combinations[0].paper = 'paper_1'; }],
    ['no print stage', value => { value.combinations[0].processMode = 'negative_digital'; value.combinations[0].paper = null; }],
    ['positive film print', value => { value.combinations[0].film = 'positive_0'; }],
    ['missing base look', value => { value.combinations.splice(0, 1); }],
    ['duplicate base pair', value => { value.combinations[1] = { ...value.combinations[0] }; }],
    ['duplicate base number', value => { value.combinations[1].number = value.combinations[0].number; }],
    ['extra paper', value => { value.papers.push({ id: 'paper_extra' }); }],
    ['wrong positive scan', value => { value.combinations.find(combo => combo.processMode === 'positive_direct').processMode = 'negative_digital'; }],
  ]) {
    const invalid = structuredClone(catalog); mutate(invalid);
    assert.throws(() => assertLookInventory(invalid), undefined, description);
  }
});

const withFilmCast = catalog => {
  const value = structuredClone(catalog);
  const prints = value.combinations.filter(combo => combo.processMode === 'negative_print');
  value.combinations.push(...prints.map(combo => ({ ...combo, id: `${combo.id}${FILM_CAST_SUFFIX}`, number: combo.number + 1000, castBaseId: combo.id,
    filmCast: { method: FILM_CAST_METHOD, amountPolicy: 'chroma-target', amount: 0.637, percent: 64, targetChroma: 6 } })));
  value.filmCast = { method: FILM_CAST_METHOD, amountPolicy: 'chroma-target', minAmount: 0.2, targetChroma: { default: 6, kodak_vision3_500t: 10 }, variants: prints.length };
  return value;
};

const withEditorialHue = catalog => {
  const value = withFilmCast(catalog);
  const film = value.combinations.at(-1).film;
  value.filmCast.targetHue = { [film]: 180 };
  for (const combo of value.combinations.filter(c => c.castBaseId && c.film === film))
    combo.filmCast = { ...combo.filmCast, amount: 1, percent: 100, directionPolicy: 'editorial-hue', targetHue: 180,
      filmCC: [0, 80, 100], hueShiftCC: [0, 5.1, 3], appliedCC: [0, 85.1, 103] };
  return value;
};

test('look inventory accepts an editorial-hue film and rejects inconsistent hue recipes', () => {
  const { catalog } = publicCatalog(fixture());
  const valid = withEditorialHue(catalog);
  assert.deepEqual(assertLookInventory(valid), { baseLooks: BASE_LOOKS, filmCastLooks: 128, combinations: PUBLIC_LOOKS + 128 });
  const variant = value => value.combinations.at(-1);
  const other = value => value.combinations.find(c => c.castBaseId && c.film !== variant(value).film);
  for (const [description, mutate] of [
    ['blended amount', value => { variant(value).filmCast.amount = 0.8; variant(value).filmCast.percent = 80; }],
    ['missing policy', value => { delete variant(value).filmCast.directionPolicy; }],
    ['hue differs from catalog', value => { variant(value).filmCast.targetHue = 200; }],
    ['zero shift', value => { variant(value).filmCast.hueShiftCC = [0, 0, 0]; variant(value).filmCast.appliedCC = [0, 80, 100]; }],
    ['shift beyond slider range', value => { variant(value).filmCast.hueShiftCC = [0, 40, 3]; variant(value).filmCast.appliedCC = [0, 120, 103]; }],
    ['applied filters differ', value => { variant(value).filmCast.appliedCC = [0, 85.1, 104]; }],
    ['undeclared film gets a hue', value => { Object.assign(other(value).filmCast, { directionPolicy: 'editorial-hue', targetHue: 180 }); }],
    ['invalid catalog hue', value => { value.filmCast.targetHue[variant(value).film] = 400; }],
  ]) {
    const invalid = structuredClone(valid); mutate(invalid);
    assert.throws(() => assertLookInventory(invalid), undefined, description);
  }
});

test('look inventory accepts declared film-cast variants and rejects malformed ones', () => {
  const { catalog } = publicCatalog(fixture());
  const valid = withFilmCast(catalog);
  assert.deepEqual(assertLookInventory(valid), { baseLooks: BASE_LOOKS, filmCastLooks: 128, combinations: PUBLIC_LOOKS + 128 });
  const variant = value => value.combinations.at(-1);
  for (const [description, mutate] of [
    ['undeclared variant', value => { value.filmCast.variants = 2; }],
    ['missing selectable pair', value => { value.combinations.pop(); value.filmCast.variants--; }],
    ['excluded pair', value => { value.filmCast.skipped = [{ id: value.combinations[0].id, reason: 'Editorial exclusion' }]; }],
    ['missing catalog method', value => { value.filmCast.method = 'spektrafilm-print-neutral-density-v1'; }],
    ['wrong number', value => { variant(value).number += 1; }],
    ['unknown base', value => { variant(value).castBaseId = 'negative_0__missing'; }],
    ['wrong ID', value => { variant(value).id = `${variant(value).castBaseId}__neutral30`; }],
    ['wrong paper', value => { variant(value).paper = value.papers.find(paper => paper.id !== variant(value).paper).id; }],
    ['paperless base', value => { const base = value.combinations.find(combo => combo.processMode === 'negative_digital'); Object.assign(variant(value), { castBaseId: base.id, id: `${base.id}${FILM_CAST_SUFFIX}`, number: base.number + 1000, paper: null, film: base.film }); }],
    ['duplicate pairing', value => { value.combinations.push({ ...variant(value), number: variant(value).number + 500 }); value.filmCast.variants++; }],
    ['retired scaling method', value => { variant(value).filmCast.method = 'spektrafilm-print-neutral-density-v1'; }],
    ['amount equal to base', value => { variant(value).filmCast.amount = 1; }],
    ['amount below the minimum', value => { variant(value).filmCast.amount = 0.1; variant(value).filmCast.percent = 10; }],
    ['fixed shared policy', value => { variant(value).filmCast.amountPolicy = 'fixed'; }],
    ['missing policy', value => { delete variant(value).filmCast.amountPolicy; }],
    ['percentage label differs from amount', value => { variant(value).filmCast.percent = 30; }],
    ['missing chroma target', value => { delete variant(value).filmCast.targetChroma; }],
    ['old catalog recipe', value => { value.filmCast.amountPolicy = 'fixed'; }],
    ['catalog shared amount', value => { value.filmCast.amount = 0.3; }],
    ['catalog shared label', value => { value.filmCast.percent = 30; }],
    ['catalog without chroma target', value => { delete value.filmCast.targetChroma; }],
    ['retired neutral field', value => { variant(value).printNeutralAmount = 0.3; }],
  ]) {
    const invalid = structuredClone(valid); mutate(invalid);
    assert.throws(() => assertLookInventory(invalid), undefined, description);
  }
});

test('camera STD contract rejects missing models, stale B metadata, wrong sources and mismatched aliases', async () => {
  const catalog = JSON.parse(await fs.readFile(new URL('../public/catalog.json', import.meta.url), 'utf8'));
  const combo = catalog.combinations[0];
  assertCameraStdContract(combo, catalog.cameraAdapters);
  for (const mutate of [
    value => { value.stdVariant = 'B'; },
    value => { value.printNeutralAmount = 0.6; },
    value => { value.printNeutralAmount = 0.3; },
    value => { value.id += '__neutral30'; },
    value => { value.neutralBaseId = value.id; },
    value => { value.qa.printNeutralCorrection = { amount: 0.3 }; },
    value => { value.qa.referenceModel = 'spektrafilm-print-neutral-density-v1'; },
    value => { value.stdMethod = 'unknown'; },
    value => { value.files.std.name = '0001STB.cube'; },
    value => { value.files.stdB = value.files.std; },
    value => { value.stdVariants = { B: {} }; },
    value => { value.qa.sourceVlogSha256 = '0'.repeat(64); },
    value => { value.qa.sourceAdapterSha256 = '0'.repeat(64); },
    value => { value.qa.stdVsDirectEngine = {}; },
    value => { value.qa.singleTonePrecurve = { variant: 'B' }; },
    value => { delete value.stdByCamera.S5II; },
    value => { value.stdByCamera.S1II.std = { ...value.files.std, sha256: '0'.repeat(64) }; },
    value => { value.stdByCamera.S5II.qa.tetrahedral.mean = NaN; },
    value => { value.previews = { staleB: {} }; },
  ]) {
    const changed = structuredClone(combo); mutate(changed);
    assert.throws(() => assertCameraStdContract(changed, catalog.cameraAdapters));
  }
});

test('camera verifier authenticates every model ZIP and rejects stale raw cubes, sidecar trees and source corruption', async () => {
  const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'film-lab-camera-std-'));
  const catalog = JSON.parse(await fs.readFile(new URL('../public/catalog.json', import.meta.url), 'utf8'));
  const combo = catalog.combinations.find(value => value.id === 'fujifilm_c200__fujifilm_crystal_archive_typeii');
  const source = new URL(`../public/luts/${combo.id}/`, import.meta.url);
  const destination = path.join(temporary, 'luts', combo.id);
  try {
    await fs.mkdir(path.dirname(destination), { recursive: true });
    await fs.cp(source, destination, { recursive: true });
    await fs.cp(new URL('../public/camera-adapters/', import.meta.url), path.join(temporary, 'camera-adapters'), { recursive: true });
    const single = { combinations: [combo], cameraAdapters: catalog.cameraAdapters };
    const result = await verifyCameraStd(temporary, single, 1);
    assert.equal(result.stdLuts, 10); assert.equal(result.luts, 11); assert.equal(result.archives, 10);
    const wrongCamera = structuredClone(single);
    wrongCamera.combinations[0].stdByCamera.S5II.zip = { ...combo.files.zip };
    await assert.rejects(verifyCameraStd(temporary, wrongCamera, 1), /Changed STD cube/);
    await fs.writeFile(path.join(destination, '0001STB.cube'), 'retired cube');
    await assert.rejects(verifyCameraStd(temporary, single, 1), /Unexpected\/retired raw asset/);
    await fs.rm(path.join(destination, '0001STB.cube'));
    await fs.mkdir(path.join(temporary, 'refined-v3'));
    await assert.rejects(verifyCameraStd(temporary, single, 1), /Retired asset tree/);
    await fs.rmdir(path.join(temporary, 'refined-v3'));
    const model = catalog.cameraAdapters.models.find(value => value.id === 'S5II');
    await fs.appendFile(path.join(temporary, model.asset.path), '\ncorruption');
    await assert.rejects(verifyCameraStd(temporary, single, 1));
  } finally { await fs.rm(temporary, { recursive: true, force: true }); }
});
