# v3 development baseline and separate transport

The historical JPG tone v3 rendering is the main development baseline again.
Single-tone A/B remains available for comparison. This change restores the
recorded v3 output; it does not regenerate its colour, change film profiles, or
claim that v3 is an unmodified upstream renderer. Later fixes should address
observed defects while checking that differences between film looks remain.

`pipeline/prepare_legacy_v3.py` publishes a separate, reproducible overlay from
the immutable `artifacts/std-precurve-baseline/` snapshot. The existing
`public/catalog.json`, current A/STD and B/STB files, VLOG files, QA, provenance,
and current ZIP bundles are preserved byte-for-byte. The separate manifest is
merged by the app at runtime; the audited A/B catalog is not rewritten.

## Prepare and verify

Run from `film-lab`:

```sh
.venv/bin/python -m pipeline.prepare_legacy_v3
.venv/bin/python -m pipeline.prepare_legacy_v3 --verify-only
.venv/bin/python -m pytest pipeline/tests/test_legacy_v3.py -q
```

The historical snapshot is required. It is an ignored local audit artifact,
so a source-only checkout without that snapshot cannot recreate the original
v3 bytes using this command. The script fails instead of substituting a new
rendering. Existing overlay files must already match exactly; preparation
does not silently overwrite a different baseline.

There are 238 active looks: 148 film-model looks and 90 official-source Fuji
compositions. The four reference interpretations are excluded. All originals
are verified before the overlay becomes visible. No public deployment is
performed by this script.

## Output and manifest

Each original archive is copied without recompression to:

```text
public/legacy-v3/<combination-id>/<original-number>LUTS.zip
public/legacy-v3/manifest.json
```

The manifest has `schemaVersion: 1`, `method: "legacy-v3-baseline"`, the SHA256
of the historical catalog, and a `combinations` array. Each record contains:

- `id` and `sourceVlogSha256`.
- `files.stdLegacy`: the old STD entry name, uncompressed size/SHA256,
  `encoding: "zip-entry"`, original ZIP URL and transfer size/SHA256.
- `files.zipLegacy`: the same original ZIP URL, size and SHA256.
- `qa`: the original `stdGeneration`, `jpgToneProtection`,
  `stdVsDirectEngine`, `stdVsContinuousComposition`, and `warnings` values.

The suggested single-LUT download name is `####STL.cube`; the suggested bundle
download name is `####V3.zip`. These are browser download names only. Original
ZIP bytes and its `####STD.cube` entry remain unchanged, including the
`#LUMIXPHOTOSTYLE STD` header. The bundle still includes its unchanged VLOG and
original QA/provenance, README, changelog and licence notices.

Historical film-model archives contain seven entries. Fuji archives contain
eight because they also include `FUJIFILM_NOTICE.txt`. Exact entry sets, CRCs,
entry sizes/SHA256, immutable snapshot hashes, and current VLOG identity are
checked. An altered VLOG is a failure, even if a current catalog hash has been
updated to match that alteration.

Fuji's original 90 QA records did not contain `stdGeneration` or
`stdVsContinuousComposition`; the sidecar records these as `null` instead of
inventing historical values. `jpgToneProtection` and `stdVsDirectEngine` are
copied as recorded. These old accuracy metrics retain their historical
reference and must not be relabeled as A/B precurve accuracy or measured
physical film/camera accuracy.

The report at `artifacts/legacy-v3-prepare-report.json` records counts, archive
entry counts, baseline/current catalog hashes, the overlay manifest hash, and
whether all 238 source VLOG files match. It also verifies that protected
current artifact files remain unchanged during preparation.

## Rights and provenance

Original archive notices remain intact. Upstream components retain their
spektrafilm attribution and licence. Fuji data retains its original rights;
this sidecar adds no redistribution rights or claim of an unmodified official
Fuji product. Camera sample photos are not included in these ZIP copies.
