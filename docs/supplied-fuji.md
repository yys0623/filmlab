# Supplied FUJIFILM simulation LUTs

The active sosang catalog uses nine user-supplied Standard LUTs in place of the
previous official-FUJIFILM package integration. These are edited digital LUTs,
not unmodified official downloads. Their existing processing remains intact.

| Look | Original filename |
| --- | --- |
| ASTIA | `ASTIA - STD.cube` |
| CLASSIC CHROME | `CLASSIC CHROME - STD.cube` |
| CLASSIC Neg | `CLASSIC Neg - STD.cube` |
| ETERNA | `ETERNA - STD v2.cube` |
| ETERNA Bleach Bypass | `ETERNA BB - STD v2.cube` |
| PRO Neg | `PRO Neg - STD.cube` |
| PROVIA | `PROVIA - STD.cube` |
| REALA ACE | `REALA-ACE - STD v2.cube` |
| VELVIA | `VELVIA - STD v2.cube` |

All nine input files contain a 33³ RGB grid. The importer preserves every
numeric row, original title, and existing comment. It inserts
`#LUMIXPHOTOSTYLE STD` and only adds explicit `DOMAIN_MIN 0 0 0` /
`DOMAIN_MAX 1 1 1` when the source omitted those default domains. Numeric token
hashes are equal before and after import; the entire file hash changes because
of the added metadata.

The rendering path is **S1II Standard input → supplied cube → display**. No
paper selection, spektrafilm print stage, Alchemy adapter, further correction,
or 3D-grid rebake is applied. Preview interpolation is tetrahedral. There is no
V-Log variant and no inferred conversion for other cameras. S1II compatibility
comes from the supplied workflow and source-header context; this import does
not establish an independent camera calibration.

Reimport from the original folder, without editing files there:

```sh
.venv/bin/python -m pipeline.import_supplied_fuji --source "$LUT_SOURCE_DIR"
```

Set `LUT_SOURCE_DIR` to the local `ALL_FUJI_LUT` directory before running this
command. The folder is not bundled with the source archive. Public metadata
contains original basenames and hashes, never the user's absolute source path.

The importer removes the ten former `type: official` stocks and their 90
`official_direct` / `official_print` combinations. Their catalog snapshot,
asset directories and public official-package metadata are archived under
`artifacts/sosang-update/retired-fuji/`, outside the served tree. The 148
spektrafilm engine combinations remain. Repeated imports are deterministic and
do not regenerate or recolour the existing engine outputs.

`public/catalog.json` exposes the separate `suppliedFuji` inventory. Assets live
under `public/supplied-fuji/`: nine cubes, `provenance.json`, and `NOTICE.txt`.
Provenance records source/distributed byte counts and SHA-256 hashes plus
`numericRowsSha256`. The numeric hash is calculated from original decimal
tokens in original row order, with one ASCII space between channels and one LF
after each row; it ignores only headers and comments. The private import report
is `artifacts/sosang-update/supplied-fuji-import.json`.

The source author and license were not supplied. `author` and `license` are
therefore null and `licenseStatus` is `not-provided`; neither the app license nor
spektrafilm's license is asserted for these files. FUJIFILM names identify the
looks and do not imply endorsement.
