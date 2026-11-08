# LUT 다운로드 파일명

파일명 규칙은 `src/lutNames.ts`에서 관리합니다. 필름 이름은 유지하고 인화지만 약자로 표시합니다. 브랜드·Professional 표기, 공백·문장부호는 파일명에서 제외합니다. 파일명 변경은 LUT의 색변환 데이터를 바꾸지 않습니다.

| 출력 | 규칙 | 예시 |
| --- | --- | --- |
| STD · 인화지 | 필름명 + 인화지 약자 | `C200CA.cube`, `Portra400EP.cube`, `Vision3200TCA.cube` |
| V-Log · 인화지 | 필름명 + 인화지 약자 + VLOG | `C200CAVLOG.cube`, `Portra400EPVLOG.cube` |
| 디지털 스캔 | 필름명 + DS | `C200DS.cube` |
| 슬라이드 직접 스캔 | 필름명 + SL | `Velvia100SL.cube` |
| 제공된 후지 시뮬레이션 | 시뮬레이션명 | `CLASSICCHROME.cube` |

인화지 없는 디지털·슬라이드의 V-Log 파일에도 `VLOG`가 붙습니다. 제공된 후지 시뮬레이션 9종은 인화지를 사용하지 않고 S1II STD 파일만 제공합니다.

기종은 내보내기 화면에서 선택합니다. 다른 기종의 STD LUT라도 파일명은 같으므로 **기종별로 폴더를 나누어 보관**해야 합니다. 카메라에 복사할 때도 해당 기종의 파일인지 먼저 확인합니다.

ZIP 이름에는 기종을 남깁니다. 예: `C200CA-S1II.zip`. ZIP 내부의 STD와 V-Log `.cube`도 위 규칙을 사용합니다. 기존 라이선스·생성 정보 등의 부속 파일명과 내용은 유지하며, 생성 정보에 기록된 원본 파일명은 다운로드 이름 변경 전의 이름입니다. ZIP 자체는 카메라에 넣지 않고 압축을 푼 `.cube`를 카드 최상위에 복사합니다.

## 인화지·프린트 필름 약자

웹의 인화지 선택과 갤러리에도 `인화지 이름 (약자)`로 표시합니다. 2383·2393은 영화용 프린트 필름입니다.

| 인화지·프린트 필름 | 약자 |
| --- | --- |
| Fujifilm Crystal Archive Type II | CA |
| Kodak Vision 2383 | 83 |
| Kodak Vision Premier 2393 | 93 |
| Kodak Ektacolor Edge | EE |
| Kodak Professional Endura Premier | EP |
| Kodak Professional Portra Endura | PE |
| Kodak Professional Supra Endura | SE |
| Kodak Professional Ultra Endura | UE |

## 카드 파일명 제한

[Panasonic S1II 공식 사용설명서 — LUT 라이브러리](https://eww.pavc.panasonic.co.jp/dscoi/DC-S1M2/html/DC-S1M2_DVQP3242_kor/0079.html)는 영숫자 파일명을 사용하도록 안내하며, FAT32는 확장자를 제외한 최대 8자, exFAT는 확장자를 포함한 최대 255자를 지원한다고 명시합니다. 확인일: 2026-11-04.

sosang은 필름 이름을 보존하므로 모든 파일명을 8자로 제한하지 않습니다. 긴 이름은 exFAT 카드에서 사용합니다. FAT32 카드를 사용할 경우 다운로드 후 이름을 영문·숫자 8자 이내로 직접 줄이되 `.cube` 확장자는 유지해야 합니다. 카메라·필름·인화지·STD/V-Log 조합을 구별할 수 있도록 원래 파일과 대응 관계를 기록합니다.
