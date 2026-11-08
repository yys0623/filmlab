# 슬라이드 직접 스캔 — 2026-11-02

> 현재 STD 입력은 [카메라별 STD→V-Log 변환](camera-std.md)을 사용합니다. 아래 B·JPG 톤 보호 설명은 변경 이력이며, V-Log 룩과 인화 모델 설명은 그대로 적용됩니다.


## 이전 STD v3 · JPG 톤 보호 — 2026-11-03

Provia 100F·Velvia 100·Ektachrome 100·Kodachrome 64의 STD는 아래 v2 직접 스캔 계산 뒤에 `pipeline/jpg.py`의 `film-lab-jpg-tone-protection-v1`을 적용한다. 인화지를 추가하지 않으며, 슬라이드 모델의 강한 암부 응답이 이미 완성된 JPG에 다시 겹치는 것을 줄인다.

각 룩의 회색 4,097개에서 얻은 고정 중성 응답으로 톤을 보상한다. **중성 톤 변화의 20%**를 남기고 원본 OKLab L에서 벗어나는 폭을 부드럽게 제한한다. 같은 밝기의 중성 색편향을 제거하고 색역 밖에서는 밝기·색상 방향을 유지하며 채도를 줄인다. 20%는 LUT 적용 강도가 아니다. 샘플·내 사진·다운로드는 완성된 STD LUT를 100% 적용한다.

원본 사진과 V-Log는 이 STD 보호를 적용하지 않는다. 사진별 노출·화이트밸런스·샤픈은 사용하지 않는다. 기반 슬라이드의 대비·색편향을 그대로 전달하는 결과가 아니며, 실제 필름·실측 스캐너와 일치하거나 원본에서 잃은 디테일을 복원한다고 주장하지 않는다. UI는 **BETA 0.6 · JPG 톤 보호**로 표시한다. 공통 수식은 [README](../README.md#jpg-톤-보호-v3)에 있다.

아래는 최초 슬라이드 지원과 STD v2의 구현 이력이다. 당시 조합 수와 바이트 보존·오차 수치는 현재 STD v3의 검증 수치를 대체하지 않는다.

요구사항은 ChatGPT 「프로젝트 확인 요약」의 최신 변경 설명에서 확인했다. 업데이트된 MD의 Library 링크는 로그인 화면으로 연결되어 첨부 원문 전체를 내려받지는 못했다. 기존 로컬 명세와 채팅에 명시된 아래 변경 내용을 구현했다.

- 네거티브: 필름 현상 → 인화지 인화 → 스캔.
- 슬라이드: 필름 현상 → 필름 직접 스캔. 인화지 선택 비활성화.
- 두 경로 모두 V-Log/STD LUT, 샘플 및 업로드 사진 미리보기 제공.

## 엔진

고정된 upstream 0.3.4, commit `3bb2c2d2801ff68b92019cf1dbcbb133d60832bc`의 GUI는 positive 필름 선택 시 `io.scan_film=True`를 설정한다. 런타임은 이 플래그에 따라 `printing.expose`, `printing.develop`를 건너뛰고 `CMY_FILM → RGB_OUT` 스캔을 실행한다. 원본 LUT builder와 QA factory는 이 플래그를 설정하지 않으므로 앱의 `pipeline/slide.py`가 두 경로를 보완한다. vendor 파일은 수정하지 않는다.

`SlideBundleBuilder`는 기존 1-LUT 격자 생성·색공간 처리·인코딩을 재사용하며, 런타임 초기화 전에 `scan_film=True`를 설정한다. 네거티브에는 기존 upstream builder를 그대로 사용한다. 슬라이드의 QA는 builder와 분리된 런타임 초기화에서 같은 직접 스캔 경로를 실행한다.

원본 런타임은 초기화 시 인화지 객체를 요구하므로 내부적으로 Portra Endura 프로파일을 로드한다. 인화 단계는 실행하지 않으며 슬라이드 결과의 `paper`는 `null`이다. 이 초기화 의존성은 provenance의 `runtimeInitPrintProfile`에 이름과 해시로 기록하고, 실제 선택된 인화지로 표시하지 않는다. Crystal Archive로 초기화해도 같은 픽셀 결과가 나오는 것을 4종 모두 검사한다.

## STD 생성 v2 (이력)

슬라이드도 네거티브와 같은 STD v2 입력 계약을 사용한다. sRGB 33³ 격자를 선형광으로 디코딩하고 V-Gamut으로 변환한 뒤, `scan_film=True` 연속 엔진을 직접 계산한다. 중간 V-Log LUT의 보간을 제거하며, 인화 단계는 계속 우회한다. 기본 입력 배율 1.0배를 유지하고, 추가 노출·채도 보정은 적용하지 않는다. V-Log 생성 방식은 유지한다.

v2의 STD 오차는 `qa.stdVsDirectEngine`에서 최종 파일과 독립 오프그리드 연속 엔진을 비교한다. 기존 `STD ↔ 연속 합성` 수치는 v1 이력이며 직접 엔진 정확도의 근거로 쓰지 않는다. v2 JSON의 `stdVsContinuousComposition`은 새 STD와 이전 V-Log LUT 합성 경로의 차이를 보여 주는 진단값으로만 남긴다. 당시 표시는 `STD 근사 · 기본 노출`로 통일했다. 이는 카메라 Standard 렌더링이나 실물 슬라이드의 실측 보정을 뜻하지 않는다.

## 카탈로그와 UI

- schemaVersion 2, `processMode`: `negative_print` / `positive_direct`.
- 네거티브 ID와 파일 번호 유지. 슬라이드는 `<film_id>__direct_scan`, `paper: null`.
- Provia `0017`, Velvia `0025`, Ektachrome `0041`, Kodachrome `0065`.
- 기존 32개 미지원 인화 조합 대신 4개 직접 스캔 룩만 노출.
- 총 132개 룩, 264개 LUT, 132개 ZIP, 792개 미리보기.
- 슬라이드에서는 인화지 선택 비활성화. 네거티브로 돌아오면 마지막 인화지 선택 유지.
- 다운로드·업로드 렌더링은 선택한 룩의 실제 STD/V-Log 파일을 사용한다.

## 검증 범위

4종의 오프그리드 직접 엔진 비교, 흑백 램프 방향, 인화지 초기화 의존성, 인화 노드 우회, 미리보기와 독립 LUT reader 일치, 메타데이터와 ZIP 내용을 검사한다. 슬라이드 최초 지원 시에는 기존 네거티브 LUT 256개의 SHA-256이 변경 전과 모두 같았다. 후속 STD v2에서는 직접 엔진 계산으로 STD LUT·미리보기·QA·ZIP이 갱신되므로 그 해시 불변성 주장은 적용하지 않는다. V-Log는 생성 방식을 유지한다. 최종 검사 결과는 `validation.md`와 조합별 `qa.json`에 기록한다. 카메라 실기 적용과 실물 필름 색 일치는 미검증이다.
