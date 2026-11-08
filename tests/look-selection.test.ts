import test from 'node:test'
import assert from 'node:assert/strict'
import { findLook, findFilmCast, processModeFor, selectStdAsset, selectDownloadAsset, selectStdQa, cameraForSample, sampleForCamera, downloadFilename, UNSUPPORTED_L10, suppliedCombination, previewCameraFor } from '../src/lookSelection.ts'
import type { Asset, Combination, Sample, SuppliedFujiLook } from '../src/types.ts'

const negative = { id: 'portra', type: 'negative' }
const slide = { id: 'velvia', type: 'positive' }
const official = { id: 'gfx_classic_chrome', type: 'official' }
const combinations: Combination[] = [
  { id: 'portra__endura', film: 'portra', paper: 'endura', processMode: 'negative_print', number: 1, status: 'ready' },
  { id: 'portra__crystal', film: 'portra', paper: 'crystal', processMode: 'negative_print', number: 2, status: 'ready' },
  { id: 'portra__digital_scan', film: 'portra', paper: null, processMode: 'negative_digital', number: 161, status: 'ready' },
  { id: 'portra__reference', film: 'portra', paper: null, processMode: 'reference_interpretation', number: 177, status: 'ready' },
  { id: 'velvia__direct_scan', film: 'velvia', paper: null, processMode: 'positive_direct', number: 41, status: 'ready' },
  { id: 'gfx_classic_chrome__direct', film: 'gfx_classic_chrome', paper: null, processMode: 'official_direct', number: 181, status: 'ready' },
  { id: 'gfx_classic_chrome__endura', film: 'gfx_classic_chrome', paper: 'endura', processMode: 'official_print', number: 182, status: 'ready' },
  { id: 'gfx_classic_chrome__crystal', film: 'gfx_classic_chrome', paper: 'crystal', processMode: 'official_print', number: 183, status: 'ready' },
]

test('print and digital select their exact combination while retaining the requested paper', () => {
  assert.equal(findLook(combinations, negative, 'crystal', 'negative_print')?.id, 'portra__crystal')
  assert.equal(findLook(combinations, negative, 'crystal', 'negative_digital')?.id, 'portra__digital_scan')
  assert.equal(findLook(combinations, negative, 'crystal', 'negative_print')?.id, 'portra__crystal')
})

test('slide always selects positive direct scan regardless of negative-mode preference', () => {
  for (const preference of ['negative_print', 'negative_digital'] as const) {
    assert.equal(processModeFor(slide, preference), 'positive_direct')
    assert.equal(findLook(combinations, slide, 'endura', preference)?.id, 'velvia__direct_scan')
  }
})

test('visiting a slide preserves the remembered negative process and selected paper', () => {
  const selectedPaper = 'crystal'
  for (const preference of ['negative_print', 'negative_digital'] as const) {
    const original = findLook(combinations, negative, selectedPaper, preference)
    assert.equal(findLook(combinations, slide, selectedPaper, preference)?.id, 'velvia__direct_scan')
    assert.equal(findLook(combinations, negative, selectedPaper, preference), original)
    assert.equal(findLook(combinations, negative, selectedPaper, 'negative_print')?.paper, selectedPaper)
  }
})

test('a missing digital asset never falls back to print or the wrong paperless process', () => {
  const unavailable = combinations.filter(c => c.processMode !== 'negative_digital')
  unavailable.push({ id: 'wrong_mode', film: 'portra', paper: null, processMode: 'positive_direct', number: 99, status: 'ready' })
  assert.equal(findLook(unavailable, negative, 'endura', 'negative_digital'), undefined)
  assert.equal(findLook(combinations, negative, 'missing_paper', 'negative_print'), undefined)
})

test('real-film reference look is independent from paper and experimental digital scan', () => {
  assert.equal(findLook(combinations, negative, 'crystal', 'reference_interpretation')?.id, 'portra__reference')
  assert.equal(findLook(combinations, negative, 'endura', 'reference_interpretation')?.id, 'portra__reference')
  assert.equal(findLook(combinations, { id: 'unsupported', type: 'negative' }, 'endura', 'reference_interpretation'), undefined)
  assert.equal(findLook(combinations.filter(c => c.processMode !== 'reference_interpretation'), negative, 'endura', 'reference_interpretation'), undefined)
  assert.equal(findLook(combinations, slide, 'endura', 'reference_interpretation')?.id, 'velvia__direct_scan')
})

