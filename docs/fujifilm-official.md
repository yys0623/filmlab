# FUJIFILM 공식 GFX LUT와 인화지 조합

> 현재 STD 입력은 [카메라별 STD→V-Log 변환](camera-std.md)을 사용합니다. 아래 B·JPG 톤 보호 설명은 변경 이력이며, V-Log 룩과 인화 모델 설명은 그대로 적용됩니다.


## 이전 STD v3 · JPG 톤 보호 — 2026-11-03

후지 90개 합성 룩의 STD는 아래 **v2 입력·인화 연결을 기반으로 계산한 뒤** `pipeline/jpg.py`의 `film-lab-jpg-tone-protection-v1`을 적용한다. 인화지를 끈 STD에도 적용한다. 원본 FUJIFILM LUT 파일과 해시는 보존하지만, **배포 STD의 대비·중성 색조는 공식 원본 그대로가 아니다.** Film Lab의 추가 JPG 렌더링 정책이다.

공통 PROVIA 입력 변환만으로 남았던 암부 구분 저하와 인화지의 들린 유색 블랙을 줄이기 위해, 각 최종 룩의 회색 4,097개 응답을 고정 기준으로 사용한다. 같은 입력 휘도의 중성 톤 변화 중 **20%**를 남기도록 보상한 뒤 원본의 OKLab L 주변으로 밝기 변화를 부드럽게 제한한다. 이 20%는 LUT 강도가 아니다. 사진별·장면별 계수는 없고, 모든 룩에 같은 정책을 적용하되 참조하는 중성 응답은 선택한 룩의 응답이다.

