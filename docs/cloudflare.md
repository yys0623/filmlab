# Cloudflare 공개 배포본

현행 sosang 빌드는 148개 엔진 룩, 10개 카메라의 합성 STD 1,480개, 공통 V-Log 148개와 사용자가 제공한 후지 STD LUT 9개를 제공합니다. 여기에 네거티브 인화 128개 조합마다 추천 현상 방법 변형이 하나씩 붙고([필름 색 남김 문서](film-cast.md)), 인화 필터 M·Y 슬라이더용 데이터 128개(`/print-timing/`, [인화 필터 문서](print-timing.md))가 함께 배포됩니다. 제공된 후지 LUT는 인화지·카메라 변환 없이 그대로 제공하며 별도 `suppliedFuji` 카탈로그로 관리합니다. 선택한 기종의 ZIP을 미리보기·다운로드 전송에 사용합니다. 모델별 변환·검증 상태·권리는 [카메라 STD 문서](camera-std.md)를 참고하세요. 빌드 갱신과 실제 공개 사이트 배포는 별도입니다.

`scripts/prepare-cloudflare.mjs`는 완성된 `dist/`를 읽어 별도 `dist-cloudflare/`를 생성한다. 공개 카탈로그에서 `reference_interpretation` 조합과 `referenceStudy`를 제거하고 상태별 개수를 재계산한다. 제외 조합의 디렉토리 전체와 `research/reference-looks.json`도 복사하지 않는다. 기존 FUJI 공식 필름·`fujiStudy`·`research/fujifilm-official.json`과 90개 합성 룩은 제거한다. 제공 후지 LUT 9개와 provenance·NOTICE는 `/supplied-fuji/`에서 원본 수치 그대로 제공한다. 공개되는 148개 조합의 카메라별 STD·VLOG·QA·출처 자산은 입력 `dist/`의 바이트를 유지한다. 미리보기는 선택한 카메라의 STD로 브라우저에서 계산하고, 과거 버전의 미리보기 사본은 포함하지 않는다. 외부 리뷰 사진을 모은 `sample-study/`는 배포 입력에 포함하지 않는다.

```sh
node scripts/prepare-cloudflare.mjs
node scripts/verify-cloudflare.mjs
node --experimental-strip-types scripts/verify-assets.mjs dist-cloudflare
node --test tests/cloudflare.test.mjs tests/geo.test.mjs
```

Node.js 22.12 이상을 사용한다. 첫 명령은 전용 출력 폴더 `dist-cloudflare/`를 다시 만든다. 개인용 `dist/`는 변경하지 않는다. `verify-cloudflare`는 148개 조합·1,480개 STD와 148개 V-Log LUT, 별도 후지 STD 9개, 제외된 데이터의 부재, 원본 카탈로그의 허용된 부분과의 일치, 자산 해시·크기, JSON의 웹 자산 참조, 샘플 원본 해시, 공개 텍스트의 개인 로컬 경로, 20,000개 파일·단일 25 MiB 제한을 검사한다. 기존 `verify-assets` 검사는 ZIP 안 LUT의 해시·형식·수치까지 검증한다. `verify-supplied-fuji`는 별도 후지 파일의 해시와 원본 데이터 보존, STD 태그, 중복·누락 및 불필요한 인화지/V-Log/카메라 합성 경로의 부재를 검사한다.

필름 라이선스와 사진 권리는 구분한다. 공개 샘플은 사용자 촬영본과 기술 테스트 패턴만 포함하며, 이용자가 선택한 사진은 브라우저 안에서 처리한다.

## 실행과 계정 연결

먼저 현행 카메라 STD 생성·검증을 완료한 뒤 배포 빌드를 만든다. 이전 B 정리 도구는 과거 아카이브용이며 현행 생성 경로에 사용하지 않는다.

`npm run build:cloudflare`는 타입 검사·Vite 빌드·무손실 ZIP 패키징·공개판 선별·소스 코드 패키징·공개판 검사를 순서대로 실행한다. `npm run preview:cloudflare -- --port 4418`로 Cloudflare의 로컬 런타임을 실행한다. `npm run deploy:cloudflare`는 같은 빌드·검증 후 공식 Wrangler로 배포한다. 모든 명령은 `scripts/run-web.mjs`의 지원 Node 런타임 선택을 거친다.

무료 Cloudflare 계정을 만들고 이메일을 인증한 후 `npm run cloudflare:login`의 공식 OAuth 승인을 완료한다. 인증 값은 Wrangler가 로컬에서 관리하며 저장소·배포 자산에 포함하지 않는다. 여러 계정에 속해 있으면 배포 대상 계정을 명시적으로 선택해야 한다. 기본 `wrangler.jsonc`의 `name`은 `sosang`이며, `npm run deploy:cloudflare`는 이 Worker에 배포한다. 기존 동명 Worker가 있다면 덮어쓰기 전에 소유·용도를 확인한다.

휴대폰 등 다른 기기에서 승인하거나 원격 작업 중이면 다음 기기 인증 방식을 사용한다. 터미널에 표시된 공식 주소에서 일회용 코드를 입력하고 승인하면 되며, 브라우저가 이 컴퓨터의 localhost에 접근할 필요가 없다. 앱 배포에 필요한 계정·사용자 조회와 Worker 배포 권한으로 범위를 제한한다.

