# STD A/B single-tone precurve: contract and independent validation

> Historical study. Current STD delivery uses the model-specific V-Log Alchemy adapter; see [camera STD](camera-std.md). The measurements below describe the former implementation.

The new STD mapping uses the already exported, immutable VLOG CUBE as its colour renderer. It replaces the previous display-referred `JpgToneProtection` policy. It is an explicit Film Lab working model for rendered Standard/sRGB JPEGs, **not** an official Panasonic Standard inverse, a measured camera calibration, or proof of physical film/paper accuracy.

## Full 238-combination interpolation summary

**The four independently re-evaluated combinations below are not the full catalog.** Across all 238 active combinations, some 33³ LUT interpolation errors exceed the review threshold. This table aggregates each generated `qa.json` after SHA256 verification against the catalog; it is not an independent re-evaluation of all 238 engines. Four archived reference combinations are excluded.

| Variant | Random p99 >0.02 | Worst random p99 | Worst random maximum | Photo p99 >0.02 combinations | Worst photo p99 |
|---|---:|---:|---:|---:|---:|
| A | 26 / 238 | 0.053306 | 0.133360 | 7 / 238 | 0.036642 |
| B | 12 / 238 | 0.055727 | 0.153746 | 13 / 238 | 0.053820 |

The worst cases are:

- A random p99: `gfx_velvia__kodak_2393` (0.053306); largest individual random error: `gfx_velvia__official_direct` (0.133360).
- A photo p99: `kodak_portra_800_push2__kodak_endura_premier` / `std_playground` (0.036642).
- B random p99: `gfx_velvia__kodak_2393` (0.055727); largest individual random error: `gfx_velvia__kodak_2393` (0.153746).
- B photo p99: `kodak_portra_800_push2__kodak_ultra_endura` / `std_playground_panel` (0.053820).

Full-catalog QA uses 4,350 synthetic samples per combination (4,096 random +129 gray +125 grid) and 1,024 fixed sampled pixels per photo. The independent representative audit uses 4,225 synthetic samples and a full-image stride for photos. These are different sample sets; their p99 values need not match.

The complete warning IDs and per-combination records are in `public/audit/std-precurve/all-combinations-summary.json` and in `report.json` → `allCatalogQaSummary`. The HTML shows the whole-catalog summary before the four representative photo comparisons, with expandable warning tables.

**33³ compatibility is retained.** The generation and files satisfy the selected mapping, but high-curvature colour/gamut boundaries can produce materially larger interpolation errors between nodes. The result must not be described as “all interpolation checks passed.” No LUT resolution or colour-engine changes were made for this reporting update.

The root integration run passed **219 Python tests and 43 JavaScript tests**. File verification covered **722 public CUBEs** (including eight legacy files for four archived reference combinations) and **714 visible CUBEs** (238 × VLOG/A/B). These code and file-integrity results are distinct from the interpolation-warning counts above. They do not establish physical film/paper accuracy or camera calibration.

## Fixed transform

Let `D` and `E` be sRGB decoding and encoding. With the published Panasonic matrix coefficients already used by the project:

```
F(x) = VLogEncode(D(x) @ sRGB_to_VGamut.T)
R(x) = exported_VLOG_CUBE(F(x))
N(g) = E(0.2126 D(R(g,g,g).R)
       + 0.7152 D(R(g,g,g).G)
       + 0.0722 D(R(g,g,g).B))
STD_v(x) = R(P(T_v(x)))
```

`N` is sampled at 4097 uniformly spaced encoded gray inputs. `P` is a piecewise-linear generalized inverse of its cumulative maximum. The same scalar `T` and `P` are applied separately to all three encoded input channels. Output RGB from `R` is returned unchanged. There is no new saturation gain, neutral-cast subtraction, OKLab lightness constraint, tanh compression, tone-retention blend, or output gamut remapping. Any compression/clipping already baked into the VLOG source remains.

The selected VLOG CUBE is the numerical reference. Earlier native continuous-engine and Fuji STD paths are different references; agreement with them is not the new STD accuracy criterion. The audit includes a separate continuous-native gray comparison for the three physical-model combinations to disclose source CUBE interpolation differences.

