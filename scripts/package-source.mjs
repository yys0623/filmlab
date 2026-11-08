// Publish editable source and the pinned, Apache-licensed camera input adapters.
// Private photographs and creative/output LUT bundles remain excluded.
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { gzipSync } from 'node:zlib';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const destination = path.resolve(root, process.argv[2] || 'dist-cloudflare');
const directories = ['src', 'server', 'tests', 'scripts', 'pipeline', 'licenses', 'docs', 'public/camera-adapters'];
const requiredFiles = ['index.html', 'tsconfig.json', 'package.json', 'package-lock.json', 'LICENSE', 'README.md'];
const optionalFiles = ['wrangler.jsonc', 'wrangler.legacy.jsonc'];
const extensions = new Set(['.ts', '.tsx', '.js', '.jsx', '.mjs', '.cjs', '.css', '.scss', '.py', '.json', '.jsonc', '.md', '.txt', '.lock', '.html']);
const excludedDirectories = new Set(['vendor', 'vendors', 'cache', 'caches', '__pycache__', 'node_modules', 'public', 'dist', 'dist-cloudflare', 'assets', 'samples', 'originals', 'artifacts', 'coverage', 'credentials', 'secrets']);
const excludedFiles = /(?:^|[._-])(?:credentials?|secrets?|id_rsa|id_ed25519)(?:[._-]|$)|\.(?:pyc|pyo|pem|key|p12|pfx)$/i;
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
const archiveDirectory = 'film-lab-source';
const archiveName = 'film-lab-source.tar.gz';
const maxArchiveBytes = 25 * 1024 * 1024;

function assert(condition, message) { if (!condition) throw new Error(message); }
function within(directory, candidate) { return candidate === directory || candidate.startsWith(directory + path.sep); }
function runTar(args) {
  const result = spawnSync('tar', args, { encoding: 'utf8', env: { ...process.env, COPYFILE_DISABLE: '1' }, maxBuffer: 8 * 1024 * 1024 });
  if (result.error) throw result.error;
  assert(result.status === 0, `tar failed: ${result.stderr.trim()}`);
  return result.stdout;
}

// Require an already prepared deployment: this script must not initialize or
// overwrite a source directory when given the wrong destination argument.
const destinationStat = await fs.lstat(destination);
assert(destinationStat.isDirectory() && !destinationStat.isSymbolicLink(), 'Destination must be a real prepared deployment directory');
assert(destination !== root && !directories.some(name => within(path.join(root, name), destination)), 'Destination overlaps the source tree');
const catalogPath = path.join(destination, 'catalog.json');
const catalogStat = await fs.lstat(catalogPath);
assert(catalogStat.isFile() && !catalogStat.isSymbolicLink(), 'Destination catalog must be a regular file');
const catalogBytes = await fs.readFile(catalogPath);
const catalog = JSON.parse(catalogBytes.toString('utf8'));
assert(Array.isArray(catalog.combinations), 'Destination catalog has no combinations');

const selected = [];
async function select(relative) {
  assert(!relative.includes('\\') && !/[\r\n\0]/.test(relative), `Unsafe source path: ${relative}`);
  // This local video production workspace is not corresponding application source.
  if (relative === 'docs/video') return;
  const name = path.posix.basename(relative);
  if (name.startsWith('.') || excludedDirectories.has(name.toLowerCase()) || excludedFiles.test(name)) return;
  const absolute = path.join(root, relative);
  const stat = await fs.lstat(absolute);
  assert(!stat.isSymbolicLink(), `Source symlinks are not allowed: ${relative}`);
  if (stat.isDirectory()) {
    for (const child of (await fs.readdir(absolute)).sort()) await select(`${relative}/${child}`);
    return;
  }
  assert(stat.isFile(), `Not a regular source file: ${relative}`);
  assert(requiredFiles.includes(relative) || optionalFiles.includes(relative) || extensions.has(path.extname(name).toLowerCase()) || (relative.startsWith('public/camera-adapters/') && name.endsWith('.cube')) || /^LICEN[CS]E(?:[._-].*)?$/.test(name), `Unexpected non-source file: ${relative}`);
  assert(stat.size <= 5 * 1024 * 1024, `Unexpectedly large source file: ${relative}`);
  selected.push(relative);
}
for (const relative of [...directories, ...requiredFiles]) await select(relative);
for (const relative of optionalFiles) {
  try { await fs.lstat(path.join(root, relative)); }
  catch (error) { if (error.code === 'ENOENT') continue; throw error; }
  await select(relative);
}
selected.sort();
assert(selected.includes('server/worker.mjs') && selected.includes('src/main.tsx') && selected.includes('src/lut.worker.ts') && selected.includes('scripts/package-source.mjs'), 'Required editable application sources are missing');