test('official LUT can switch paper off and on without losing the selected paper', () => {
  assert.equal(findLook(combinations, official, 'crystal', 'official_print')?.id, 'gfx_classic_chrome__crystal')
  assert.equal(findLook(combinations, official, 'crystal', 'official_direct')?.id, 'gfx_classic_chrome__direct')
  assert.equal(findLook(combinations, official, 'endura', 'official_direct')?.id, 'gfx_classic_chrome__direct')
  assert.equal(findLook(combinations, official, 'crystal', 'official_print')?.paper, 'crystal')
  assert.equal(findLook(combinations, official, 'endura', 'official_print')?.id, 'gfx_classic_chrome__endura')
})

test('official LUT routes cannot resolve to real-film reference or negative digital assets', () => {
  assert.equal(processModeFor(official, 'reference_interpretation'), 'official_print')
  assert.equal(processModeFor(negative, 'official_direct'), 'negative_print')
  assert.equal(processModeFor(slide, 'official_print'), 'positive_direct')
  const withoutDirect = combinations.filter(c => c.processMode !== 'official_direct')
  withoutDirect.push({ id: 'wrong_official_scan', film: official.id, paper: null, processMode: 'negative_digital', number: 999, status: 'ready' })
  assert.equal(findLook(withoutDirect, official, 'crystal', 'official_direct'), undefined)
  assert.equal(findLook(combinations, official, 'missing', 'official_print'), undefined)
})

const file = (name: string): Asset => ({ name, path: `/luts/example/${name}`, bytes: 1, sha256: name })
const metric = { mean: .005, p95: .006, p99: .007, max: .008, samples: 100 }
const cameraCombo: Combination = {
  ...combinations[0], stdMethod: 'camera-vlog-alchemy-v1',
  files: { std: file('S1II_STD.cube'), vlog: file('VLOG.cube'), zip: file('S1II.zip'), qa: file('qa.json'), provenance: file('provenance.json') },
  stdByCamera: {
    S1II: { std: file('S1II_STD.cube'), zip: file('S1II.zip'), qa: { tetrahedral: metric, trilinear: metric }, warnings: ['S1II measurement'] },
    S5II: { std: file('S5II_STD.cube'), zip: file('S5II.zip'), qa: { tetrahedral: { ...metric, mean: .01 }, trilinear: metric }, warnings: ['S5II measurement'] },
  },
}

test('preview and downloads select the exact requested camera and preserve the shared V-Log', () => {
  for (const camera of ['S1II', 'S5II']) {
    const expected = cameraCombo.stdByCamera![camera]
    assert.equal(selectStdAsset(cameraCombo, camera), expected.std)
    assert.equal(selectDownloadAsset(cameraCombo, 'std', camera), expected.std)
    assert.equal(selectDownloadAsset(cameraCombo, 'zip', camera), expected.zip)
    assert.equal(selectDownloadAsset(cameraCombo, 'vlog', camera), cameraCombo.files!.vlog)
  }
  assert.notEqual(selectStdAsset(cameraCombo, 'S1II'), selectStdAsset(cameraCombo, 'S5II'))
})

test('unknown, missing and old-camera inputs never fall back to S1II or a retired STD', () => {
  for (const id of ['', 'S9', UNSUPPORTED_L10, 'l10', 'DMC-L10']) {
    assert.equal(selectStdAsset(cameraCombo, id), undefined)
    assert.equal(selectDownloadAsset(cameraCombo, 'std', id), undefined)
    assert.equal(selectDownloadAsset(cameraCombo, 'zip', id), undefined)
    assert.equal(selectDownloadAsset(cameraCombo, 'vlog', id), cameraCombo.files!.vlog)
  }
  assert.equal(selectStdAsset(undefined, 'S1II'), undefined)
  const old = { ...cameraCombo, stdMethod: undefined }
  assert.equal(selectStdAsset(old, 'S1II'), undefined)
  for (const format of ['std', 'vlog', 'zip'] as const) {
    assert.equal(selectDownloadAsset(old, format, 'S1II'), undefined)
    assert.equal(selectDownloadAsset({ ...cameraCombo, status: 'failed' }, format, 'S1II'), undefined)
  }
})