```sh
npm run cloudflare:login -- --device --browser=false --scopes account:read user:read workers_scripts:write
```

`server/worker.mjs`는 언어 자동 선택을 위한 `GET /api/locale`만 처리한다. `wrangler.jsonc`의 `run_worker_first: ["/api/locale"]`로 해당 경로만 Worker를 먼저 실행하고, 그 외 요청은 기존 정적 자산 제공을 유지한다. Worker에 전달된 다른 경로도 `env.ASSETS.fetch(request)`로 넘긴다. 바인딩은 정적 파일용 `ASSETS` 하나이며 데이터베이스·KV·유료 서비스 바인딩은 추가하지 않는다. 기존 `workers_scripts:write` 배포 권한을 그대로 사용한다. 이 구성은 Cloudflare의 [선택 경로 Worker 실행 및 자산 바인딩](https://developers.cloudflare.com/workers/static-assets/binding/)을 따른다.

기본 공개 주소는 **https://sosang.film-lab-jc.workers.dev/**이다. 새 Cloudflare 배포는 기존 Sites의 접근 권한이나 배포를 변경하지 않는다.

## 주소 이전과 구주소 유지

기존 `https://film-lab.film-lab-jc.workers.dev/`는 `wrangler.legacy.jsonc`의 `film-lab` Worker로 유지한다. 진입점은 `server/legacy-worker.mjs`이다. 구주소의 `/`와 `/index.html`에 대한 GET·HEAD 요청만 같은 경로의 새 호스트로 308 리디렉션하며 쿼리 문자열을 보존한다. `#studio` 같은 fragment는 서버에 전달되지 않으며 브라우저가 새 주소로 이어간다.

이미 열린 구주소 탭이 카탈로그·사진·LUT 파일을 계속 읽을 수 있도록 정적 자산과 `/api/locale`은 구주소에서도 제공한다. 구주소의 정적 자산 우선 처리는 의도된 구성이다. 공유한 파일 직접 링크도 유지하며, 새로 공유하는 사이트 주소에는 sosang 호스트를 사용한다.

먼저 `npm run deploy:cloudflare`로 새 주소를 배포하고 홈페이지·언어 API·사진·LUT 다운로드를 확인한다. 확인이 끝난 뒤에만 같은 검증된 배포 자산으로 구주소 Worker를 별도로 배포한다. 다음 명령은 Node.js 22.12 이상에서 실행한다.

```sh
node node_modules/wrangler/bin/wrangler.js deploy --config wrangler.legacy.jsonc
```

일반 업데이트는 기본 sosang 배포 명령을 사용한다. 구주소 배포는 위 명령으로 명시적으로 수행한다. 호스트가 달라지므로 브라우저에 저장된 언어·카메라 선택은 새 주소에서 다시 설정된다.

## 접속 국가와 언어

Worker는 Cloudflare가 제공하는 [`request.cf.country`](https://developers.cloudflare.com/workers/runtime-apis/request/#incomingrequestcfproperties)만 읽는다. `KR`이면 `{"locale":"ko"}`, 다른 국가 코드이면 `{"locale":"en"}`을 반환한다. 국가 정보가 없거나 미확인 코드인 경우에는 `{"locale":null}`을 반환해 클라이언트가 브라우저 언어를 대체 기준으로 사용할 수 있게 한다. 요청자가 넣은 국가 헤더·쿼리 매개변수는 판단에 사용하지 않는다.

응답에는 언어 코드만 포함하며 IP·국가 정보의 저장이나 로그 출력을 하지 않는다. `Cache-Control: no-store`를 Worker 응답에 직접 적용해 서로 다른 방문자의 언어 결과를 재사용하지 않는다. `HEAD`도 지원하고 다른 메서드는 `405`와 `Allow: GET, HEAD`로 거절한다. 로컬 환경에서는 국가 정보가 없을 수 있으며, 국가별 분기·헤더 무시·캐시·정적 자산 전달은 `tests/geo.test.mjs`로 확인한다.

## 캐시와 소스 제공

`public/_headers`는 내용 해시가 파일명에 들어간 `/assets/*`에만 1년 immutable 캐시를 설정한다. 고정 이름인 카탈로그·LUT ZIP·사진·소스 패키지는 Cloudflare 기본 ETag 재검증을 유지한다. 새 LUT와 오래된 ZIP의 혼합을 막기 위해 고정 경로에는 immutable을 사용하지 않는다. 압축과 캐시 응답 헤더는 실제 배포 후 확인한다.

`scripts/package-source.mjs`는 허용한 소스와 라이선스만 묶어 `/source/film-lab-source.tar.gz`로 제공한다. 브라우저 코드와 함께 `server/worker.mjs`도 포함하고 필수 파일로 확인한다. 사진·LUT 데이터·인증 정보·개인용 배포 설정을 넣지 않는다. 사이트의 제작 정보에서 소스를 내려받을 수 있으며, 카탈로그에 패키지 크기와 SHA-256을 기록한다.