## A: preserve the model's attainable endpoint range

Let `b=Y(R(0,0,0))`, `w=Y(R(1,1,1))`, with linear-light luminance `Y`. Then:

```
T_A(x) = E(b + (w-b) D(x))
```

This preserves relative **linear-light** tone within the model's reachable black/white range. It does not stretch that output range back to 0 and 1. Neutral output remains coloured if the source is coloured. These endpoints describe this declared input domain; they are not measured paper Dmin/Dmax and also apply to direct-film scans without paper.

The intended neutral A result is linear `Y = b + (w-b) D(x)`, subject to 4097-point neutral sampling and the final 33³ CUBE. Strict floating-point increase near the endpoints and 8-bit visible level count are separate measurements. An increasing float curve can contain repeated 8-bit codes.

## B: fixed 18% gray and one derived highlight parameter

For linear channel `y=D(x)`, `m=0.18`:

```
                 y                                  y <= m
T_B_linear(y) = {
                 m + (y-m)/(1+k (y-m)/(1-m))          y > m

k = (1-w)/(w-m)
T_B(x) = E(T_B_linear(D(x)))
```

`k` is determined from the source endpoint; it is not a visually fitted knob. For `m<w<=1`, the upper branch has `T(m)=m`, `T'(m)=1`, `T(1)=w`, and positive derivative
`1/(1+k(y-m)/(1-m))²`. The identity/shoulder join is C1, not generally C2. A combination with `w<=m` cannot satisfy this contract and is rejected.

True linear 18% encodes to **117.645813 / 255**. Integer code 118 is its 8-bit approximation, whose decoded linear value is 0.181164244.

B preserves the identity target below middle gray, but the inverse domain begins at `E(b)`. Values below that floor clamp to source input zero. Thus B cannot preserve detail below the source's nonzero black floor. The “strict endpoint detail” condition belongs to A and cannot simultaneously be imposed on B with this floor and a highlight-only target.

## Plateaus and monotonicity

`maximum.accumulate` makes N nondecreasing, not necessarily strictly increasing. Plateaus have no unique classical inverse. The implementation inverts each rising segment from the **last** occurrence of the lower plateau to the **first** occurrence of the next level. Exact black/white use source endpoints 0/1. It does not insert epsilon slopes or invent lost detail.

Overwriting the final plateau's first input with 1 inside a normal interpolation table would distort the immediately preceding inverse segment. The analogous start-plateau problem also matters. These cases were identified in review and corrected before generation; an independent round-trip counterexample test covers a long black and white plateau.

The report records decreases, plateau steps, maximum monotonic correction and inverse residual. If the real source N decreases, exact inversion of original N and monotone P cannot both be claimed: the correction changes the target reference. No endpoint success may conceal this change.

## What “equal tone” can verify

The proposed identity `new(x) = R(P(x))` omits T. It cannot hold in general for A, nor for B wherever a channel enters the highlight shoulder. Selecting pixels by OKLab L 0.35–0.85 does not resolve the mismatch: a saturated midtone pixel may have one channel above the knee.

The correct implementation check is **full RGB equality with `R(P(T_v(x)))`**, allowing 33³ CUBE interpolation/serialization error. That test catches extra output colour edits as well as formula mistakes.

A separate colour diagnostic holds the **metric's** lightness coordinate equal and compares OKLab a,b. The report calls `100*norm(Δa,Δb)` “iso-L chroma delta”; this is not CIE ΔE00, and no display images are altered to produce it. It also reports full `100*norm(ΔL,Δa,Δb)` and ΔL, so differences in rendering tone remain visible. Midtone pixels are selected once from original OKLab L 0.35–0.85. Chroma ratios exclude original C<=0.02 to avoid meaningless huge ratios around gray. Positive and negative chroma changes are reported separately rather than assuming all pixels become more saturated. A further direction test compares `(old_ab-source_ab) dot (new_ab-source_ab) < 0`, excluding pixels unless **both** vector lengths are at least 0.005 OKLab. Its percentage uses only that explicitly reported eligible subset; it is not a universal hue reversal claim.

