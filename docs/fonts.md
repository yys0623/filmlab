# Film Lab의 로컬 웹폰트

2026-11-03에 공식 배포처에서 다운로드했다. 한글에는 SUIT Variable, 영문·숫자에는 Manrope Variable의 Latin 파일을 사용한다. 웹폰트는 앱의 `public/fonts/`에서 직접 제공하며 런타임 외부 폰트 CDN 요청은 필요하지 않다. 두 파일 모두 배포처가 제공한 WOFF2를 그대로 보관했고, 글리프·이름·메타데이터 수정이나 자체 서브셋·형식 변환을 하지 않았다.

## 배포 파일과 실제 검사

| 파일 | 폰트 버전 | 가변 굵기 `wght` | 크기 | cmap / glyph 수 |
|---|---|---|---:|---:|
| `public/fonts/SUIT-Variable.woff2` | 2.040 | 100–900 | 624,536 bytes | 2,933 / 2,956 |
| `public/fonts/Manrope-Variable-latin.woff2` | 4.505 | 200–800 | 24,436 bytes | 218 / 282 |

두 파일의 `wOF2` signature, TrueType outline, `fvar` 가변 축을 실제 파싱했다. SUIT의 `한`, Manrope의 `A`를 굵기 400·700으로 각각 읽어 윤곽이 실제로 달라지는 것도 확인했다. 파일명만 보고 가변 폰트로 판단하지 않았다. 이 검사는 파일 구조·문자 지원 검사이며, 브라우저 화면과 줄바꿈·레이아웃 검수는 별도로 수행한다.

SUIT는 현대 한글 완성형 11,172자 중 **2,668자**와 한글 호환 자모를 포함한다. 모든 한글이나 분해형 자모를 지원하는 파일은 아니다. 다운로드 시점의 `src/` 텍스트와 `public/catalog.json`에 쓰인 한글 완성형은 모두 포함됐으며 누락 문자는 없었다. 사용자 파일명 등 다른 입력에는 미지원 문자가 있을 수 있으므로 시스템 대체 폰트를 유지한다. Manrope Latin은 한글을 포함하지 않고, 두 파일 모두 ASCII 인쇄 문자 95개를 포함한다.

## 공식 출처

### SUIT Variable

- 제작자 저장소: [sun-typeface/SUIT](https://github.com/sun-typeface/SUIT)
- 고정 commit: `55118d981336d8fce005eb62888c12c0568ef7b0`
- [다운로드한 WOFF2 원본](https://raw.githubusercontent.com/sun-typeface/SUIT/55118d981336d8fce005eb62888c12c0568ef7b0/fonts/variable/woff2/SUIT-Variable.woff2)
- [제작자 CSS](https://raw.githubusercontent.com/sun-typeface/SUIT/55118d981336d8fce005eb62888c12c0568ef7b0/fonts/variable/woff2/SUIT-Variable.css)
- [라이선스 원문](https://raw.githubusercontent.com/sun-typeface/SUIT/55118d981336d8fce005eb62888c12c0568ef7b0/LICENSE) → `public/licenses/SUIT_OFL.txt`

### Manrope Variable Latin

- 공식 Google Fonts 저장소: [google/fonts — Manrope](https://github.com/google/fonts/tree/2fe1e8c6b137fb13041a7cfca6fdcd8a910ea4dc/ofl/manrope)
- 라이선스 기록의 고정 commit: `2fe1e8c6b137fb13041a7cfca6fdcd8a910ea4dc`
- [공식 Google Fonts CSS](https://fonts.googleapis.com/css2?family=Manrope:wght@200..800&display=swap)의 `latin` 블록에서 WOFF2 URL과 200–800 가변 굵기를 확인했다. 요청 User-Agent는 Chrome 131 데스크톱 형식이다. Google Fonts CSS는 요청 환경에 따라 다른 형식을 제공할 수 있다.
- [다운로드한 WOFF2 원본](https://fonts.gstatic.com/s/manrope/v23/xn7gYHE41ni1AdIRggexSvfedN4.woff2)
- [라이선스 원문](https://raw.githubusercontent.com/google/fonts/2fe1e8c6b137fb13041a7cfca6fdcd8a910ea4dc/ofl/manrope/OFL.txt) → `public/licenses/MANROPE_OFL.txt`

이 파일은 Google Fonts가 OFL로 배포하는 **Manrope 4.505**다. 저자 홈페이지의 별도 Manrope V5 파일이나 그 별도 사용 조건을 이 파일의 출처·라이선스로 혼용하지 않는다. URL의 `v23`은 Google Fonts 배포 URL의 버전 표기이며 폰트 내부 버전 4.505와 구분한다.

## 적용 범위와 대체 폰트

한국어 모드의 본문은 `"SUIT Variable", "Manrope"`, 영어 모드와 영문 룩 제목·필름 이름은 `"Manrope", "SUIT Variable"` 순서로 지정한다. 각 순서 뒤에는 `-apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Malgun Gothic", sans-serif` 같은 시스템 대체 폰트를 유지하는 편을 권장한다. `@font-face`에서 Manrope는 `font-weight: 200 800`, SUIT는 `font-weight: 100 900`, 둘 다 `font-style: normal; font-display: swap`으로 선언한다. Manrope 파일의 기본 name 레코드에 ExtraLight가 있어도 위의 가변 축 전체를 포함한다.

Manrope의 `unicode-range`는 제공된 공식 Latin CSS를 따른다.

```css
unicode-range: U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC,
  U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329,
  U+2000-206F, U+20AC, U+2122, U+2191, U+2193,
  U+2212, U+2215, U+FEFF, U+FFFD;
```

SUIT에는 `unicode-range`를 좁게 지정하지 않는 편을 권장한다. 한글 외에 파일이 지원하는 `↗ → ← ₩` 등의 기호에도 대체 글리프를 제공할 수 있다. Manrope Latin에 없는 `Δ` 같은 그리스 문자와 두 파일에 없는 글자는 다음 시스템 폰트로 넘어간다. 이는 CSS 적용 권장 기준이며 폰트 파일의 문자 집합을 확장한다는 뜻은 아니다.

## 라이선스와 무결성

두 파일 모두 **SIL Open Font License 1.1**이며, 원문 저작권 고지와 전문을 위의 `public/licenses/` 파일에 그대로 보관한다. SUIT 원문은 SUNN의 저작권 및 Reserved Font Name `SUIT`를 명시한다. Manrope 원문은 The Manrope Project Authors의 저작권을 명시한다. 웹폰트와 함께 이 라이선스 파일을 배포한다. 폰트 자체의 라이선스는 LUT의 CC BY-SA와 구분한다.

| 파일 | SHA-256 |
|---|---|
| `SUIT-Variable.woff2` | `aa894a204d5a6fbae259dac6868d350cbd373a390caee0313f92946af741df23` |
| `Manrope-Variable-latin.woff2` | `8bd97e6bbbc1f602a8f791530eed1064c9a357d5731bbc76e3fc587fb068728f` |
| `SUIT_OFL.txt` | `30d101ee3c35ef629d622d933d261a27b2f60223e0a3b0f36791e569c2b9daa9` |
| `MANROPE_OFL.txt` | `58172e0c0fac2cda8a37b348164bb55e44b0e69051e557e92b1d3f6910141f7b` |
