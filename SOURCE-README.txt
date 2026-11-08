sosang — corresponding application source
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
Install Node.js 22.12 or newer and Yarn 1. Extract this archive, enter the
film-lab-source directory, and run:

  yarn install --frozen-lockfile
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

The usual yarn build command additionally runs scripts/pack-static.mjs.
That full authoring workflow expects the generated, unpacked public/ tree,
including raw .cube files. Use the two build commands above when using the
already packed runtime assets supplied by the public site. yarn dev and
yarn preview can serve the application locally once the appropriate public/
or dist/ runtime files have been supplied. See README.md for the full workflow.

In this checkout, the Vite development server proxies runtime assets from the
public deployment when public/catalog.json is absent. This requires an internet
connection. Supplying a local public/catalog.json disables the proxy; restart
the development server after adding it.

Browser regression tests
------------------------
Install the Playwright browser once with `yarn playwright install chromium`,
then run `yarn test:e2e`. The tests start their own development server and
exercise the print-filter retry and mobile mini-preview in Chromium. In this
source archive they require internet access to the public runtime assets.

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