Neutral red-minus-blue comparisons use source-renderer input **`P(T_v(g))`**. Comparing with `R(g)` at the original g would conflate changing the operating exposure with removing a cast. An RGB-shared nonlinear precurve can change coloured-channel ratios and therefore hue/chroma; a neutral-luminance inverse is not a full 3D inverse or a claim of pure luminance-only editing.

## Independent audit and reproducibility

Run after generating A/B assets:

```sh
.venv/bin/python -m pipeline.audit_precurve
```

The audit reads baseline hashes from `artifacts/std-precurve-baseline/catalog.json`, validates saved legacy STD CUBEs, and verifies VLOG hashes are unchanged. It uses **colour-science's CUBE reader and tetrahedral interpolation**, independently spells out F/N/P/T, and treats `SingleTonePrecurve` as an implementation under test. The app JavaScript is not used to manufacture expected values.

It checks Portra 400/Portra Endura, C200/Crystal Archive Type II, Velvia 100 direct scan, and Classic Chrome/Crystal Archive Type II. The public report contains:

- Original gray, unprotected continuous/native and exported-VLOG gray, legacy v3, A and B tables.
- Exported CUBE grid-node, deterministic off-grid and five real-photo errors against the independent same-T reference.
- Neutral source endpoints/casts, dense float monotonicity and separately quantized 8-bit levels.
- Per-photo and aggregate full/iso-L colour statistics and stable chroma-ratio quantiles.
- Same-image comparisons without per-image fitting or automatic exposure.
- SHA256 provenance for the inspected source, old and new LUTs and public sample files.

Generated report: `public/audit/std-precurve/index.html`; machine-readable measurements: `report.json` in the same folder. Images use small derivatives of already-public samples, with an sRGB ICC profile. No personal full-resolution originals are added.

## Limits of the conclusion

An exact match to this model proves implementation consistency, not that its camera approximation is measured or that its colours reproduce a particular physical film/print. Removing the earlier JPG protection also intentionally removes its neutral-cast and coloured-shadow lightness guarantees. Native colour casts return. The change is appropriate to the explicitly requested source-renderer-preserving contract; it is not evidence that every photograph will have better shadows.

The outstanding empirical validation is paired capture of the same scene under controlled exposure and white balance: **V-Log + unchanged VLOG LUT versus Standard + new STD A/B LUT**. Camera preprocessing, clipping and its LUT interpolation are not characterized by these desktop calculations.

## Measured representative results

These measurements use the four regenerated A/B CUBEs, five public Standard photographs and the preserved v3 baseline. They are measurements of this set, not universal film characteristics.

| Combination | A off-grid p99 / max | B off-grid p99 / max | Worst photo p99 A / B |
|---|---:|---:|---:|
| Kodak Portra 400 + Kodak Professional Portra Endura | 0.00493 / 0.01036 | 0.00872 / 0.02085 | 0.00353 / 0.00728 |
| Fujifilm C200 + Fujifilm Crystal Archive Type II | 0.00692 / 0.01575 | 0.00943 / 0.02381 | 0.00692 / 0.00875 |
| Fujifilm Velvia 100 + Direct scan | 0.01428 / 0.02906 | 0.01211 / 0.02421 | 0.01099 / 0.01184 |
| Fujifilm CLASSIC CHROME + Fujifilm Crystal Archive Type II | 0.02184 / 0.05188 | 0.01966 / 0.05498 | 0.00559 / 0.00811 |

RGB errors are the largest absolute encoded sRGB channel difference (0–1) per pixel. All 33³ grid nodes match independent reference rounding within 0.0000005; production class agreement is within 1.1e-15. Random sampling is 4096 uniform RGB values plus 129 grays, a different sample set from generation QA. **Classic Chrome A p99 exceeds 0.02** in this independent set; no blanket “all interpolation checks passed” claim is made. All representative photograph p99 values are below 0.012, with rare larger errors still included in the JSON.

The continuous native 256-code gray check itself has small reversals: Portra has one negative step (minimum linear-Y step −1.388e−6) and Velvia has two (−7.193e−7); C200 has none. The selected exported-VLOG neutral responses have no reversal or plateau on 4097 samples in these four combinations. These are different numerical references, so native behavior is not retroactively claimed to be strictly monotonic.