for (const required of ['pipeline/camera_std.py', 'pipeline/import_supplied_fuji.py', 'docs/supplied-fuji.md', 'scripts/migrate-camera-std.py', 'scripts/verify-camera-std.mjs', 'scripts/verify-gallery.mjs', 'scripts/verify-supplied-fuji.mjs', 'public/camera-adapters/source.json', 'public/camera-adapters/manifest.json', 'public/camera-adapters/V-Log-Alchemy-LICENSE.txt']) assert(selected.includes(required), `Required LUT source is missing: ${required}`);
assert(selected.filter(name => name.startsWith('public/camera-adapters/') && name.endsWith('.cube')).length === 10, 'Exactly ten pinned camera input adapters must be included');

const sourceReadme = `sosang — corresponding application source
==========================================

This archive contains the editable TypeScript/React application and Web Worker,
build and verification scripts, Python color-processing code/configuration,
tests, dependency lock files, documentation, and applicable code licenses.
The ten pinned V-Log Alchemy camera input adapters, manifest, calibration
reports, and Apache-2.0 license are included in public/camera-adapters/.
Read LICENSE and licenses/ for the licensing terms. Third-party data retains
its own rights; this source archive does not grant rights to photographs or
FUJIFILM's original LUT data.

Build the browser JavaScript and CSS
-----------------------------------
Install Node.js 22.12 or newer and npm. Extract this archive, enter the
film-lab-source directory, and run:

  npm ci
  node node_modules/typescript/bin/tsc -b
  node node_modules/vite/bin/vite.js build

This compiles the application and its worker into dist/ without needing any
private photograph or external LUT source package. The application fetches its
catalog, previews, and LUTs at runtime; a JS-only build therefore needs runtime
assets before it can display the available looks.

Runtime assets are supplied separately by the public deployment from which
this archive was downloaded. Its /catalog.json lists public sample images,
preview images, and per-look ZIP assets, with byte sizes and SHA-256 hashes.
The gallery uses /gallery/manifest.json and /gallery/recommended/manifest.json;
include the prepared image and thumbnail paths from each. Gallery photos are already rendered
and must never be fed through another LUT as Standard sample inputs.
Serve that catalog and its referenced files at the same URL paths alongside
the compiled app; include the public /favicon.svg, /fonts/ and /licenses/ files too.
The /api/locale endpoint runs in server/worker.mjs on Cloudflare; its deployment
configuration is wrangler.jsonc. Locally the UI falls back to browser language.
Creative output LUTs and photographs are intentionally not duplicated in this
source archive. Only the ten reusable camera input adapters are included.
Each look has a stdByCamera map: select the explicit camera entry; never
substitute the default camera for an unsupported model. Its ZIP contains that
camera's merged STD and the unchanged creative VLOG cube. In the packed
deployment, std/vlog records refer to entries in their selected camera ZIP;
copy that ZIP once and retain the catalog's encoding and transfer hash fields.
Do not treat the ZIP as a raw .cube file or run pack-static.mjs on an already
packed deployment. The public source download is /source/film-lab-source.tar.gz.

The usual npm run build command additionally runs scripts/pack-static.mjs.
That full authoring workflow expects the generated, unpacked public/ tree,
including raw .cube files. Use the two build commands above when using the
already packed runtime assets supplied by the public site. npm run dev and
npm run preview can serve the application locally once the appropriate public/
or dist/ runtime files have been supplied. See README.md for the full workflow.

The JS tests include runtime-asset integrity and interpolation fixtures; some
tests require the corresponding generated public/ assets. SOURCE-MANIFEST.json
records every selected source file's SHA-256 and size, plus this README. It does
not list itself, and is not a manifest of third-party runtime data.

Optional Python regeneration
----------------------------
See README.md and pipeline/requirements.lock. scripts/bootstrap.py obtains the
upstream spektrafilm repository at the commit pinned in pipeline/config/default.json
and installs the pinned Python dependencies. The vendor checkout and virtual
environment are not bundled. Color configuration and all sosang processing
code are included; sample images and original FUJIFILM LUT archives are not.
pipeline/camera_std.py composes the selected input adapter with each existing
creative VLOG. scripts/migrate-camera-std.py regenerates all camera variants
and preserves VLOG bytes. It requires the unpacked public look catalog and
VLOG assets in addition to the included input adapters.
Photo-based preview regeneration requires separately supplied sample inputs.
The supplied FUJIFILM STD looks are imported separately without color changes
or paper processing. Their source files and output hashes are recorded in
the runtime /supplied-fuji/provenance.json; source LUT files are not bundled
in this application-source archive. See docs/supplied-fuji.md.
No credentials are needed to compile the browser application. Hosting account
credentials, local caches, user originals, and build outputs are excluded.
`;