test('QA tracks the requested camera composition rather than the default-camera metric', () => {
  for (const camera of ['S1II', 'S5II']) {
    const qa = selectStdQa(cameraCombo, camera)
    assert.equal(qa.metric, cameraCombo.stdByCamera![camera].qa)
    assert.deepEqual(qa.warnings, cameraCombo.stdByCamera![camera].warnings)
    assert.equal(qa.method, 'camera-vlog-alchemy-v1')
  }
  assert.equal(selectStdQa(cameraCombo, UNSUPPORTED_L10).metric, undefined)
  assert.deepEqual(selectStdQa(undefined, 'S1II').warnings, [])
})

test('sample camera aliases resolve explicit model metadata without conflating the two L10 cameras', () => {
  for (const [model, id] of [['DC-S1M2', 'S1II'], ['DC-S1M2E', 'S1IIE'], ['DC-S1RM2', 'S1RII'], ['DC-S5M2', 'S5II'], ['DC-S5M2X', 'S5IIX'], ['DC-G9M2', 'G9II'], ['DC-GH6', 'GH6'], ['DC-GH7', 'GH7'], ['DC-S9', 'S9'], ['DC-L10', 'DC-L10']]) {
    assert.equal(cameraForSample({ cameraMetadata: { Model: model } }), id)
  }
  for (const [cameraId, id] of [['s5m2', 'S5II'], ['s1m2', 'S1II'], ['s1r2', 'S1RII'], ['s9', 'S9']]) assert.equal(cameraForSample({ cameraId }), id)
  for (const sample of [{ cameraMetadata: { Model: 'DMC-L10' } }, { cameraId: 'l10' }, { cameraName: 'LUMIX DMC-L10', cameraId: 'DC-L10' }]) assert.equal(cameraForSample(sample), UNSUPPORTED_L10)
  for (const sample of [undefined, null, {}, { cameraId: 'unknown' }, { cameraMetadata: { Model: 'DC-UNKNOWN' } }]) assert.equal(cameraForSample(sample), undefined)
})

test('download filenames preserve full film names, append print codes and distinguish V-Log', () => {
  const film = { id: 'fujifilm_c200', name: 'Fujifilm C200' }
  const paper = { id: 'fujifilm_crystal_archive_typeii', name: 'Fujifilm Crystal Archive Type II' }
  assert.equal(downloadFilename(film, paper, 'negative_print', 'std', 'LUMIX S1II'), 'C200CA.cube')
  assert.equal(downloadFilename(film, paper, 'negative_print', 'zip', 'LUMIX S5II'), 'C200CA-S5II.zip')
  assert.equal(downloadFilename(film, paper, 'negative_print', 'vlog', 'LUMIX S1II'), 'C200CAVLOG.cube')
  assert.equal(downloadFilename(film, paper, 'negative_print', 'vlog', 'LUMIX S1II'), downloadFilename(film, paper, 'negative_print', 'vlog', 'LUMIX S5II'))
  assert.equal(downloadFilename(film, undefined, 'negative_digital', 'std', 'S1II'), 'C200DS.cube')
  assert.equal(downloadFilename({ id: 'fujifilm_velvia_100', name: 'Fujifilm Velvia 100' }, undefined, 'positive_direct', 'vlog', 'S1II'), 'Velvia100SLVLOG.cube')
  assert.equal(downloadFilename({ id: 'kodak_portra_400', name: 'Kodak Portra 400' }, { id: 'kodak_endura_premier', name: 'Kodak Professional Endura Premier' }, 'negative_print', 'std', 'S1II'), 'Portra400EP.cube')
  assert.equal(downloadFilename({ id: 'kodak_vision3_200t', name: 'Kodak Vision3 200T' }, paper, 'negative_print', 'std', 'S1II'), 'Vision3200TCA.cube')
})

