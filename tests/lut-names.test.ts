import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { downloadFilename, PAPER_CODES, paperLabel } from '../src/lutNames.ts'
import type { Catalog } from '../src/types.ts'

const catalog: Catalog = JSON.parse(readFileSync(new URL('../public/catalog.json', import.meta.url), 'utf8'))

test('every current paper displays the same unique code used in downloads', () => {
  assert.equal(new Set(Object.values(PAPER_CODES)).size, catalog.papers.length)
  for (const paper of catalog.papers) {
    assert.match(PAPER_CODES[paper.id], /^[A-Z0-9]+$/)
    assert.equal(paperLabel(paper), `${paper.name} (${PAPER_CODES[paper.id]})`)
    assert.ok(paperLabel(paper, true).endsWith(`(${PAPER_CODES[paper.id]})`))
  }
})

test('all downloadable looks retain film words, have safe unique names, and separate STD from V-Log', () => {
  const names = new Set<string>()
  for (const combo of catalog.combinations.filter(combo => combo.status === 'ready')) {
    const film = catalog.films.find(film => film.id === combo.film)!
    const paper = catalog.papers.find(paper => paper.id === combo.paper)
    const fullFilm = film.name.replace(/^(Kodak|Fujifilm) (Professional )?/i, '').replace(/[^A-Za-z0-9]/g, '')
    for (const format of ['std', 'vlog'] as const) {
      const name = downloadFilename(film, paper, combo.processMode, format, 'S1II', !!combo.castBaseId)
      assert.match(name, /^[A-Za-z0-9]+\.cube$/)
      assert.ok(name.startsWith(fullFilm))
      assert.ok(!names.has(name.toLowerCase()), name)
      names.add(name.toLowerCase())
      for (const camera of catalog.cameraAdapters!.models) {
        assert.equal(downloadFilename(film, paper, combo.processMode, format, camera.id, !!combo.castBaseId), name)
      }
    }
  }
  for (const look of catalog.suppliedFuji!.looks) {
    const name = downloadFilename(look.stock, undefined, 'supplied_direct', 'std', 'S1II')
    assert.match(name, /^[A-Za-z0-9]+\.cube$/)
    assert.ok(!names.has(name.toLowerCase()), name)
    names.add(name.toLowerCase())
  }
})

test('long film names and push variants are not truncated to eight characters', () => {
  const paper = catalog.papers.find(paper => paper.id === 'kodak_endura_premier')!
  for (const [id, expected] of [
    ['kodak_portra_400', 'Portra400EP.cube'],
    ['kodak_portra_800_push1', 'Portra800Push1EP.cube'],
    ['kodak_portra_800_push2', 'Portra800Push2EP.cube'],
    ['kodak_vision3_200t', 'Vision3200TEP.cube'],
  ]) {
    const film = catalog.films.find(film => film.id === id)!
    assert.equal(downloadFilename(film, paper, 'negative_print', 'std', 'S1II'), expected)
  }
})

test('film-cast variants keep the print code and add FC; paperless modes reject it', () => {
  const film = catalog.films.find(film => film.id === 'kodak_gold_200')!
  const paper = catalog.papers.find(paper => paper.id === 'fujifilm_crystal_archive_typeii')!
  assert.equal(downloadFilename(film, paper, 'negative_print', 'std', 'S1II', true), 'Gold200CAFC.cube')
  assert.equal(downloadFilename(film, paper, 'negative_print', 'vlog', 'S1II', true), 'Gold200CAFCVLOG.cube')
  assert.equal(downloadFilename(film, paper, 'negative_print', 'zip', 'LUMIX S1II', true), 'Gold200CAFC-S1II.zip')
  assert.throws(() => downloadFilename(film, undefined, 'negative_digital', 'std', 'S1II', true))
})
