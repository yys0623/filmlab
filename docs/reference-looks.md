# 실제 필름 사진 참고색

2026-11-03. `film-lab-reference-interpretation-v1`은 실물 필름 사진을 보고 만든 **Film Lab의 독립적인 색 해석**입니다. 참고사진은 실제 필름 촬영본이고, 앱의 결과는 사용자의 디지털 사진에 LUT를 적용한 것입니다. 실물 필름과 디지털 원본의 대응 쌍으로 계측하거나 학습한 결과가 아닙니다.

## 조사와 선별

촬영자가 필름명과 실제 필름 촬영을 확인할 수 있게 설명한 자료만 채택했습니다. 필름 시뮬레이션·프리셋·LUT 출력은 제외했습니다. 실제 필름 스캔도 현상·스캐너·작업자의 색 처리 영향을 포함하므로, 명시된 내용과 미상을 구분합니다. 자동 스캔은 가공되지 않은 원본을 뜻하지 않습니다.

- Portra 400: [Ginger Lab 정상 노출 비교](https://www.thegingerlab.com/film-exposures), [mkaz 실제 필름 테스트](https://mkaz.com/articles/color-film-tests/). 깊은 암부와 선명한 유채색도 유지되는 사례로, 모든 Portra를 파스텔이나 무광 검정으로 만들지 않습니다.
- Gold 200: [David Cruz의 동일 네거티브 스캐너 비교](https://thedrunkweddingphotographer.com/summerimperfect/noritsu-vs-frontier), [mkaz 테스트](https://mkaz.com/articles/color-film-tests/). 따뜻한 유채색과 중립 흰색·푸른색이 함께 있는 경향을 참고했습니다.
- Pro 400H: [Ginger Lab](https://www.thegingerlab.com/film-exposures)의 정상 노출본을 주참고로 삼았습니다. [Richard Photo Lab 비교](https://richardphotolab.com/blogs/post/how-switch-fuji-400h-different-film)는 노출·현상이 달라 기본 계수의 목표에서 제외하고 처리 조건에 따른 변화를 확인하는 데 사용했습니다.
- C200: [Howard Xiaopeng의 2018년 실촬영](https://emulsive.org/reviews/film-reviews/film-review-kodak-colorplus-200-and-fuji-fujicolor-c200-compared), [Daniel Marinelli의 2019년 실촬영](https://emulsive.org/featured/film-review-kodak-gold-200-vs-fujicolor-c200-comparison-by-dan-marinelli). 서로 다른 촬영자이나 같은 매체이며 후보정은 미상입니다. [Carlos Garcia](https://carlosgrphoto.com/2018/11/03/fujicolor-c200-review/)와 [50mmF2](https://50mmf2.com/writings/fujifilm-fujicolor-c200-film-review)의 실제 촬영은 편차 확인에 사용했습니다. 특정 녹색·분홍 편향을 기본값으로 복사하지 않았습니다.

C200과 2022년 FUJIFILM 200 자료는 별도로 구분했습니다. 필름명이 비슷하거나 처리 과정이 유사하다는 이유로 동일 유제로 간주하지 않습니다. 참고사진 복제본은 앱·다운로드 ZIP·Git에 포함하지 않습니다.

정확한 출처·조건·판단·제조사 자료·제외 이유는 `pipeline/config/reference-looks.json`을 기준으로 하고, 같은 내용을 `public/research/reference-looks.json`, 카탈로그, 각 ZIP의 `provenance.json`에 전달합니다. 제조사 자료는 제품 특성을 확인하는 보조 자료이며 숫자 보정 계수의 출처가 아닙니다.

## 편집 방향

| 룩 | 의도한 조정 |
|---|---|
| Portra 400 | 중간 밝기를 조금 열고 피부색 주변·강한 녹색을 정리하며 파랑과 빨강 유지 |
| Gold 200 | 중간 암부 대비와 노랑·주황의 생기를 강화하되 흰색에 노란 틴트 금지 |
| Pro 400H | 주황·노랑의 강도를 낮추고 부드러운 중간톤과 약간 차가운 녹색 |
| C200 | 선명한 중간톤·파랑·자연스러운 녹색, 빨강 유지. 후보정 미상 자료 때문에 잠정 해석 |

모든 수치는 관찰을 바탕으로 정한 편집 계수입니다. 필름의 실측 특성이라고 주장하지 않습니다. 무채색 축과 검정·흰색 끝점은 유지하고, 전체 화면을 노랑·초록으로 덮거나 검정을 강제로 띄우지 않습니다. 밝기 보정은 무채색에도 적용됩니다. 피부색 주변의 선택 보정이며 얼굴을 검출하거나 피부만 분리하는 기능은 아닙니다.

## 변환 계약

STD는 encoded sRGB → linear sRGB → OKLab → 밝기의 단조 PCHIP 곡선과 부드러운 색상별 채도·각도 조정 → linear sRGB 채널 경계 제한 → sRGB 순서입니다. [OKLab 원문](https://bottosson.github.io/posts/oklab/)의 행렬을 사용합니다. near-neutral 보호와 원형 색상 경계의 연속성을 검사합니다. 색역 밖으로 나간 RGB 채널만 0–1로 제한하며, 그 경우 OKLab 명도·색상이 정확히 보존된다고 주장하지 않습니다. 현재 네 룩의 shadow/highlight tint는 모두 0입니다.

V-Log는 Panasonic V-Log를 디코딩하고 V-Gamut을 linear sRGB로 변환합니다. 각 선형 RGB 채널의 0.75부터 같은 하이라이트 압축을 적용하고 sRGB 기반의 같은 참고색으로 들어갑니다. 18.4% 중간 회색은 이 기본 변환에서 유지됩니다. 음수 채널은 0으로 제한합니다. HDR의 색상은 달라질 수 있으며 이 V-Log 기반 변환도 카메라나 필름 계측 결과는 아닙니다.

두 입력을 각각 33³ 격자에서 직접 계산합니다. STD가 V-Log 큐브를 중간에 다시 보간하지 않습니다. 출력은 full-range sRGB입니다. 종이·필름 노출/현상 모델, 그레인·할레이션·이미지별 자동 노출은 실행하지 않습니다.

## 재생성 및 검증

```bash
.venv/bin/python -m pipeline.generate_research
.venv/bin/python -m pytest pipeline/tests -q
npm test
npm run build
npm run verify:assets -- dist
```

새 룩의 파일 번호는 177–180, ID는 `<film>__reference`, 모드는 `reference_interpretation`입니다. 기존 148개 룩의 레코드와 파일 해시를 검증한 후 4개를 추가합니다. `pipeline.generate`로 기존 모델 카탈로그 전체를 다시 만든 경우 `pipeline.generate_research`를 이어 실행해야 합니다.

LUT의 off-grid 오차는 연속 색 변환과의 보간 차이입니다. 전체 도메인과 사용자 STD 사진별 4,096개 픽셀을 구분해 검사합니다. V-Log 검사는 같은 STD 값을 수식으로 V-Log에 옮긴 합성 입력도 포함하며 실제 카메라 V-Log 촬영 검증은 아닙니다. V-Log의 극단 색·노출에서는 보간 오차가 더 크므로 경고를 유지하고, 현재 사진용 내보내기의 기본값은 STD입니다. 실제 필름에 대한 재현 정확도가 아닙니다. 사용자 소유의 STD 사진 5장과 테스트 패턴에 내려받는 STD LUT를 한 번 적용해 미리보기를 생성합니다. UI·업로드·ZIP과 개별 LUT 다운로드는 같은 검증된 자산을 사용합니다.

## 1차 검증 수치

최종 STD 전체 도메인 4,350점의 최대 채널 오차 p99는 필름별 0.00545–0.00834, 최대 오차는 0.0135–0.0293입니다(출력 sRGB 0–1). 사용자 STD 사진 5장 × 4종에서 사진별 p99의 최대값은 0.00562입니다. 이는 필름 재현 정확도가 아니라 연속 변환과 33³ LUT의 차이입니다.

새 V-Log는 실험적 출력으로 표시합니다. 합성 sRGB 범위를 V-Log로 매핑한 표본에서도 p99가 0.0683–0.0875이고, 사용자 사진을 합성 V-Log로 옮긴 표본에서는 사진별 p99 최대 0.0300입니다. 실제 촬영 V-Log 검증이 아니며 고채도 경계 오차가 남아 있습니다. V-Log와 ZIP 선택 시 안내를 표시하고, 사진 비교와 기본 다운로드는 STD를 사용합니다.
