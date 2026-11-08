# v3 Refined: preserve the look, soften its gamut boundary

This local experimental version makes an actual change to the v3 Standard LUT calculation. It retains v3's input adaptation, neutral calibration, lightness protection and chroma gain, and replaces only the last gamut-mapping operation. It does not use A/B's per-look neutral inverse. Original v3, A/B and V-Log files remain unchanged.

This is a rendering refinement, not evidence that the result matches a physical film more accurately. It deliberately retains v3's existing manual rendering policies, including neutral subtraction and lightness-related chroma gain. It does not solve every concern raised about those policies.

## What changes

The old final operation reduces out-of-gamut chroma to the maximum allowed at a fixed OKLab lightness and hue. Several different requested chroma values can end up on the same boundary. A smooth shoulder can retain some of their differences instead of immediately mapping them to one value.

Let `Cmax(L,h)` denote the first sRGB boundary reached from neutral along the fixed-lightness, fixed-hue ray, and `r=C/Cmax`. Use the same `k=0.90` for every film and every photograph:

```text
r <= k:  f(r) = r
r >  k:  f(r) = k + (1-k)*(r-k) / (r-k + 1-k)
C_out = Cmax * f(r)
```

The curve and its first derivative agree with identity at the knee. Beyond it, the derivative stays positive and the result approaches the boundary asymptotically. This is a statement about the radial chroma mapping at fixed L/h, not a claim of global smoothness across every hue slice.

Colors below 90% of the first radial boundary remain unchanged in the continuous mapper. At that boundary (`r=1`) the new chroma is 95% of the original. Compression also affects near-boundary colors that were already in gamut. Rare later in-gamut re-entry regions can receive a greater reduction; a blanket “at most 5% for every in-gamut color” would be incorrect.

The 0.90 choice is an engineering compromise, not a measured film coefficient. Pilot comparisons at 0.85, 0.90 and 0.95 evaluated channel-boundary events and preservation of differences between films. The selected value gives more separation near the boundary than 0.95 with less chroma change than 0.85. Exact results and the independent exported-CUBE review are in [the validation report](v3-refined-validation.md).

## Finding the correct boundary

Each linear sRGB channel along a fixed-L/h OKLab ray is a cubic polynomial. This geometry follows the inverse OKLab transform, discussed by its author in [sRGB gamut clipping](https://bottosson.github.io/posts/gamutclipping/). Our shoulder function and implementation are separate from the clipping algorithms in that article.

A single endpoint test and unrestricted binary search are insufficient for some blue rays: a ray can leave sRGB and then re-enter it. The implementation therefore:

1. Computes the RGB cubic coefficients along the chroma scale.
2. Finds all real derivative roots for all three channels within the search interval.
3. Sorts those critical points to partition the interval. Each channel is monotone within each partition.
4. Finds the first partition endpoint outside the RGB bounds and bisects only that interval for 24 steps.

This selects the boundary connected to neutral and cannot skip an intervening excursion through a later valid endpoint. Neutral colors and black/white endpoints have explicit branches. A regression test checks a blue re-entry case against independent polynomial roots.

## Generation and application

`pipeline/jpg_refined.py` subclasses the original `JpgToneProtection`; the parent has only an overridable `map_gamut` hook. The parent's default remains the original mapping.

`pipeline/generate_v3_refined.py` reconstructs each historical continuous rendering path. Before producing a candidate, all 35,937 original v3 grid nodes must agree with the immutable baseline within 0.000001. This prevents an unrelated engine/input change from being attributed to gamut refinement.

New files are stored separately under `public/refined-v3/`, using `####STR.cube` and `####V3R.zip`. Each ZIP contains the actual refined STD, unchanged V-Log, new interpolation QA, provenance and original rights notices. The cube retains its `#LUMIXPHOTOSTYLE STD` tag. The manifest ties every candidate to both original STD and V-Log hashes.

```sh
.venv/bin/python -m pipeline.generate_v3_refined --knee .9 --jobs 3
.venv/bin/python -m pytest pipeline/tests/test_jpg.py pipeline/tests/test_jpg_refined.py pipeline/tests/test_v3_refined_exports.py -q
npm test
npm run build
npm run verify:assets -- dist
```

The app offers the refinement as the default experimental choice alongside Legacy v3, A and B. Preview, uploaded photographs and STD download use the same selected CUBE; ZIP and QA follow that selection. V-Log is unchanged.

## Limits

- The method does not restore information clipped by the original camera, film model or official LUT.
- A 33-grid CUBE approximates the continuous transformation. Between grid nodes, interpolation can introduce small lightness/hue differences; its actual QA is reported separately.
- 8-bit quantization and cube interpolation can still produce channel endpoints. Elimination of all clipping is not promised.
- The method preserves the v3 gray tone instead of solving the full rendered-JPEG/double-tone modeling problem.
- No image statistics, per-photo correction, spatial processing, sharpening or additional exposure adjustment are used.
- Paired real-camera V-Log/Standard validation and physical film/print matching remain unverified.
