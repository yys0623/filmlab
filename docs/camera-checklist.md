# S1M2 / S1II 실기 확인

2026-11-04 C200 + Crystal Archive Type II의 원래 V-Log LUT와 S1II 합성 STD LUT를 사용자 카메라에서 각각 적용했습니다. EXIF는 DC-S1M2 펌웨어 1.5, LUT1 100%, LUT2 OFF를 확인하며 사용자는 이후 여러 장면을 같은 방식으로 촬영해 비교했고, 결과가 상당히 비슷하다고 평가했습니다. 이는 여러 장면의 정성 확인이며 차트·색차계 측정은 아닙니다. [자료와 수치 검증의 구분](camera-std.md)

## 같은 장면으로 비교하기

1. 앱에서 실제 카메라 모델을 선택하고 원하는 필름·인화지 ZIP을 받습니다. ZIP 안의 짧은 파일명을 사용합니다.
2. LUT Library에 STD와 V-Log를 각각 등록하고, 입력 베이스가 올바르게 인식되는지 확인합니다.
3. 합성 STD는 LUT1에 100%, LUT2 OFF로 적용합니다. 별도의 S2V를 추가하지 않습니다.
4. 조명·구도·초점·수동 화이트밸런스를 고정합니다. Photo Style 대비/채도 조정은 기본값으로 둡니다.
5. Standard LUT OFF/ON, V-Log LUT OFF/ON을 각각 촬영합니다. 조리개·셔터·ISO 및 실제 노출 차이를 기록합니다.
6. 피부·회색·빨강·녹색·하늘·하이라이트를 확인합니다. ISO 숫자가 같아도 내부 게인과 헤드룸이 같다고 가정하지 않습니다.
7. 색차 수치와 사용자의 시각 평가를 따로 기록합니다. 다른 기종으로 결과를 일반화하지 않습니다.

Panasonic [LUT Library](https://eww.pavc.panasonic.co.jp/dscoi/DC-S1M2/html/DC-S1M2_DVQP3227_eng/0079.html), [Photo Style](https://eww.pavc.panasonic.co.jp/dscoi/DC-S1M2/html/DC-S1M2_DVQP3227_eng/0076.html)를 참고하세요.

| 항목 | 현재 상태 |
|---|---|
| 카메라/펌웨어 | DC-S1M2 / 1.5 |
| C200 V-Log·합성 STD 가져오기 | 사용자 촬영 EXIF로 확인 |
| C200 선반 장면 | 사용자 정성 확인: 상당히 비슷함 |
| 수동 WB·고정 구도의 통제 촬영 | 미완료 |
| 피부·컬러 차트 정량 비교 | 미완료 |
| 다른 조합·기종의 실기 비교 | 미완료 |

구형 DMC-L10은 현재 지원하지 않습니다. GH6는 후반 작업용입니다. 일반 sRGB 파일에 적용한 색은 실제 해당 기종 Standard 입력의 정확도 검증이 아닙니다.