All four A dense gray curves have positive float steps. B has an intentional source-black floor; its 33³ CUBE softens the boundary across a grid cell. Thus even the location/width of the flat part differs slightly between the analytic reference and exported interpolation. The output range contains only 185–211 distinct rounded encoded-Y levels on 4097 probes; these 8-bit plateaus do not imply a float reversal.

| Combination | v3 C/source median | A C/source median | B C/source median | Mean ΔL A / B |
|---|---:|---:|---:|---:|
| Kodak Portra 400 + Kodak Professional Portra Endura | 1.174 | 0.821 | 0.927 | -0.0762 / -0.0081 |
| Fujifilm C200 + Fujifilm Crystal Archive Type II | 1.331 | 0.883 | 0.993 | -0.0673 / -0.0060 |
| Fujifilm Velvia 100 + Direct scan | 1.233 | 0.867 | 0.949 | -0.0782 / -0.0070 |
| Fujifilm CLASSIC CHROME + Fujifilm Crystal Archive Type II | 0.975 | 0.609 | 0.733 | -0.1029 / -0.0132 |

The prior claim of a universal 15–30% chroma increase is not supported: representative v3 medians range from 0.975 to 1.331. The new A/B precurves reduce median chroma on these images, including when comparing a,b at equal metric L, despite having no explicit saturation control. This follows from selecting different renderer inputs and retaining source casts. Per-photo direction counts and full/iso-L deltas are in the report.

The prior Portra input-gray 44→about 23 statement is reproducible: continuous native output is 22.8497, exported-VLOG composition is 23.0957. Independent precurve A gives 38.9203 and B gives 44.0000 before final CUBE interpolation. At input code 118, A gives 96.8048 while B gives 117.9996. A therefore should not be presented as maintaining original middle-gray brightness: its narrower native output range is intentional.

## Validation 4: real browser output versus the actual download

For Classic Chrome + Crystal Archive Type II, the browser was given `std_figures.webp` (1024×683, 699,392 pixels). Actual on-screen A/B blob PNGs were saved. The actually downloaded `0202STD.cube` / `0202STB.cube` files were then read with colour-science and independently applied with tetrahedral interpolation to the uploaded source. Both downloads matched their catalog SHA256 values.

| Variant | RGB pixels | Exact RGB pixels | Maximum byte error | Download SHA matches catalog |
|---|---:|---:|---:|---|
| A | 699,392 | 100% | 0 | yes |
| B | 699,392 | 100% | 0 | yes |

The saved evidence is `artifacts/std-precurve-browser/independent-pixel-check.json`; its content and SHA256 are included in the public report's `validation4BrowserPixelAgreement` field. This evidence comes from the separate real-browser check, not from regenerating expected PNGs with the app implementation. Its scope is this one combination and uploaded photo. It does not prove every browser, device, photograph or camera behaves identically.

## Measured direction changes

The old/new direction test is nonzero for every representative combination. This means the new precurve changes the direction of some colour changes relative to the source; it does not establish which version is physically correct. Percentages below apply only to the eligible subset where both old and new Δab lengths exceed 0.005 OKLab.

| Combination | A eligible / midtones | A opposed among eligible | B eligible / midtones | B opposed among eligible |
|---|---:|---:|---:|---:|
| Kodak Portra 400 + Kodak Professional Portra Endura | 29.72% | 41.64% | 27.04% | 16.37% |
| Fujifilm C200 + Fujifilm Crystal Archive Type II | 29.91% | 55.73% | 29.56% | 25.19% |
| Fujifilm Velvia 100 + Direct scan | 27.18% | 71.35% | 21.64% | 46.28% |
| Fujifilm CLASSIC CHROME + Fujifilm Crystal Archive Type II | 35.47% | 25.20% | 34.34% | 14.28% |

Final independent report SHA reference matches the completed 238-combination catalog. The report includes the exact requested gray inputs `[0,10,20,30,44,60,89,118,150,180,225,255]` and separate cast probes `[20,44,89,118,180]`.
