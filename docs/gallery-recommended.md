# 추천 조합 갤러리

`#gallery/recommended`는 2026년 11월 7일 LUMIX S1II로 촬영한 WebP 270장을 보여준다. 기존 실촬영 갤러리(`#gallery`)와 STD 미리보기 샘플은 별도로 유지한다.

사진은 카메라에서 LUT를 적용해 완성한 결과다. 가져올 때 색을 다시 계산하지 않는다. WebP의 `LUT1Name`을 스튜디오의 실제 내보내기 파일명과 대조해 필름, 인화지, 현상 방식을 식별한다. `FC`가 붙은 13개 조합 251장은 해당 현상 프리셋으로 연결하고, `FC`가 없는 Portra 400 19장은 기본 조합으로 연결한다. 두 경우 모두 촬영 당시 첫 번째 LUT의 불투명도는 100%였고 두 번째 LUT는 꺼져 있었다.

## 다시 가져오기

프로젝트 루트에서 지원되는 Node 런타임, ExifTool, 프로젝트의 Python 가상환경을 사용한다.

```sh
.venv/bin/python -m pipeline.import_recommended_gallery --source /path/to/2601107_film/webp --jobs 4
npm test
npm run verify:assets
```

새 컬렉션은 `public/gallery/recommended/manifest.json`, `images/`, `thumbs/`에 저장한다. 확대본은 긴 변 최대 2,400px, 썸네일은 480px이며, EXIF 방향을 반영해 세로 사진도 바로 서게 한다. 공개 WebP에는 원본 EXIF나 XMP를 복사하지 않는다. 매니페스트에는 분류·화면 표시에 필요한 촬영 정보와 검증용 해시를 기록한다. 사진의 저작권은 촬영자에게 있으며 사진은 애플리케이션의 소스 라이선스 대상이 아니다.