const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'film-lab-source-'));
try {
  const staging = path.join(temporary, archiveDirectory);
  const manifest = { schema: 1, files: [] };
  async function stage(relative, bytes) {
    // Fresh files avoid copying extended attributes, resource forks, or local
    // filesystem ownership into the archive.
    new TextDecoder('utf-8', { fatal: true }).decode(bytes);
    assert(!bytes.includes(0), `Binary content in source file: ${relative}`);
    assert(!/-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----/.test(bytes.toString('utf8')), `Private key content in source file: ${relative}`);
    const output = path.join(staging, relative);
    await fs.mkdir(path.dirname(output), { recursive: true });
    await fs.writeFile(output, bytes, { mode: 0o644 });
    await fs.chmod(output, 0o644);
    await fs.utimes(output, 0, 0);
    manifest.files.push({ path: relative, bytes: bytes.length, sha256: sha256(bytes) });
  }
  for (const relative of selected) await stage(relative, await fs.readFile(path.join(root, relative)));
  await stage('SOURCE-README.txt', Buffer.from(sourceReadme));
  const manifestFile = path.join(staging, 'SOURCE-MANIFEST.json');
  await fs.writeFile(manifestFile, JSON.stringify(manifest, null, 2) + '\n', { mode: 0o644 });
  await fs.utimes(manifestFile, 0, 0);

  const entries = [...manifest.files.map(file => file.path), 'SOURCE-MANIFEST.json'].sort().map(relative => `${archiveDirectory}/${relative}`);
  const fileList = path.join(temporary, 'files.txt');
  await fs.writeFile(fileList, entries.join('\n') + '\n');
  const tarPath = path.join(temporary, 'source.tar');
  const version = runTar(['--version']);
  const ownerArguments = /bsdtar/i.test(version) ? ['--uid=0', '--gid=0', '--uname=root', '--gname=root'] : ['--owner=0', '--group=0'];
  runTar(['-cf', tarPath, '--format=ustar', ...ownerArguments, '-C', temporary, '-T', fileList]);
  assert((await fs.stat(tarPath)).size < 128 * 1024 * 1024, 'Source tar exceeds the expected source-only size');
  const archive = gzipSync(await fs.readFile(tarPath), { level: 9 });
  assert(archive.length < maxArchiveBytes, 'Source archive must be smaller than 25 MiB');
  const archivePath = path.join(temporary, archiveName);
  await fs.writeFile(archivePath, archive);
  const actualEntries = runTar(['-tzf', archivePath]).trim().split('\n');
  assert(JSON.stringify(actualEntries) === JSON.stringify(entries), 'Source archive contains unexpected or missing entries');

  // Avoid replacing a catalog that another generation process changed while
  // source packaging was in progress.
  assert((await fs.readFile(catalogPath)).equals(catalogBytes), 'Destination catalog changed while source was being packaged');
  const sourceDirectory = path.join(destination, 'source');
  await fs.mkdir(sourceDirectory, { recursive: true });
  const sourceStat = await fs.lstat(sourceDirectory);
  assert(sourceStat.isDirectory() && !sourceStat.isSymbolicLink(), 'Source output must be a real directory');
  const stagedArchive = path.join(sourceDirectory, `.${archiveName}.${process.pid}.tmp`);
  const stagedCatalog = path.join(destination, `.catalog.source.${process.pid}.tmp`);
  try {
    await fs.writeFile(stagedArchive, archive, { flag: 'wx', mode: 0o644 });
    catalog.sourceCode = { path: `/source/${archiveName}`, bytes: archive.length, sha256: sha256(archive) };
    await fs.writeFile(stagedCatalog, JSON.stringify(catalog, null, 2) + '\n', { flag: 'wx', mode: 0o644 });
    await fs.rename(stagedArchive, path.join(sourceDirectory, archiveName));
    await fs.rename(stagedCatalog, catalogPath);
  } finally {
    await fs.rm(stagedArchive, { force: true });
    await fs.rm(stagedCatalog, { force: true });
  }
  console.log(`Packaged ${entries.length} source files (${archive.length} bytes): ${path.join(sourceDirectory, archiveName)}`);
  console.log(`SHA-256: ${catalog.sourceCode.sha256}`);
} finally {
  await fs.rm(temporary, { recursive: true, force: true });
}