test('camera selection keeps a matching photo or switches to a matching sample, never to another model', () => {
  const photo = (id: string, cameraId?: string, inputKind: Sample['inputKind'] = 'review-jpeg'): Sample => ({ id, cameraId, inputKind, name: id, category: '', credit: '', source: null, path: '', width: 1, height: 1, previewLut: 'std' })
  const samples = [photo('one', 's1m2'), photo('two', 's1m2'), photo('three', 's5m2'), photo('old-l10', 'l10'), photo('chart', undefined, 'synthetic-srgb')]
  assert.equal(sampleForCamera(samples, 'S1II', 'two')?.id, 'two')
  assert.equal(sampleForCamera(samples, 'S5II', 'two')?.id, 'three')
  assert.equal(sampleForCamera(samples, 'S9', 'two')?.id, 'chart')
  assert.equal(sampleForCamera(samples, 'DC-L10', 'old-l10')?.id, 'chart')
  assert.equal(sampleForCamera(samples.filter(sample => sample.id !== 'chart'), 'DC-L10'), undefined)
})


test('supplied Fuji is a direct S1II STD asset with no paper, V-Log, ZIP or alternate-camera fallback', () => {
  const look: SuppliedFujiLook = { stock: { id: 'fuji_sim_astia', name: 'FUJIFILM ASTIA', type: 'supplied', stage: 'digital', brand: 'Fujifilm', use: 'digital', recommendedPrint: null, sha256: 'source' }, std: file('ASTIA.cube'), sourceFile: 'ASTIA - STD.cube', sourceSha256: 'source' }
  const combo = suppliedCombination(look, 'S1II')
  assert.equal(combo.paper, null)
  assert.equal(combo.processMode, 'supplied_direct')
  assert.equal(processModeFor(look.stock, 'negative_print'), 'supplied_direct')
  assert.equal(selectStdAsset(combo, 'S1II'), look.std)
  assert.equal(selectDownloadAsset(combo, 'std', 'S1II'), look.std)
  for (const camera of ['S5II', 'S9', UNSUPPORTED_L10]) assert.equal(selectDownloadAsset(combo, 'std', camera), undefined)
  for (const format of ['vlog', 'zip'] as const) assert.equal(selectDownloadAsset(combo, format, 'S1II'), undefined)
  assert.equal(downloadFilename(look.stock, undefined, combo.processMode, 'std', 'LUMIX S1II'), 'ASTIA.cube')
  assert.equal(selectStdQa(combo, 'S1II').metric, undefined)
})

test('S1II sample preview is independent from export camera, while uploads use the export camera', () => {
  const sample = { cameraId: 'S1II', inputKind: 'camera-std' } as Sample
  for (const target of ['S1II', 'S5II', 'S9']) {
    assert.equal(previewCameraFor(sample, false, target), 'S1II')
    assert.equal(previewCameraFor(sample, true, target), target)
    assert.equal(selectStdAsset(cameraCombo, previewCameraFor(sample, false, target)), cameraCombo.stdByCamera!.S1II.std)
  }
  assert.equal(previewCameraFor(null, false, 'S5II'), 'S1II')
  assert.equal(previewCameraFor({ cameraId: 'l10' } as Sample, false, 'S1II'), UNSUPPORTED_L10)
})

test('film-cast variants never replace the base look and pair only with their own print', () => {
  const cast: Combination = { id: 'portra__crystal__filmcast', film: 'portra', paper: 'crystal', processMode: 'negative_print', number: 1002, status: 'ready', castBaseId: 'portra__crystal' }
  const withCast = [cast, ...combinations]
  const base = findLook(withCast, negative, 'crystal', 'negative_print')
  assert.equal(base?.id, 'portra__crystal')
  assert.equal(findFilmCast(withCast, base)?.id, cast.id)
  assert.equal(findFilmCast(withCast, findLook(withCast, negative, 'endura', 'negative_print')), undefined)
  assert.equal(findFilmCast(withCast, findLook(withCast, negative, 'crystal', 'negative_digital')), undefined)
  assert.equal(findFilmCast(withCast, cast), undefined)
  assert.equal(findFilmCast([{ ...cast, status: 'failed' }, ...combinations], base), undefined)
  assert.equal(findFilmCast(withCast, undefined), undefined)
})
