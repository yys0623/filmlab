# External review JPEG samples for local comparison

> Current previews select a matching camera adapter. DMC-L10 has no supported adapter and is shown without a transformed preview; it must never resolve to DC-L10. JPEG Photo Style evidence and redistribution limits below remain applicable.

This collection prepares **30 external review JPEGs** for the local Film Lab editor: the 29 external photographs selected in the previous `sample-study`, plus one newly selected S1 II sunny scene from the original files already downloaded for that study. It contains input photographs only. No film LUT, A/B tone mapping, exposure, white-balance adjustment, saturation adjustment or noise reduction is baked into these images. The app applies the sole active STD B LUT at runtime; earlier STD variants are retained only in local development records.

The parent catalog and LUTs are unchanged by this importer. The previous study's 124 film-rendered pictures use the old v3 policy and are **not reused**.

## Files and reproduction

Run from `film-lab`:

```sh
.venv/bin/python -m pipeline.import_external_samples
```

The importer reads `../sample-study/manifest.json` and `../sample-study/originals/<study-id>.jpg`. It checks the original SHA256 and reads EXIF again with ExifTool before creating outputs. The newly selected `dpr-s1m2pre-12` has a separate `SUPPLEMENTS` record in the importer containing its original URL, SHA256, metadata and selection evidence. This keeps the historical study manifest intact and makes the extra source reproducible.

Outputs:

- `public/samples/external/manifest.json`
- `public/samples/external/<study-id>.webp`: EXIF orientation applied, embedded ICC converted to sRGB when present, longest side at most 1600 pixels using Lanczos, lossless WebP with an sRGB ICC profile.
- `public/samples/external/<study-id>-thumb.webp`: aspect ratio preserved within 320×240, also lossless WebP with sRGB ICC.

If an original has no embedded ICC profile, its freshly verified EXIF sRGB tag supplies the input-colour-space assumption. The importer verifies decoded RGB equality with the prepared pixels for both image sizes. This is lossless verification of each **resized/prepared** image; resizing is not claimed to preserve every full-resolution source pixel. Runtime/library versions and the source-study manifest SHA are recorded in `preparation`.

## Coverage and selection

| Camera ID | Camera | Unique photographs | Covered condition slots |
|---|---|---:|---:|
| s5m2 | LUMIX S5 II | 7 | 7 |
| s1m2 | LUMIX S1 II | 6 | 6 |
| s1r2 | LUMIX S1R II | 6 | 7 |
| l10 | LUMIX DMC-L10 | 4 | 5 |
| s9 | LUMIX S9 | 7 | 7 |

There are 32 covered slots out of the requested 35. S1R II `dpr-s1r2-29` serves both bright indoor and indoor portrait conditions; DMC-L10 `dpr-l10-07` serves both dim indoor and indoor portrait conditions. These are shared frames, not additional unique photographs.

The three unavailable external conditions remain explicit in `missing`:

- S1 II bright indoor: the previous study used the user's figures photo; no external original with a sufficiently clear scene classification was selected.
- DMC-L10 overcast outdoors.
- DMC-L10 overcast outdoor portrait.

S1 II sunny is now covered by `external-dpr-s1m2pre-12`: a DPReview pre-production image showing blue sky, sunlit city/rail infrastructure and deep ground shadows. Its original SHA256 is `1878e0bf04fbd4f838a2b3da1f6a5c143dedbc40ddf1dbd875b432ac0f91698d`. The `preproduction: true` flag is retained.

Weather is inferred from photographs or the original source description, not checked against weather records. The Korean and English notes preserve uncertainty about overcast versus building shade. “Portrait in sunshine” may be backlit; notes identify this distinction. The L10 indoor-dim example is a window-lit portrait classified using scene appearance and ISO 320 / f/5.6 / 1/30 s, rather than a measured room-light level.

## Camera metadata verification

The original 29 selected files were rehashed and their current EXIF was read independently of the old manifest. All 29 hashes and selected metadata fields matched. The additional S1 II sunny original was separately hash-checked and its EXIF matched the pinned supplemental record, giving **30 checked input originals**.

