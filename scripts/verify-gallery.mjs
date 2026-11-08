import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';
import { downloadFilename } from '../src/lutNames.ts';

const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const digestPattern = /^[a-f0-9]{64}$/;
const exifFields = new Set(['PhotoStyle', 'LUT1Name', 'LUT1Opacity', 'LUT2Name', 'LUT2Opacity', 'ISO', 'FNumber', 'ExposureTime', 'ExposureCompensation', 'WhiteBalance', 'LensModel']);
const filmLutNames = {
  'Fujifilm C200 Alchemy TEST.cube': 'fujifilm_c200',
  'Kodak Gold 200.cube': 'kodak_gold_200',
  'Kodak Ektar 100 .cube': 'kodak_ektar_100',
  'Kodak Vision3 200T.cube': 'kodak_vision3_200t',
  'Fujifilm Velvia 100.cube': 'fujifilm_velvia_100',
};
export const GALLERY_MANIFEST = 'gallery/manifest.json';
export const RECOMMENDED_MANIFEST = 'gallery/recommended/manifest.json';
const recommendedPhotoFields = new Set(['id', 'sourceFilename', 'filmId', 'paperId', 'combinationId', 'path', 'thumbnailPath',
  'width', 'height', 'thumbnailWidth', 'thumbnailHeight', 'cameraId', 'cameraName', 'capturedAt', 'exif',
  'sourceSha256', 'preparedSha256', 'thumbnailSha256', 'filmEvidence', 'paperEvidence', 'renderKind', 'credit', 'license']);