중성 색편향을 제거하고 sRGB 밖의 색은 밝기·색상 방향을 유지한 채 채도를 줄인다. 따라서 v2 기반 인화 모델의 검정·흰색 한계와 회색 캐스트를 최종 STD에 그대로 보존한다는 설명은 v3에 적용하지 않는다. 모델의 색 변화를 기준으로 삼지만 대비와 색역 경계의 채도는 달라질 수 있다. 정확한 계수·수식은 [README](../README.md#jpg-톤-보호-v3)와 `pipeline/jpg.py` metadata에 있다.

샘플과 업로드 미리보기 및 다운로드는 같은 새 STD LUT를 사용한다. 원본 사진·공식 원본 파일·V-Log LUT에는 이 톤 보호를 적용하지 않는다. 사진별 노출·화이트밸런스·샤픈을 쓰지 않으며 카메라 역변환, 실물 필름·인화 일치, FUJIFILM 공식 JPG 레시피로 표시하지 않는다. 원본에서 이미 손실된 디테일을 복원하지도 않는다. 실제 필름 사진 참고색 4종은 별도 변환이며 이 보호의 대상이 아니다.

아래는 공식 다운로드 근거와 v1·v2 연결의 이력을 보존한 설명이다. v2의 "기존 152개 룩 불변"과 당시 출력 범위 설명을 전체 STD v3 갱신에 대한 주장으로 사용하지 않는다.

## 공식 원본

GFX ETERNA 55의 공식 LUT 패키지 v1.10(2026-04-16)을 FUJIFILM 배포처에서 내려받았다. 그 안의 **F-Log2 / F-Gamut, 65³, 시뮬레이션 LUT v1.00 10종**을 사용한다. 패키지 버전과 개별 LUT 버전은 다르다. F-Log2C/F-GamutC 파일, WDR 및 Log-to-709 기술 변환은 이 10종에 포함하지 않는다.

- 공식 배포: https://www.fujifilm-x.com/global/support/download/lut/
- 원본 ZIP: https://dl.fujifilm-x.com/support/lut/gfx-eterna-55-3d-lut-v110.zip
- F-Log2 변환식/색역: https://dl.fujifilm-x.com/technical-data/F-Log2_DataSheet_E_Ver.1.1.pdf
- 출력 모니터 기준(13쪽): https://dl.fujifilm-x.com/support/lut/GFX_ETERNA_WhitePaper_260206_v101.pdf
- 패키지 SHA-256: `febfc7050999620651ca0cf162bf8b499970ef270b4da632765b61b958cf7940`

출처와 원본 파일별 SHA-256은 `pipeline/config/fujifilm-official.json`, 공개 미러 `public/research/fujifilm-official.json`에 기록한다. 원본 패키지는 `.cache/fujifilm-gfx/`에 보존하고 Git이나 공개 다운로드에 원본 사본을 중복 포함하지 않는다.

## 범위

CLASSIC CHROME, CLASSIC Neg., REALA ACE, PROVIA, Velvia, ASTIA, PRO Neg. Std, ETERNA, ETERNA BLEACH BYPASS, ACROS.

각 시뮬레이션마다 인화지 없는 출력 1개와 프린트 재료 8개를 제공한다. **90개 조합, STD/V-Log LUT 180개**다. 기존 152개 룩을 유지해 전체 **242개 룩, 484개 LUT, 242개 ZIP**이 된다. 프린트 재료는 사진 인화지 6종과 영화용 프린트 필름(Kodak 2383/2393) 2종이며 화면에서도 구분한다. 새 조합 번호는 201–290이다.

## 기반 입력과 출력의 계약 (v2)

공식 LUT 데이터와 원본 파일의 해시는 변경하지 않는다. 아래 **v2 입력·인화 연결**을 공식 65³ 원본의 사면체 보간과 순차 계산한 후, 최종 33³ 합성 LUT를 만든다. JPG 입력 보상은 10종 모두에 동일하게 적용하며 시뮬레이션마다 별도의 역곡선을 만들지 않는다.

- **STD:** sRGB decode → PROVIA 중성 회색 응답을 기준으로 역산한 공통 JPG 톤 보상 → 선형 sRGB를 F-Gamut(BT.2020과 같은 원색)으로 행렬 변환 → 공식 F-Log2 인코딩 → 선택한 원본 65³ LUT. 이미 완성된 JPG에 로그용 톤 처리가 겹쳐 암부가 과도하게 눌리는 현상을 줄이기 위한 입력 근사다. 10종이 같은 기준을 공유하므로 시뮬레이션 간 색·톤 차이를 따로 제거하지 않는다. Panasonic Standard나 GFX JPEG 렌더링을 역변환하는 카메라 프로파일은 아니며, 원본에서 손실된 디테일은 복원하지 않는다.
- **V-Log:** Panasonic V-Log decode → V-Gamut에서 F-Gamut으로 선형 행렬 변환 → F-Log2 encode → 같은 원본 LUT. 이미 로그 입력이므로 **STD의 JPG 톤 보상을 적용하지 않는다**. 0–1 LUT 영역 밖의 F-Log2 코드는 경계로 제한한다. 센서·화이트밸런스 차이는 교정하지 않았다.
- **공식 LUT 출력:** 공식 백서가 권장하는 BT.709 원색/D65/감마 2.2 모니터 기준으로 해석한다. `linear = encoded^2.2`로 되돌리고 최종 출력은 sRGB로 인코딩한다. BT.709 OETF나 sRGB 디코딩을 원본 출력에 대신 적용하지 않는다.

공식 LUT만 모드에도 위 입력·출력 변환은 포함된다. 배포 LUT는 원본 FUJIFILM 파일이 아니라 Film Lab 합성 파일이며, GFX 카메라에 넣을 원본 F-Log2 LUT로 표시하지 않는다. 원본은 공식 사이트에서 받는다. 사진 미리보기는 항상 STD 기준이다.

## 기반 인화지 연결 (v2)

완성된 양화 RGB를 다시 네거티브 필름 모델에 입력하면 필름이 이중으로 적용된다. 따라서 가상 디지털 프린터의 입력을 만든 후 upstream `LOG_E_PRINT`에 주입해 **printing.develop → scanning.scan_print**만 실행한다. 필름 노광·필름 현상·확대기 노광은 실행하지 않는다.

v2 인화 연결의 method ID는 `film-lab-fuji-digital-paper-bridge-v2`다. 입력과 출력은 display-linear sRGB다. 각 재료에서 다음 값을 한 번 계산하고 모든 사진과 시뮬레이션에 고정해 사용한다.

1. 중간 회색 출력이 선형 sRGB `(0.184, 0.184, 0.184)`가 되도록 3채널 기준 노출 `offset_paper`를 구한다.
2. 프로파일의 노출 영역에서 4,097개 지점과 정확한 기준 노출을 샘플링한다. 공통 노출 변화 `δ`에 대한 분광 인화 출력의 BT.709 휘도 `Y(δ)`를 얻고, 단조 PCHIP 보간으로 그 역함수 `inverseY`를 만든다.
3. 입력 `[0, 0.184, 1]`이 각각 `[재료의 도달 가능한 검정 휘도, 0.184, 재료의 도달 가능한 흰색 휘도]`를 지나는 부드러운 단조 PCHIP 목표 곡선 `target`을 만든다.
4. 각 입력 채널을 목표 휘도와 역노출 응답으로 연결한 뒤, 실제 인화지 현상·분광 스캔 계산을 실행한다.

```text
logE_c = offset_paper_c + inverseY(target(linearRGB_c))
```

이 연결은 완성된 공식 LUT 출력에 인화지의 가파른 톤 곡선이 다시 겹치는 현상을 줄인다. 채널별 출력 RGB를 강제로 목표값으로 바꾸는 방식은 아니므로 염료 간 상호작용과 회색의 색편향은 남는다. 사진별 자동 노출이나 시뮬레이션별 재보정은 하지 않는다. 목표 곡선과 RGB → 인화 노출 연결은 **Film Lab의 가상 프린터 가정**이며, FUJIFILM이나 spektrafilm 제작자가 제시한 공식 디지털 인화 레시피 또는 실측 프린터 값이 아니다.

원본 인화지의 특성 곡선·염료 스펙트럼·관찰 광원과 CAM16UCS 출력을 유지한다. 분광 스캐너를 직접 계산하며 중간 스캐너 LUT는 쓰지 않는다. 재료 고유의 검정·흰색 한계 안에서 톤을 연결하므로 인화지 없는 출력과 밝기·하이라이트 차이가 남는다. ACROS도 컬러 프린트 재료를 통과하면 약한 색조가 생길 수 있다.

초기화에 필요한 Portra 400 프로파일은 어떤 필름 단계에도 사용하지 않는다. C200으로 초기화해도 결과가 같다는 테스트로 확인한다. 각 조합의 provenance에 실제 오프셋·흑백 끝점·회색 보정 잔차·실행 단계와 `neutralCalibration`을 기록한다.

## v1에서 암부가 과하게 눌린 원인

v1의 STD 입력은 디코딩한 display-linear JPG 값을 선형 배율 1.0으로 그대로 장면 반사값처럼 사용했다. JPG에 이미 적용된 카메라 톤 위에 공식 로그용 LUT의 톤이 겹쳐, 중간 회색보다 어두운 영역이 크게 내려갈 수 있었다. 그 뒤 인화 연결의 `logE = offset_paper − 0.60 × log10(max(linearRGB, 1e−6) / 0.184)`가 인화지의 비선형 농도 응답을 더해 그림자를 추가로 눌렀다. 이 과정을 실제 인화지의 필연적인 대비로 해석하지 않는다.

v2는 이 두 연결 지점을 수정한다. JPG 단계에서는 공통 PROVIA 기준의 톤 보상을 적용하고, 인화 단계에서는 재료별 고정 역노출 응답과 제한된 목표 톤을 연결한다. 공식 LUT 원본과 기존 152개 룩은 변경하지 않는다. 시뮬레이션 자체의 강한 대비와 재료의 검정·흰색 한계까지 제거하는 보정은 아니므로, 원본과 같은 밝기나 모든 조합의 동일한 대비를 보장하지 않는다.

## 생성과 검증

```sh
.venv/bin/python -m pipeline.generate_fuji --download --jobs 2
.venv/bin/python -m pytest pipeline/tests
npm test
npm run build
npm run verify:assets -- dist
```

원본 패키지와 각 LUT의 해시가 기록된 값과 다르면 생성을 중단한다. 전체 모델의 재생성 순서는 `pipeline.generate` → `pipeline.generate_research` → `pipeline.generate_fuji --download --jobs 2`다. 새 후지 생성기는 기존 152개 레코드와 연결 자산의 무결성을 먼저 검증하고 보존한다.

테스트는 공식 F-Log2 회색 코드, 정확한 원색 행렬, 독립 colour-science LUT reader와의 일치, STD 공통 톤 보상과 V-Log 경로의 분리, 인화 노드 실행 범위, 회색의 단조성·끝점·보정, 픽셀 독립성을 확인한다. 조합별 4,350개 입력 및 사용자 사진별 1,024개 픽셀에서 최종 33³ LUT와 순차 계산을 비교한다. 이 수치는 LUT 보간 오차이며 실물 필름·GFX 실기·실제 인화의 재현 정확도가 아니다. V-Log 전체 영역의 극단적인 색과 노출에서 오차가 커질 수 있어 실험용으로 표시한다.

## 권리와 출처

FUJIFILM 원본 LUT 데이터의 권리는 FUJIFILM에 남는다. 새 합성 LUT 전체에 CC BY-SA 라이선스를 임의로 부여하지 않는다. spektrafilm 인화지·공유 도구의 Andrea Volpato 출처 및 해당 구성요소의 원래 라이선스는 유지한다. 사용자 사진은 촬영자 소유다. 실제 필름 사진을 참고해 만든 별도 4종과 이 공식 디지털 시뮬레이션 모드는 구분한다.

## 배포용 샘플 미리보기

생성기와 `public/`에는 모든 조합의 비교용 WebP를 보존한다. 정적 배포 시 새 후지 90개 조합은 `previewMode: runtime-std`로 표시하고, 중복된 미리보기 540개를 배포본에서 생략한다. 화면은 공통 샘플 원본을 sRGB 픽셀로 읽고, 다운로드용 STD LUT를 검증·압축 해제한 뒤 업로드 사진과 같은 Web Worker에서 사면체 보간으로 계산한다. 결과는 PNG이며 추가 손실 압축을 하지 않는다. LUT 값·해상도를 줄이지 않고 호스팅의 256 MiB 제한 안에 배포하기 위한 구성이다. 이 배포 전송 방식 자체는 색상값을 바꾸지 않는다. STD v3 생성에 따른 LUT·미리보기 갱신과 전송 방식은 구분한다.