- All models match the expected camera: `DC-S5M2`, `DC-S1M2`, `DC-S1RM2`, `DMC-L10`, or `DC-S9`.
- All 26 modern-camera images report **`PhotoStyle: Standard or Custom`**, preserved verbatim. This tag does not establish that every proprietary camera setting equals the factory Standard default.
- S1 II, S1R II and S9: **19 images** have empty LUT 1/2 names and both opacity values explicitly zero.
- S5 II: **7 images** have the expected PhotoStyle and an empty LUT name, but opacity tags are unavailable. This weaker evidence is stated in both languages; the importer does not invent zero-opacity values.
- DMC-L10: **4 images** report **`FilmMode: Standard (color)`**.
- All 30 report sRGB.
- Seven images retain the previous or source-declared early/pre-production flag. Cameralabs `cl-s1r2-16` reports firmware `Ver.0.5`; its notes explicitly say production-camera status is unconfirmed. A false `preproduction` flag there means it was not classified as pre-production by the stored selection record, not proof of production firmware.

The earlier exclusions remain appropriate: Photography Blog S1R II samples with “Sample LUT1” at 100%; DPReview S1R II #2/#21 with Natural style; RAW developments and monochrome/Dynamic samples. None is silently used to fill a missing Standard condition.

These are review JPEGs, **not matched Standard/V-Log captures**. They can illustrate look behaviour across different lighting and cameras; they cannot validate a measured camera Standard inverse or rank camera colour accuracy.

## Sources, attribution and local scope

There are 15 DPReview images, 14 Photography Blog images and one Cameralabs image. Every entry retains a source page URL, direct original URL, credit and original SHA256. Individual photographers are not guessed where the original EXIF Artist is empty.

Representative source pages:

- [DPReview S5 II gallery](https://www.dpreview.com/sample-galleries/1023117505/panasonic-s5-ii-sample-gallery-dpreview-tv/)
- [DPReview S1 II gallery](https://www.dpreview.com/sample-galleries/4490579097/panasonic-s1ii-sample-gallery/)
- [DPReview S1 II pre-production gallery](https://www.dpreview.com/sample-galleries/6093167269/panasonic-s1ii-pre-production-sample-gallery/)
- [DPReview S1R II gallery](https://www.dpreview.com/sample-galleries/0830456176/panasonic-lumix-dc-s1rii-sample-gallery/)
- [DPReview DMC-L10 gallery](https://www.dpreview.com/sample-galleries/3952923458/panasonic-lumix-dmc-l10-review-samples/)
- [Photography Blog S5 II review](https://www.photographyblog.com/reviews/panasonic_lumix_s5ii_review), [S1 II review](https://www.photographyblog.com/reviews/panasonic_lumix_s1_ii_review), [S9 review](https://www.photographyblog.com/reviews/panasonic_lumix_s9_review), [DMC-L10 review](https://www.photographyblog.com/pages/reviews/reviews_panasonic_lumix_dmc_l10_3.php)
- [Gordon Laing / Cameralabs S1R II café photograph](https://www.flickr.com/photos/cameralabs/54442767164/)

The local cached Cameralabs/Flickr source explicitly permits downloading originals for evaluation on one's own computer or printer, and says another website or publication requires permission. Its stored Flickr `license` value is 0. The cached Photography Blog pages retain a Photo 360 copyright notice. The collected DPReview/Photography Blog records contain no general redistribution or Creative Commons grant. Blank EXIF copyright fields are not treated as a permission grant.

**`localOnly: true` is a distribution-scope flag, not a redistribution licence or automatic access control.** Copyright remains with the sources. Attribution does not itself grant permission. These assets are intended for the user-requested local comparison; the deployment/build layer must exclude this directory from a public package unless separate publication rights are established. No source claims are inferred from the LUT/software licences.

## Manifest contract

The root has `schemaVersion: 1`, `localOnly: true`, `models`, `scenes`, `missing`, `samples`, `preparation` and `rights`. Models use `{id,name}`. Scenes use `{id,name,nameEn}`. Missing entries use `{camera,scene,reason,reasonEn}`.

Every sample has:

```text
id = external-<study-id>
name, nameEn, category, categoryEn
credit, source, originalUrl
path, thumbnailPath, width, height
inputKind = review-jpeg
previewLut = std
cameraId, cameraName, scenes
notes, notesEn, stdEvidence, stdEvidenceEn, preproduction
sourceFilename, sourceSha256, preparedSha256, cameraMetadata
```

`previewLut: std` identifies the rendered JPEG input family; it does not mean a LUT was applied to the prepared file. The editor uses STD B for every sample and uploaded image. `cameraMetadata` retains the checked metadata values, not the machine's absolute input filename. Thumbnail and image paths are local `/samples/external/…` paths. Names, condition labels, notes and evidence are available in Korean and English; film/LUT data remain in the main catalog.
