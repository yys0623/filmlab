# Legacy v3 local baseline validation — 2026-11-03

> Historical study. Current STD delivery uses the model-specific V-Log Alchemy adapter; see [camera STD](camera-std.md). The measurements below describe the former implementation.

The requested direction is to preserve the existing differences between film looks and make targeted corrections only when a defect is demonstrated. This update makes **Legacy v3** the local default and keeps A/B available in the same editor. It does not change v3 LUT samples, A/B samples, or V-Log files. This is a working baseline, not a new claim of physical film accuracy.

## Preservation and application

- All 238 original v3 STD files and their original ZIP archives are SHA-256 verified against the recorded baseline. All 238 source V-Log files also match the current V-Log files.
- The existing A/B catalog and 1,429 protected current assets remained unchanged during preparation.
- Preview, uploaded photos and single STD downloads select the same asset. A/B selections retain their original files; V-Log is independent of this choice.
- v3 downloads use `####STL.cube` and `####V3.zip` to distinguish them from A/B downloads. The original `####STD.cube` entry inside each ZIP is unchanged.
- The displayed v3 QA comes from the original v3 ZIP. A/B comparison metrics are not shown as v3 measurements.

## Runtime checks

47 JavaScript tests passed, including all 238 overlay mappings, wrong/missing baseline rejection, variant and ZIP routing, independent tetrahedral interpolation, archive integrity and language behavior. Five Python packaging tests passed. TypeScript/production build and the packed `dist` asset verifier passed; the verifier checked 238 v3 ZIPs/STD entries in addition to the current A/B assets.

Browser checks covered the default v3 selection, A/B switching, sample-camera switching, version-specific QA, real STD download, Korean/English text and the 390-pixel layout. The actual browser download `0081STL.cube` matched the preserved Portra 400 + Crystal Archive Type II STD byte-for-byte:

```text
601c0b995d38393f05a279e07fd1f73e6cb40a0469ef14b81ca1749d2b92032b
```

Screenshots are saved under `artifacts/legacy-v3-browser/`. The external review images remain local-only. This update has not been deployed publicly.

## Defect review scope

`pipeline/audit_legacy_v3.py` uses an independent colour-science CUBE reader and tetrahedral interpolation. It examines all 238 preserved v3 LUTs against 35 photographs (5 user photographs and 30 attributed external JPEGs), with a deterministic 64 × 64 grid of actual source pixels per photo. It also checks dense 4,097-sample gray ramps and local input perturbations. This is a finite sample review, not proof about every image or the entire continuous RGB domain.

Numerical output, gray reversals, new channel boundaries, severe luminance loss and local color steps are separated in `artifacts/legacy-v3-review/report.json`. Increased chroma by itself is not classified as a defect. Thresholds are diagnostic definitions, not universal perceptual quality standards. The final investigation and limitations are recorded with that report.

## Review findings

Across the sampled pixels and gray ramps, all 238 LUTs were finite and in range. No gray reversal above 0.000001 of an 8-bit output code was found. No severe luminance-loss cases met the predefined tests: source encoded Y 16–64 falling below 4, or source Y 192–235 reaching 250 or above. These are deliberately severe diagnostic thresholds; they do not imply every tone or color is ideal.

91 combinations introduced at least one channel-boundary event among sampled pixels whose corresponding input channel was away from its boundary. The largest rate was 8.10% of the sample pixels for FUJI Velvia direct. Channel clipping is distinct from the entire RGB pixel turning black or white.

Four flagged crops were traced through the generation stages and inspected visually:

- FUJI Velvia direct: the representative blue-channel boundary was already present in the native official rendering path.
- Ektar 100 + 2393, X-Tra 400 + Ultra Endura, and C200 + Ultra Endura: some additional blue-channel compression appears after v3 lightness/neutral-color adjustment and gamut mapping. Saturated color shifts remain visible; the selected crops did not show a new discontinuous band or wholesale loss of spatial detail. Other channels still vary.
- The reproduced v3 continuous calculation matched preserved LUT grid samples within 0.0000005 per channel. This is not a file-storage or RGB-channel-order defect.

These are documented limits of particular high-chroma combinations, not grounds for automatically lowering saturation in every film. The decision for this pass is to preserve the original v3 colors and make no color-math change. Original v3 already uses lightness compensation, neutral correction and chroma scaling; preserving it does not validate those choices as a physical film match. See the detailed stage measurements and crops in `artifacts/legacy-v3-review/`.

## Further changes

Keep this original v3 baseline immutable. Any later correction needs a separately named candidate and paired comparisons on the affected photo regions. Compare hue direction and between-film chroma differences at the same paper, in addition to shadow/highlight detail and clipping. Do not normalize each film toward the same color, or infer physical accuracy from greater color separation. Paired captures of the same scene in V-Log and Standard remain unverified.
