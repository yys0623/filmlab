# sosang

필름·인화지와 사용자 제공 후지 필름 시뮬레이션을 비교하고 LUMIX용 LUT를 내려받는 React + TypeScript + Vite 앱입니다. 한국어·영어 UI, 카메라 선택, 내 사진 업로드, 원본/적용 비교와 카메라에서 LUT를 적용해 촬영한 사진 갤러리를 제공합니다.

## 현재 색 변환

STD는 **기종별 Panasonic Standard → V-Log/V-Gamut 변환 → 기존 V-Log 룩**을 하나의 33³ LUT로 합성합니다. V-Log Alchemy `e51ba9a23458ff5c316f630b860eb0201139d126`의 모델별 변환을 고정해 사용합니다. 기본 카메라는 **S1II / DC-S1M2**입니다. 이전 STD B 선행 커브는 현행 생성 경로에 사용하지 않습니다.

148개 필름·인화지/스캔 룩에 10개 카메라의 STD 변환을 제공합니다. 기존 V-Log 148개, STD 1,480개, 카메라별 ZIP 1,480개를 유지합니다. 이전 공식 후지 90조합은 제거했습니다. 별도로 사용자 제공 후지 STD LUT 9종을 RGB 값 변경 없이 S1II용으로 제공하며, 이 9종에는 인화지·Alchemy·V-Log 변환을 추가하지 않습니다. [후지 LUT 출처와 처리](docs/supplied-fuji.md)

지원 목록: GH6, S5II, S5IIX, G9II, GH7, S9, S1IIE, S1RII, S1II, DC-L10. GH6는 후반 작업용입니다. **구형 DMC-L10은 지원하지 않습니다.** 새 DC-L10과 같은 카메라로 취급하거나 다른 기종의 LUT로 대체하지 않습니다.

각 STD의 계약은 `C_camera(x) = L_VLOG(A_camera(x))`입니다. 변환 LUT는 trilinear, V-Log 룩은 tetrahedral 보간으로 평가하고 33³로 기록합니다. 브라우저는 이 다운로드 파일에 tetrahedral 보간을 한 번 적용합니다. 별도의 sRGB→V-Log 공식, B 커브, 채도 게인, 사진별 자동 보정은 추가하지 않습니다.

[C200 실기 확인과 구현·검증 한계](docs/camera-std.md), [실기 비교 절차](docs/camera-checklist.md), [검증 기록](docs/validation.md)을 참고하세요.

## 필름 색 남김 (실험)

인화지 인화 룩에는 선택형 변형이 있습니다. 필름별 중립 인화 필터를 고정 기준 필터(같은 인화지의 Portra 400)와 섞어서 필름 고유의 색 기운을 남깁니다. 필터를 0 쪽으로 줄이는 방식이 아니라서 전체가 주황으로 틀어지지 않습니다. 강도는 18% 회색의 CIELAB 채도로 필름마다 맞추고, 남는 색이 마젠타인 조합은 제공하지 않습니다. 기본 룩 148개는 그대로이며 변형은 번호 +1000, 파일명 `FC`로 구분합니다. [방식과 한계](docs/film-cast.md)

## 인화 필터 미세 조정 (실험)

인화 룩에서 spektrafilm GUI의 Print M·Y filter shift를 슬라이더(±30 CC)로 조절할 수 있습니다. 인화지 노출 지점에서 LUT를 나눠 9개 필터 위치로 미리 굽고, 브라우저가 그 사이를 보간해 선택한 카메라의 33³ STD·V-Log 큐브를 바로 만듭니다. 0/0이면 기존 LUT를 그대로 씁니다. [방식과 정확도](docs/print-timing.md)

## 사용

필름과 인화지를 고르고 **LUT 내보내기에서 카메라를 선택**합니다. 기본 제공 사진은 2026-11-04 사용자가 촬영한 S1II Standard / LUT OFF 13장입니다. 샘플 미리보기는 내보내기 기종과 독립적으로 S1II를 유지합니다. 업로드 사진은 내보내기에서 고른 촬영 기종의 STD LUT를 적용합니다. 후지 제공 LUT는 S1II만 선택할 수 있습니다. 일반 sRGB 이미지나 다른 Photo Style에 적용한 결과는 카메라 변환의 정확도 검증으로 해석하지 않습니다.

갤러리에는 [기존 실촬영 108장](docs/gallery-261104.md)과 [추천 조합 270장](docs/gallery-recommended.md)이 별도 탭으로 있습니다. 사진에 LUT를 다시 적용하지 않습니다. 기존 컬렉션은 EXIF의 필름명과 촬영자가 확인한 인화지를 표시하고, 추천 조합 컬렉션은 카메라에 기록된 LUT 파일명에서 필름·인화지·현상 방식까지 확인합니다. 각 사진을 확대해 촬영 정보를 확인하거나 해당 조합을 스튜디오에서 열 수 있습니다.