function localPath(root, url, prefix) {
  assert(typeof url === 'string' && url.startsWith(prefix) && !/[\\?#]/.test(url), `Invalid photo path: ${url}`);
  const decoded = decodeURIComponent(url);
  assert(!decoded.split('/').includes('..'), `Unsafe photo path: ${url}`);
  const filename = path.resolve(root, '.' + decoded);
  assert(filename.startsWith(root + path.sep), `Unsafe photo path: ${url}`);
  return filename;
}

// Read dimensions and metadata flags from the actual derivative rather than
// trusting its JSON. Lossless and lossy WebP containers are both supported.
export function inspectWebp(bytes) {
  assert(bytes.length >= 20 && bytes.toString('ascii', 0, 4) === 'RIFF' && bytes.toString('ascii', 8, 12) === 'WEBP', 'Expected a WebP derivative');
  assert.equal(bytes.readUInt32LE(4) + 8, bytes.length, 'Truncated WebP');
  let dimensions, hasIcc = false, imagePayloads = 0;
  for (let offset = 12; offset < bytes.length;) {
    assert(offset + 8 <= bytes.length, 'Truncated WebP chunk');
    const type = bytes.toString('ascii', offset, offset + 4), size = bytes.readUInt32LE(offset + 4);
    const start = offset + 8, end = start + size;
    assert(end <= bytes.length, 'Truncated WebP chunk');
    assert(!['EXIF', 'XMP '].includes(type), 'Photo derivative contains private EXIF/XMP metadata');
    if (type === 'ICCP') hasIcc = size > 0;
    if (type === 'VP8X') {
      assert(size >= 10, 'Invalid extended WebP');
      assert.equal(bytes[start] & 0x0c, 0, 'Photo derivative advertises EXIF/XMP metadata');
      dimensions = { width: bytes.readUIntLE(start + 4, 3) + 1, height: bytes.readUIntLE(start + 7, 3) + 1 };
    } else if (type === 'VP8L') {
      assert(size >= 5 && bytes[start] === 0x2f, 'Invalid lossless WebP');
      const bits = bytes.readUInt32LE(start + 1);
      dimensions ||= { width: (bits & 0x3fff) + 1, height: ((bits >>> 14) & 0x3fff) + 1 };
      imagePayloads++;
    } else if (type === 'VP8 ') {
      assert(size >= 10 && bytes.toString('hex', start + 3, start + 6) === '9d012a', 'Invalid lossy WebP');
      dimensions ||= { width: bytes.readUInt16LE(start + 6) & 0x3fff, height: bytes.readUInt16LE(start + 8) & 0x3fff };
      imagePayloads++;
    }
    offset = end + (size % 2);
    assert(offset <= bytes.length, 'Invalid WebP padding');
  }
  assert(dimensions && imagePayloads === 1 && hasIcc, 'Expected one color-managed WebP image');
  return dimensions;
}

// The 2026-11-04 photographs were shot with the paper recommended at that
// time. Gold 200 was later re-recommended on Ektacolor Edge; the gallery keeps
// the pairing it was actually shot with.
export const recommendedAtCapture = { kodak_gold_200: 'kodak_portra_endura' };

export function assertPhotoContract(gallery, catalog) {
  assert.equal(gallery.schemaVersion, 1);
  assert.equal(gallery.source, 'user-provided');
  assert.equal(gallery.paperEvidence, 'user-confirmed-recommended');
  assert.equal(gallery.cameraId, 'S1II');
  assert(Array.isArray(gallery.items) && gallery.items.length > 0, 'Gallery is empty');
  const ids = new Set(), filenames = new Set(), paths = new Set();
  for (const item of gallery.items) {
    assert(!ids.has(item.id), 'Duplicate gallery photo'); ids.add(item.id);
    assert.match(item.sourceFilename, /^P\d+\.JPG$/i, 'Expected a source basename, not a local path');
    assert(!filenames.has(item.sourceFilename), 'Duplicate gallery source'); filenames.add(item.sourceFilename);
    const film = catalog.films.find(film => film.id === item.filmId);
    const combo = catalog.combinations.find(combo => combo.id === item.combinationId);
    assert(film && combo, 'Unknown gallery film or combination');
    assert.equal(combo.film, film.id, 'Gallery combination uses another film');
    assert.equal(item.paperId, recommendedAtCapture[film.id] ?? film.recommendedPrint, 'Gallery paper differs from the user-confirmed recommended setting');
    assert.equal(combo.paper, item.paperId, 'Gallery combination uses another paper');
    if (film.type === 'positive') {
      assert.equal(item.paperId, null, 'Slide gallery photographs must not claim a paper');
      assert.equal(combo.processMode, 'positive_direct');
    } else assert.equal(combo.processMode, 'negative_print');
    assert.equal(item.cameraId, gallery.cameraId);
    assert.equal(item.renderKind, 'camera-rendered');
    assert.equal(item.filmEvidence, 'camera-exif-lut1-name');
    assert(!('previewLut' in item) && !('inputKind' in item), 'A rendered gallery photo must not become an ungraded preview input');
    assert(item.exif && Object.keys(item.exif).every(key => exifFields.has(key)), 'Unexpected private EXIF field in gallery');
    assert.equal(item.exif.PhotoStyle, 'Standard or Custom');
    assert.equal(item.exif.LUT1Opacity, 100, 'Gallery must contain the camera-rendered LUT output');
    assert.equal(item.exif.LUT2Opacity, 0, 'Unexpected second LUT in gallery');
    assert.equal(filmLutNames[item.exif.LUT1Name], item.filmId, 'Gallery film does not match the camera EXIF LUT name');
    for (const key of ['sourceSha256', 'preparedSha256', 'thumbnailSha256']) assert.match(item[key], digestPattern, `Invalid photo ${key}`);
    for (const key of ['path', 'thumbnailPath']) {
      assert(!paths.has(item[key]), 'Duplicate photo derivative path'); paths.add(item[key]);
      localPath('/public', item[key], '/gallery/');
    }
  }
  const samples = catalog.samples.filter(sample => sample.inputKind === 'camera-std');
  const sampleIds = new Set(), sampleNames = new Set();
  for (const sample of samples) {
    assert(!sampleIds.has(sample.id), 'Duplicate Standard sample'); sampleIds.add(sample.id);
    assert(!filenames.has(sample.sourceFilename), 'Already graded gallery photo reused as a Standard sample');
    assert(!sampleNames.has(sample.sourceFilename), 'Duplicate Standard sample source'); sampleNames.add(sample.sourceFilename);
    assert.equal(sample.source, null); assert.equal(sample.previewLut, 'std');
    assert.equal(sample.cameraId, 'S1II');
    assert.equal(sample.cameraMetadata.Model, 'DC-S1M2');
    assert.equal(sample.cameraMetadata.PhotoStyle, 'Standard or Custom');
    assert.equal(sample.cameraMetadata.LUT1Opacity, 0, 'Standard sample already has a LUT applied');
    assert.equal(sample.cameraMetadata.LUT2Opacity, 0, 'Standard sample already has a second LUT applied');
    assert.equal(sample.cameraMetadata.ColorSpace, 'sRGB');
    for (const key of ['preparedSha256', 'thumbnailSha256']) assert.match(sample[key], digestPattern);
    for (const key of ['path', 'thumbnailPath']) localPath('/public', sample[key], '/samples/');
  }
  assert(catalog.samples.every(sample => ['camera-std', 'synthetic-srgb'].includes(sample.inputKind)), 'Retired external sample remains');
  assert.equal(catalog.samples.filter(sample => sample.inputKind === 'synthetic-srgb').length, 1, 'Keep one synthetic diagnostic chart');
  assert.equal(gallery.counts.photos, gallery.items.length);
  assert.equal(gallery.counts.standardSamples, samples.length);
  assert.equal(gallery.counts.films, new Set(gallery.items.map(item => item.filmId)).size);
}

// Unlike the first gallery, these camera LUT filenames explicitly encode
// the paper and FC variant. Today's recommended paper may change later.
export function assertRecommendedContract(manifest, catalog) {
  assert.equal(manifest.schemaVersion, 1);
  assert.equal(manifest.id, 'recommended');
  assert.equal(manifest.source, 'user-provided');
  assert.equal(manifest.paperEvidence, 'camera-exif-lut-filename');
  assert.equal(manifest.cameraId, 'S1II');
  assert(!/(?:\/(?:Users|home|Volumes|private|tmp)\/|file:\/\/|[A-Z]:[\\/])/i.test(JSON.stringify(manifest)), 'Private local path in recommended gallery');
  assert(Array.isArray(manifest.items) && manifest.items.length > 0, 'Recommended gallery is empty');
  const ids = new Set(), films = new Set(), pairs = new Set();
  for (const photo of manifest.items) {
    assert(Object.keys(photo).every(key => recommendedPhotoFields.has(key)), 'Unexpected public recommended photo field');
    assert.match(photo.sourceFilename, /^P\d+\.webp$/i, 'Expected a WebP source basename');
    assert.equal(photo.id, photo.sourceFilename.replace(/\.webp$/i, '').toLowerCase());
    assert(!ids.has(photo.id), 'Duplicate recommended source'); ids.add(photo.id);
    const prefix = '/gallery/recommended/';
    assert.equal(photo.path, `${prefix}images/${photo.id}.webp`, 'Invalid recommended image path');
    assert.equal(photo.thumbnailPath, `${prefix}thumbs/${photo.id}.webp`, 'Invalid recommended thumbnail path');
    assert.equal(photo.cameraId, manifest.cameraId);
    assert.equal(photo.filmEvidence, 'camera-exif-lut1-name');
    assert.equal(photo.paperEvidence, manifest.paperEvidence);
    assert.equal(photo.renderKind, 'camera-rendered');
    assert(!('previewLut' in photo) && !('inputKind' in photo), 'Recommended gallery photos are already graded');
    assert(photo.exif && Object.keys(photo.exif).every(key => exifFields.has(key)), 'Unexpected private EXIF field in recommended gallery');
    assert.equal(photo.exif.PhotoStyle, 'Standard or Custom');
    assert.equal(photo.exif.LUT1Opacity, 100);
    assert.equal(photo.exif.LUT2Opacity, 0);
    const combo = catalog.combinations.find(c => c.id === photo.combinationId);
    const film = catalog.films.find(f => f.id === photo.filmId);
    const paper = catalog.papers.find(p => p.id === photo.paperId);
    assert(combo && film && paper && combo.status === 'ready' && combo.processMode === 'negative_print', 'Unknown recommended print combination');
    assert.equal(combo.film, film.id, 'Recommended photo film mismatch');
    assert.equal(combo.paper, paper.id, 'Recommended photo paper mismatch');
    assert.equal(photo.exif.LUT1Name, downloadFilename(film, paper, combo.processMode, 'std', manifest.cameraId, !!combo.castBaseId), 'Recommended recipe does not match captured LUT filename');
    for (const key of ['sourceSha256', 'preparedSha256', 'thumbnailSha256']) assert.match(photo[key], digestPattern, `Invalid recommended photo ${key}`);
    for (const [key, limit] of [['width', 2400], ['height', 2400], ['thumbnailWidth', 480], ['thumbnailHeight', 480]]) {
      assert(Number.isInteger(photo[key]) && photo[key] > 0 && photo[key] <= limit, `Unexpected recommended photo ${key}`);
    }
    films.add(film.id); pairs.add(combo.id);
  }
  assert.equal(manifest.counts.photos, ids.size);
  assert.equal(manifest.counts.films, films.size);
  assert.equal(manifest.counts.combinations, pairs.size);
}

export async function verifyGallery(rootDir = 'public', suppliedCatalog) {
  const root = path.resolve(rootDir);
  const catalog = suppliedCatalog || JSON.parse(await fs.readFile(path.join(root, 'catalog.json'), 'utf8'));
  const gallery = JSON.parse(await fs.readFile(path.join(root, GALLERY_MANIFEST), 'utf8'));
  assertPhotoContract(gallery, catalog);
  const recommended = JSON.parse(await fs.readFile(path.join(root, RECOMMENDED_MANIFEST), 'utf8'));
  assertRecommendedContract(recommended, catalog);
  const sampleManifest = JSON.parse(await fs.readFile(path.join(root, 'samples/manifest.json'), 'utf8'));
  assert.deepEqual(sampleManifest, catalog.samples, 'Catalog uses stale sample metadata');
  const expectedGallery = new Set([GALLERY_MANIFEST, RECOMMENDED_MANIFEST]), expectedSamples = new Set(['samples/manifest.json', 'samples/external/manifest.json']);
  let images = 0;
  async function verifyImage(url, sha256, width, height, prefix) {
    const filename = localPath(root, url, prefix), bytes = await fs.readFile(filename);
    assert.equal(hash(bytes), sha256, `Changed photo: ${url}`);
    assert.deepEqual(inspectWebp(bytes), { width, height }, `Photo dimensions: ${url}`);
    images++;
    return path.relative(root, filename).split(path.sep).join('/');
  }
  for (const item of [...gallery.items, ...recommended.items]) {
    expectedGallery.add(await verifyImage(item.path, item.preparedSha256, item.width, item.height, '/gallery/'));
    expectedGallery.add(await verifyImage(item.thumbnailPath, item.thumbnailSha256, item.thumbnailWidth, item.thumbnailHeight, '/gallery/'));
  }
  for (const sample of catalog.samples) {
    // Imported photographs and the synthetic chart are all color-managed WebP.
    if (sample.inputKind === 'camera-std') {
      expectedSamples.add(await verifyImage(sample.path, sample.preparedSha256, sample.width, sample.height, '/samples/'));
      expectedSamples.add(await verifyImage(sample.thumbnailPath, sample.thumbnailSha256, sample.thumbnailWidth, sample.thumbnailHeight, '/samples/'));
    }
    else {
      const filename = localPath(root, sample.path, '/samples/');
      const bytes = await fs.readFile(filename);
      assert.deepEqual(inspectWebp(bytes), { width: sample.width, height: sample.height });
      images++;
      if (sample.preparedSha256) assert.equal(hash(bytes), sample.preparedSha256);
      expectedSamples.add(path.relative(root, filename).split(path.sep).join('/'));
    }
  }
  async function checkInventory(directory, expected) {
    for (const entry of await fs.readdir(directory, { withFileTypes: true })) {
      const filename = path.join(directory, entry.name), relative = path.relative(root, filename).split(path.sep).join('/');
      assert(!entry.isSymbolicLink(), `Photo symlink: ${relative}`);
      if (entry.isDirectory()) await checkInventory(filename, expected);
      else assert(entry.isFile() && expected.has(relative), `Retired or unlisted photo asset: ${relative}`);
    }
  }
  await checkInventory(path.join(root, 'gallery'), expectedGallery);
  await checkInventory(path.join(root, 'samples'), expectedSamples);
  return { photos: gallery.items.length, standardSamples: gallery.counts.standardSamples, films: gallery.counts.films,
    recommendedPhotos: recommended.counts.photos, recommendedCombinations: recommended.counts.combinations, verifiedImages: images };
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) console.log(JSON.stringify(await verifyGallery(process.argv[2]), null, 2));
