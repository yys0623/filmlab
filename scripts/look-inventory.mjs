import assert from 'node:assert/strict';

export const BASE_LOOKS = 148;
// Base public looks. Experimental film-cast variants are counted on top of
// these and declared by catalog.filmCast.variants.
export const PUBLIC_LOOKS = BASE_LOOKS;
export const FILM_CAST_METHOD = 'spektrafilm-print-reference-blend-v1';
export const FILM_CAST_SUFFIX = '__filmcast';
export const FILM_CAST_NUMBER_OFFSET = 1000;
// Amounts are solved per film/paper so 18% gray reaches a chroma target.
export const FILM_CAST_POLICY = 'chroma-target';
export const FILM_CAST_MIN_AMOUNT = 0.2;
// Films whose database direction contradicts their known look get an editorial hue.
export const FILM_CAST_HUE_POLICY = 'editorial-hue';

export function filmCastCount(catalog) {
  return catalog.filmCast?.variants ?? 0;
}

export function publicLookCount(catalog) {
  return BASE_LOOKS + filmCastCount(catalog);
}

// Keep the complete supported film/paper inventory. A film-cast variant is a
// separate creative LUT paired with exactly one negative print base look.
export function assertLookInventory(catalog) {
  const { combinations, films, papers } = catalog;
  const declared = filmCastCount(catalog), expected = BASE_LOOKS + declared;
  assert(Number.isInteger(declared) && declared >= 0 && declared <= 128, 'Invalid declared film-cast count');
  if (declared) {
    assert.equal(declared, 128, 'Every negative film/paper pair must offer the film-cast variant');
    assert.equal(catalog.filmCast.method, FILM_CAST_METHOD, 'Unknown film-cast method');
    assert.equal(catalog.filmCast.amountPolicy, FILM_CAST_POLICY, 'Film-cast recipe must solve its amount per pair');
    assert.equal(catalog.filmCast.minAmount, FILM_CAST_MIN_AMOUNT, 'Film-cast minimum amount differs');
    assert(Number.isFinite(catalog.filmCast.targetChroma?.default) && catalog.filmCast.targetChroma.default > 0, 'Missing film-cast chroma target');
    const hues = catalog.filmCast.targetHue ?? {};
    assert(Object.values(hues).every(h => Number.isFinite(h) && h >= 0 && h < 360), 'Invalid film-cast hue target');
    assert(!('amount' in catalog.filmCast) && !('percent' in catalog.filmCast), 'Catalog must not declare one shared percentage');
    assert.equal(catalog.filmCast.skipped?.length ?? 0, 0, 'Negative print variants must not be excluded');
  }
  assert.equal(combinations.length, expected, `Expected ${expected} public engine combinations`);
  assert.equal(new Set(combinations.map(combo => combo.id)).size, expected, 'Duplicate look ID');
  assert.equal(new Set(combinations.map(combo => combo.number)).size, expected, 'Duplicate look number');
  assert.equal(films.length, 20, 'Expected 20 engine films');
  assert.equal(new Set(films.map(film => film.id)).size, films.length, 'Duplicate film ID');
  assert.equal(papers.length, 8, 'Expected eight print profiles');
  assert.equal(new Set(papers.map(paper => paper.id)).size, papers.length, 'Duplicate print profile');
  const negatives = films.filter(film => film.type === 'negative');
  const positives = films.filter(film => film.type === 'positive');
  assert.equal(negatives.length, 16, 'Expected 16 negative films');
  assert.equal(positives.length, 4, 'Expected four positive films');
  const filmById = new Map(films.map(film => [film.id, film]));
  const paperIds = new Set(papers.map(paper => paper.id));
  const base = new Map(), variants = [];
  for (const combo of combinations) {
    assert(!('printNeutralAmount' in combo) && !('neutralBaseId' in combo) && !combo.id.endsWith('__neutral30'), `Retired neutral variant metadata: ${combo.id}`);
    if ('castBaseId' in combo || 'filmCast' in combo || combo.id.endsWith(FILM_CAST_SUFFIX)) { variants.push(combo); continue; }
    assert(Number.isInteger(combo.number) && combo.number > 0 && combo.number < 1000, `Invalid base look number: ${combo.id}`);
    const film = filmById.get(combo.film);
    assert(film, `Unknown film in look: ${combo.id}`);
    let baseId;
    if (combo.processMode === 'negative_print') {
      assert.equal(film.type, 'negative', `Print requires a negative film: ${combo.id}`);
      assert(paperIds.has(combo.paper), `Unknown print profile: ${combo.id}`);
      baseId = `${combo.film}__${combo.paper}`;
    } else {
      assert.equal(combo.paper, null, `Paperless look has a print profile: ${combo.id}`);
      assert.equal(combo.processMode, film.type === 'positive' ? 'positive_direct' : 'negative_digital', `Unexpected paperless mode: ${combo.id}`);
      baseId = `${combo.film}__${film.type === 'positive' ? 'direct_scan' : 'digital_scan'}`;
    }
    assert.equal(combo.id, baseId, 'Base look ID must identify its film and output');
    assert(!base.has(baseId), `Duplicate base look: ${baseId}`);
    base.set(baseId, combo);
  }
  assert.equal(base.size, BASE_LOOKS, 'Expected 148 preserved base looks');
  for (const film of negatives) {
    assert(base.has(`${film.id}__digital_scan`), `Missing digital scan: ${film.id}`);
    for (const paper of papers) {
      const id = `${film.id}__${paper.id}`;
      assert(base.has(id), `Missing negative print: ${id}`);
    }
  }
  for (const film of positives) assert(base.has(`${film.id}__direct_scan`), `Missing positive scan: ${film.id}`);
  const paired = new Set();
  for (const combo of variants) {
    const original = base.get(combo.castBaseId);
    assert(original, `Film-cast variant without a base look: ${combo.id}`);
    assert.equal(original.processMode, 'negative_print', `Film-cast variant requires a print stage: ${combo.id}`);
    assert.equal(combo.processMode, 'negative_print', `Film-cast variant requires a print stage: ${combo.id}`);
    assert.equal(combo.id, `${original.id}${FILM_CAST_SUFFIX}`, 'Film-cast ID must identify its base print');
    assert.equal(combo.film, original.film, `Film-cast film differs from base: ${combo.id}`);
    assert.equal(combo.paper, original.paper, `Film-cast paper differs from base: ${combo.id}`);
    assert.equal(combo.number, original.number + FILM_CAST_NUMBER_OFFSET, `Film-cast number must be base + ${FILM_CAST_NUMBER_OFFSET}: ${combo.id}`);
    assert(!paired.has(original.id), `Duplicate film-cast variant: ${original.id}`);
    paired.add(original.id);
    const cast = combo.filmCast;
    assert(cast && cast.method === FILM_CAST_METHOD, `Missing film-cast recipe: ${combo.id}`);
    assert.equal(cast.amountPolicy, FILM_CAST_POLICY, `Film-cast amount must be solved per pair: ${combo.id}`);
    const editorialHue = catalog.filmCast?.targetHue?.[combo.film];
    if (editorialHue !== undefined) {
      // Editorial-hue films keep their own filters (amount 1) plus a solved M/Y shift.
      assert.equal(cast.directionPolicy, FILM_CAST_HUE_POLICY, `Editorial-hue film must declare its direction policy: ${combo.id}`);
      assert.equal(cast.targetHue, editorialHue, `Film-cast hue differs from the catalog: ${combo.id}`);
      assert.equal(cast.amount, 1, `Editorial-hue variant must use the film's own filters: ${combo.id}`);
      const shift = cast.hueShiftCC;
      assert(Array.isArray(shift) && shift.length === 3 && shift[0] === 0 && shift.slice(1).every(v => Number.isFinite(v) && Math.abs(v) <= 30)
        && shift.some(v => v !== 0), `Invalid editorial hue shift: ${combo.id}`);
      assert(cast.appliedCC.every((v, i) => Math.abs(v - (cast.filmCC[i] + shift[i])) < 1e-9), `Applied filters differ from film + hue shift: ${combo.id}`);
    } else {
      assert(!('directionPolicy' in cast) && !('hueShiftCC' in cast) && !('targetHue' in cast), `Unexpected editorial hue: ${combo.id}`);
      assert(Number.isFinite(cast.amount) && cast.amount >= FILM_CAST_MIN_AMOUNT && cast.amount < 1, `Film-cast amount out of range: ${combo.id}`);
    }
    assert.equal(cast.percent, Math.round(cast.amount * 100), `Film-cast displayed percent differs from its amount: ${combo.id}`);
    assert(Number.isFinite(cast.targetChroma) && cast.targetChroma > 0, `Missing film-cast chroma target: ${combo.id}`);
  }
  assert.equal(variants.length, declared, 'Film-cast variants differ from the declared count');
  return { baseLooks: base.size, filmCastLooks: variants.length, combinations: combinations.length };
}
