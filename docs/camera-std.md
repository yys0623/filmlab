# 카메라별 STD → V-Log 합성

## 현행 계약

`STD_camera(x) = L_VLOG(A_camera(x))`

`A_camera`는 V-Log Alchemy의 기종별 Standard→Panasonic V-Log/V-Gamut LUT입니다. `L_VLOG`는 현재 제공하는 spektrafilm 또는 FUJIFILM 합성 V-Log LUT의 직렬화된 값입니다. 입력 adapter를 trilinear, 룩을 tetrahedral로 평가한 뒤 33³ 표를 생성합니다. 브라우저 미리보기는 이 합성 표를 한 번만 적용하며, 카메라 다운로드와 같은 바이트를 사용합니다.

단일 톤 선행 커브 A/B, JpgToneProtection, sRGB decode 후 장면 선형값으로 취급하는 입력 변환, 추가 채도·노출 보정은 사용하지 않습니다. LUT의 출력값을 만드는 원래 V-Log 룩은 변경하지 않습니다. 다른 카메라 모델은 서로 대체하지 않습니다.

## 출처와 모델

- [V-Log Alchemy](https://github.com/shenmintao/V-Log-Alchemy/tree/e51ba9a23458ff5c316f630b860eb0201139d126), commit `e51ba9a23458ff5c316f630b860eb0201139d126`.
- [변환 방법](https://github.com/shenmintao/V-Log-Alchemy/blob/e51ba9a23458ff5c316f630b860eb0201139d126/Luts/Panasonic-Standard/README.md), [합성 코드](https://github.com/shenmintao/V-Log-Alchemy/blob/e51ba9a23458ff5c316f630b860eb0201139d126/Tools/merge_standard_luts.py).
- 원본은 SILKYPIX의 기종별 Standard/V-Log 전방 표 대응을 정규화된 전역 최적화로 맞춥니다. 추가 실제 카메라 제약에는 S1RII 촬영 자료를 공통 사용합니다. Panasonic이 공개한 정확한 역변환이라는 의미가 아닙니다.
- GH6, S5II, S5IIX, G9II, GH7, S9, S1IIE, S1RII, S1II, DC-L10. GH6는 후반 작업 전용입니다. **DMC-L10은 미지원**입니다.
- 원작자의 정량 검증은 S1RII 펌웨어 1.5, 정성 현장 검증은 S9이며 S1II를 포함한 나머지는 모델별 통제 촬영 검증이 남아 있습니다.

## S1II 사용자 실기 관찰

2026-11-04 사용자 제공 C200 + Crystal Archive Type II 결과:

| 파일 | Photo Style | LUT | 강도 | ISO / 조리개 / 셔터 | WB |
|---|---|---|---|---|---|
| P1503671.JPG | V-Log | Fujifilm C200 V-Log.cube | 100% | 1600 / f2.8 / 1/250 | Auto |
| P1503675.JPG | Standard or Custom | Fujifilm C200 Alchemy TEST.cube | 100% | 1600 / f2.8 / 1/250 | Auto |

두 사진 모두 DC-S1M2 펌웨어 1.5, LUT2 OFF입니다. 사용자는 이후 여러 장면을 같은 방식(V-Log + 원래 LUT, Standard + 합성 STD)으로 촬영해 비교했고, 합성 STD가 V-Log 결과와 상당히 비슷하다고 평가했습니다. 위 표는 EXIF를 기록한 첫 비교 쌍입니다. 구도와 자동 WB가 고정되지 않았고 색차계·차트 측정이 없으므로 **여러 장면의 사용자 정성 확인**으로 기록합니다. 모든 기종·필름의 정량 검증 완료로 확대하지 않습니다. 원본 사진은 개인 저장 위치에 두고 공개 배포에 추가하지 않습니다.

기준 C200 V-Log SHA-256: `542f359f9158f21c941b24baf40b05db61dc171887e02b29dadb09d48d443ef9`.
S1II 원본 adapter SHA-256: `7f1f997cb4bcf5c427e8e6ccc81acfedd3f14dae0b1e8e3f8672a8231daefa7e`.
시험 합성 파일 SHA-256: `71705766f720471e6f59daa2544ba2669fc39349c38b39ed7c53d62154a95eaf`.
공개 산출물은 제목·DOMAIN 기록 차이로 파일 해시가 달라질 수 있으므로 시험 파일과의 수치 표 일치도 별도로 검사합니다.

## 수치 검증의 의미

합성 표의 격자 값은 순차 adapter→룩 계산과 직렬화 정밀도 안에서 같아야 합니다. 격자 사이에는 재샘플링 오차가 있습니다. QA의 무작위 RGB·회색 램프·샘플 사진 오차는 이 순차 계산과 합성 CUBE의 차이를 뜻하며 실카메라 STD와 실제 V-Log 촬영의 색차가 아닙니다.

최초 C200 시험: 무작위 RGB 16,384점, 0–255 채널 절대오차 평균 0.240, 95백분위 0.848, 최대 11.862 (tetrahedral 합성 CUBE 평가). 회색 4,097점 평균 0.086, 최대 0.840. 높은 채도 경계의 최대 오차를 평균값으로 숨기지 않습니다. 다른 조합은 각자의 QA를 확인해야 합니다.

최대한 재샘플링을 줄이는 방법은 카메라의 두 LUT를 연결하는 것입니다: LUT1에 해당 모델 S2V, LUT2에 원래 V-Log 룩, 양쪽 100%. 현행 앱은 사용자가 선호한 단일 합성 LUT를 제공합니다. 단일 STD를 사용하면서 S2V를 또 앞에 적용하면 변환이 중복됩니다.

## 한계와 다음 검증

- Standard에서 이미 잘린 하이라이트·색과 노이즈·디테일은 역변환으로 복원할 수 없습니다.
- 동일 ISO 숫자가 Standard와 V-Log에서 같은 센서 게인·헤드룸을 뜻하지 않을 수 있습니다. 문서의 S1RII 노출 차이를 모든 기종의 고정 보정값으로 넣지 않습니다.
- Photo Style의 대비/채도 등을 바꾸거나 Natural/Cinelike/다른 프로파일을 쓰면 전제와 다릅니다.
- 33³ 카메라 보간 방식은 공개되지 않았습니다. 앱은 tetrahedral이며 카메라와의 픽셀 동일성을 보장하지 않습니다.
- 피부·회색·고채도 패치·하이라이트를 고정 조명/수동 WB/같은 구도로 STD 및 V-Log LUT OFF/ON 촬영하여 비교해야 합니다.

## 보존과 배포

모든 원래 V-Log 바이트와 그 안의 필름·인화·FUJIFILM 모델을 보존합니다. 이전 B 파일은 서비스 디렉터리 밖 개발 아카이브에 보존하고 현행 미리보기·다운로드에서 제외합니다. 각 카메라 ZIP에 선택한 STD와 원래 V-Log, 생성 정보, 수치 QA, 관련 라이선스를 넣습니다. 기본 S1II 외 기종의 CUBE는 검증된 ZIP 엔트리로 전송하여 raw 파일 사본을 늘리지 않습니다.

기종별 source hash와 고정 commit, 보간 방법, 실기 검증 상태를 provenance에 기록합니다. V-Log Alchemy Apache-2.0 고지, spektrafilm 프로파일 고지, 해당하는 FUJIFILM 고지를 각각 보존합니다.

## 재생성

처음 입력 변환을 준비할 때는 고정 commit의 checkout을 지정합니다. 이후에는 이미 검증된 `public/camera-adapters`를 재사용합니다.

```sh
.venv/bin/python scripts/migrate-camera-std.py --source /path/to/V-Log-Alchemy --jobs 3
# 준비된 입력 변환과 현재 V-Log 파일에서 전체 STD 다시 생성
.venv/bin/python scripts/migrate-camera-std.py --jobs 3
# 개발용 단일 조합 재생성
.venv/bin/python scripts/migrate-camera-std.py --only fujifilm_c200__fujifilm_crystal_archive_typeii --jobs 1
```

V-Log 자체를 다시 만들 때는 `pipeline.generate`와 `pipeline.generate_fuji`가 현행 카메라 STD 생성기를 호출합니다. 원본 V-Log를 보존한 입력 변환 갱신에는 위 migration 명령을 사용합니다. `artifacts/std-b-before-camera-alchemy/`에 이전 카탈로그·STD·관련 파일을 보존합니다. 최종 카탈로그 저장 전 모든 기존 V-Log 해시가 변하지 않았는지 확인합니다.