- STD 다운로드: 선택한 카메라의 합성 LUT. 카메라에서는 LUT1에 100%로 적용하고 LUT2는 끕니다.
- V-Log 다운로드: 엔진 룩의 모든 기종이 공유하는 V-Log/V-Gamut 입력 룩. 제공 후지 9종은 STD 단일 파일만 있습니다.
- ZIP 다운로드: 선택한 기종의 STD와 V-Log 두 파일, 생성 정보, 수치 QA, 권리 안내.
- 개별 다운로드 이름: 필름명 + 인화지/출력명 + 카메라/입력 구분. ZIP 안에는 FAT32에 사용할 수 있는 짧은 이름을 사용합니다.

내 사진은 JPG/PNG/WebP, 최대 30 MB·8,000만 화소를 지원합니다. EXIF 방향을 반영한 sRGB canvas에서 긴 변 최대 2,048px로 처리하며 서버에 전송하지 않습니다. 파일별 크기·SHA-256을 검증하고 Web Worker에서 미리보기를 계산합니다. 사진의 LUT OFF 여부는 자동 검증하지 않습니다.

## 개발 실행

```sh
npm install
npm run dev -- --port 4418
npm test
npm run build
npm run verify:assets
```

Node.js 22.12 이상이 필요합니다. `scripts/run-web.mjs`는 지원되는 로컬 Node를 선택합니다. 개발 서버는 127.0.0.1에만 바인딩됩니다.

Python 엔진은 spektrafilm 0.3.4, commit `3bb2c2d2801ff68b92019cf1dbcbb133d60832bc`에 고정됩니다. `pipeline/requirements.lock`은 검증한 macOS 의존성을 기록합니다. 기존 `.venv`를 사용하거나 `python3 scripts/bootstrap.py`로 준비합니다. 현행 카메라 STD 생성 명령과 구조는 [카메라 STD 문서](docs/camera-std.md)에 기록합니다. `pipeline/precurve.py`, `generate_precurve.py`, `jpg.py`, 이전 감사 스크립트는 과거 연구 기록이며 현행 서비스 생성 명령으로 사용하지 않습니다.

## 배포

```sh
npm run build:cloudflare
npm run preview:cloudflare -- --port 4419
npm run deploy:cloudflare
```

기본 배포 대상은 `wrangler.jsonc`의 `sosang` Worker이며 공개 주소는 **https://sosang.film-lab-jc.workers.dev/**입니다. 기존 `https://film-lab.film-lab-jc.workers.dev/`의 홈페이지 접속은 새 주소로 이동합니다. 기존 탭과 직접 연결한 파일 링크가 계속 동작하도록 구주소의 정적 자산과 `/api/locale`은 유지합니다. 구주소 운영은 `wrangler.legacy.jsonc`로 분리하며, 새 주소 검증 후 별도로 배포합니다. [주소 이전과 배포 순서](docs/cloudflare.md#주소-이전과-구주소-유지)

빌드와 배포는 별도 단계입니다. 카메라별 ZIP을 정적 자산으로 제공하며, 선택한 조합만 요청합니다. 브라우저는 ZIP과 내부 CUBE의 해시를 각각 검증하고 무손실 압축 해제합니다. 기본 기종의 개발용 raw CUBE 사본은 production에서 ZIP 참조로 바뀌며 색 데이터는 바뀌지 않습니다.

Cloudflare의 `/api/locale`은 한국 접속에 한국어, 그 밖의 국가에 영어를 선택합니다. 수동 언어 선택이 우선하며, 위치 정보가 없으면 브라우저 언어를 사용합니다. [배포 문서](docs/cloudflare.md)

이전 사용자 샘플과 외부 리뷰 사진은 서비스 경로 밖의 개발 아카이브로 옮겼습니다. 현재 사용자 STD 사진과 기술 차트는 `public/samples/manifest.json`, 기존 실촬영은 `public/gallery/manifest.json`, 추천 조합은 `public/gallery/recommended/manifest.json`에 있습니다. 지정된 사진의 웹용 파생본만 앱에 포함하며 원본은 변경하지 않습니다.

## 자료와 권리

- 원본 엔진: [spektrafilm](https://github.com/andreavolpato/spektrafilm). 엔진·프로파일의 권리 문서를 보존합니다.
- 카메라 입력 변환: [V-Log Alchemy](https://github.com/shenmintao/V-Log-Alchemy/tree/e51ba9a23458ff5c316f630b860eb0201139d126), Apache-2.0. 출처, 고정 commit, 원본·결과 해시, 합성 변경 고지를 기록합니다.
- 과거 FUJIFILM 공식 LUT: [출처와 합성 계약](docs/fujifilm-official.md). 공식 데이터의 권리는 FUJIFILM에 있으며 입력/인화 연결은 Film Lab의 변환입니다.
- 사용자 사진의 권리는 촬영자에게 있습니다. 코드나 LUT 라이선스를 사진에 적용하지 않습니다.

배포 소스 패키지는 `scripts/package-source.mjs`의 허용 목록으로 만들며 인증 정보·개인 사진·개발 아카이브는 포함하지 않습니다. 수치 QA는 보간·파일 일관성 검사이며 실제 필름, 인화, 카메라 색의 완전한 재현을 보증하지 않습니다.
