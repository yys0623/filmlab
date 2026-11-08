# 2026-11-04 실촬영 갤러리

사용자가 제공한 `261104_film` 폴더의 JPG 124장을 EXIF로 분류했습니다. 모두 Panasonic DC-S1M2 / LUMIX S1II, `Standard or Custom` 포토스타일, sRGB 촬영본입니다. 이후 사용자 요청으로 `P1503810.JPG`, `P1503811.JPG`, `P1503812.JPG`를 제외하여 갤러리 108장과 STD 입력 13장을 사용합니다. 세 파일의 원본 JPG는 보존합니다. 실제 감광 필름을 현상한 사진이 아니라 카메라에서 필름 룩 LUT를 적용한 디지털 촬영본입니다.

## 분류와 연결

| EXIF의 LUT1 이름 | 사진 수 | 필름 | 앱의 추천 출력 |
|---|---:|---|---|
| Fujifilm C200 Alchemy TEST.cube | 22 | Fujifilm C200 | Fujifilm Crystal Archive Type II |
| Kodak Gold 200.cube | 23 | Kodak Gold 200 | Kodak Portra Endura (촬영 당시 추천) |
| Kodak Ektar 100 .cube | 21 | Kodak Ektar 100 | Kodak Portra Endura |
| Kodak Vision3 200T.cube | 21 | Kodak Vision3 200T | Kodak Vision 2383 |
| Fujifilm Velvia 100.cube | 21 | Fujifilm Velvia 100 | 슬라이드 직접 스캔 · 인화지 없음 |
| 빈 이름, LUT1/2 강도 0 | 13 | 기본 Standard | 스튜디오 입력 샘플 |

갤러리 108장은 LUT1 강도 100%, LUT2 강도 0%입니다. STD 입력 13장은 두 LUT의 이름이 비어 있고 강도가 모두 0이며, EXIF의 Contrast/Saturation/Sharpness는 Normal입니다.

필름은 EXIF에 기록된 LUT 파일명으로 식별했습니다. EXIF에 인화지명이나 LUT 전체 데이터가 들어 있는 것은 아닙니다. 인화지 연결은 “웹앱 추천 인화지로 촬영했다”는 사용자 설명과 현재 카탈로그의 `recommendedPrint`를 근거로 합니다. 이후 Gold 200의 추천 인화지는 Ektacolor Edge로 바뀌었지만, 갤러리는 실제 촬영한 Portra Endura 조합을 그대로 유지합니다(`recommendedAtCapture`). Velvia 100은 슬라이드이므로 카탈로그의 직접 스캔 조합을 연결합니다. 파일명만으로 카메라에 들어간 LUT의 바이트가 현재 다운로드와 같다는 점까지 검증할 수는 없습니다.

## 화면 동작

- 갤러리는 촬영된 결과를 그대로 표시합니다. 필터를 바꿔도 사진의 색을 다시 계산하지 않습니다.
- 확대 보기에서 촬영 파일명, 카메라와 노출, LUT 이름과 해당 필름·인화지 조합을 확인합니다.
- 해당 룩을 스튜디오에서 선택하면 LUT OFF STD 샘플에 적용합니다. 갤러리 사진에 LUT를 중복 적용하지 않습니다.
- STD 13장이 기존 사진 샘플을 대체합니다. 기술 테스트 차트는 별도의 합성 입력으로 유지합니다.
- 비슷한 장면이라도 구도·노출·촬영 시각이 다르므로 갤러리와 STD 사진을 동일 조건의 전후 비교라고 표시하지 않습니다.

## 파일과 재현

원본 JPG는 수정하지 않습니다. 웹용 파생본은 방향과 색 프로파일을 반영하고, 확대 이미지와 작은 썸네일로 준비합니다. 별도의 색 보정이나 LUT는 적용하지 않습니다. 공개 파생 이미지에서 EXIF를 제거하고, manifest에는 표시와 분류에 필요한 촬영 정보만 기록합니다. GPS, 장치 일련번호와 원본의 절대 경로는 공개하지 않습니다.

- 원본 EXIF 조사 기록: `artifacts/gallery-261104/exif-private.json` (개발용, 서비스·배포 소스 패키지 제외).
- 기존 샘플: `artifacts/gallery-261104/previous-samples/`에 보존.
- STD 기준 데이터: `assets/samples/manifest.json`, `public/samples/manifest.json` 및 `public/catalog.json`의 `samples`.
- 갤러리 기준 데이터: `public/gallery/manifest.json`.
- 가져오기 스크립트: `pipeline/import_user_gallery.py`.

```sh
.venv/bin/python -m pipeline.import_user_gallery --source /path/to/261104_film --jobs 4
```

갤러리 확대본은 긴 변 최대 2,400px / WebP quality 92, STD 입력은 최대 1,920px / quality 95, 썸네일은 최대 480px / quality 85로 준비합니다. 축소·재압축에 따른 차이가 있으므로 원본 JPG와 픽셀 단위 무손실 복제라고 해석하지 않습니다.

사진의 권리는 촬영자에게 있습니다. 코드·LUT의 오픈소스 라이선스가 사진에 적용되는 것은 아닙니다. 이번 작업은 로컬 앱과 배포용 자산 준비이며 공개 배포 실행과는 별개입니다.
