import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { browserLocale, createLocalePreference, LOCALE_STORAGE_KEY, readSavedLocale, runtimeMessage, sampleText, translate } from '../src/i18n.ts'
import type { Sample } from '../src/types.ts'
import { english } from '../src/translations/en.ts'

test('saved choices are validated and take priority without a location request', async () => {
  let requests = 0
  const request = async () => { requests++; return { locale: 'ko', country: 'KR' } }
  assert.equal(await createLocalePreference('en').resolve(request, 'ko-KR'), 'en')
  assert.equal(requests, 0)
  assert.equal(readSavedLocale({ getItem: key => key === LOCALE_STORAGE_KEY ? 'ko' : null }), 'ko')
  assert.equal(readSavedLocale({ getItem: () => 'fr' }), null)
  assert.equal(readSavedLocale({ getItem: () => { throw new Error('Storage denied') } }), null)
})

test('country-derived locale takes priority over browser language', async () => {
  assert.equal(await createLocalePreference(null).resolve(async () => ({ locale: 'ko', country: 'KR' }), 'en-US'), 'ko')
  assert.equal(await createLocalePreference(null).resolve(async () => ({ locale: 'en', country: 'US' }), 'ko-KR'), 'en')
})

test('missing, malformed, and failed location responses fall back to browser language', async () => {
  for (const response of [null, {}, { locale: null }, { locale: 'fr' }, 'not JSON data']) {
    assert.equal(await createLocalePreference(null).resolve(async () => response, 'ko-KR'), 'ko')
    assert.equal(await createLocalePreference(null).resolve(async () => response, 'ja-JP'), 'en')
  }
  assert.equal(await createLocalePreference(null).resolve(async () => { throw new Error('Offline') }, 'ko'), 'ko')
  assert.equal(browserLocale('KO-kr'), 'ko')
  assert.equal(browserLocale(''), 'en')
})

test('a manual choice wins over an in-flight country response and its failure', async () => {
  for (const fails of [false, true]) {
    const preference = createLocalePreference(null)
    let resolve!: (value: unknown) => void
    let reject!: (error: Error) => void
    const pending = preference.resolve(() => new Promise((yes, no) => { resolve = yes; reject = no }), 'ko-KR')
    preference.select('ko')
    preference.select('en')
    if (fails) reject(new Error('Timeout'))
    else resolve({ locale: 'ko', country: 'KR' })
    assert.equal(await pending, 'en')
    assert.equal(await preference.resolve(async () => { throw new Error('Must not run') }, 'ko'), 'en')
  }
})

test('translation interpolation preserves user filenames and safely falls back for unknown keys', () => {
  const filename = '놀이터 전경 <photo> {0}.jpg'
  assert.equal(translate('en', '{0} 사진을 불러왔습니다.', [filename]), `Loaded photo: ${filename}.`)
  assert.equal(translate('ko', '{0} 사진을 불러왔습니다.', [filename]), `${filename} 사진을 불러왔습니다.`)
  assert.equal(translate('en', 'unregistered-key'), 'unregistered-key')
  assert.equal(runtimeMessage('en', `${filename} · 검증된 파일을 다운로드했습니다.`), `${filename} · Verified file downloaded.`)
})

test('sample display metadata changes without mutating input records or filenames', () => {
  const sample: Sample = Object.freeze({ id: 'std_playground', name: '놀이터 전경', category: '야외 · 하늘과 초록', credit: '사용자 촬영 · LUMIX S1M2 · P1458403.JPG · Standard / LUT OFF', source: null, path: '/samples/std_playground.webp', width: 960, height: 640, inputKind: 'camera-std', previewLut: 'std' })
  const before = JSON.stringify(sample)
  assert.equal(sampleText(sample, 'name', 'en'), 'Playground view')
  assert.equal(sampleText(sample, 'category', 'en'), 'Outdoors · Sky and greens')
  assert.equal(sampleText(sample, 'credit', 'en'), 'User photograph · LUMIX S1M2 · P1458403.JPG · Standard / LUT OFF')
  assert.equal(sampleText(sample, 'name', 'ko'), '놀이터 전경')
  assert.equal(sampleText({ ...sample, inputKind: 'uploaded-srgb' }, 'name', 'en'), '놀이터 전경')
  const review: Sample = { ...sample, inputKind: 'review-jpeg', nameEn: 'Sunlit street', categoryEn: 'Outdoors · sunshine', credit: 'DPReview' }
  assert.equal(sampleText(review, 'name', 'en'), 'Sunlit street')
  assert.equal(sampleText(review, 'category', 'en'), 'Outdoors · sunshine')
  assert.equal(sampleText(review, 'credit', 'en'), 'DPReview')
  assert.equal(JSON.stringify(sample), before)
})

test('dynamic request errors and network errors are translated at display time', () => {
  assert.equal(runtimeMessage('en', '카탈로그를 불러올 수 없습니다 (503)'), 'Could not load the catalog (503)')
  assert.equal(runtimeMessage('en', '샘플 사진을 불러오지 못했습니다 (404).'), 'Could not load the sample photo (404).')
  assert.equal(runtimeMessage('en', 'LUT 파일 검증에 실패했습니다. 페이지를 새로고침해 주세요.'), 'LUT verification failed. Please refresh the page.')
  assert.equal(runtimeMessage('ko', 'Failed to fetch'), '네트워크 연결을 확인한 뒤 다시 시도해 주세요.')
})

test('active Korean interface copy has English translations', () => {
  for (const file of ['main.tsx', 'ReviewSamples.tsx', 'FilmGallery.tsx', 'LutUsageGuide.tsx', 'WhiteBalanceGuide.tsx']) {
    const source = readFileSync(new URL(`../src/${file}`, import.meta.url), 'utf8')
    for (const match of source.matchAll(/\bt\(("(?:[^"\\]|\\.)*")/g)) {
      const key = JSON.parse(match[1]) as string
      if (!/[가-힣]/.test(key)) continue
      assert.ok(english[key], `${file}: missing translation for ${key}`)
      assert.doesNotMatch(translate('en', key), /[가-힣]/, `${file}: untranslated text in ${key}`)
    }
  }
})

test('camera-specific catalog errors and unified film attribution translate', () => {
  assert.equal(runtimeMessage('en', '카메라별 STD LUT 파일 정보를 확인하지 못했습니다. 다시 불러와 주세요.'), 'Could not verify the camera-specific STD files. Please reload.')
  assert.equal(translate('en', '필름 프로파일과 FUJIFILM 공식 LUT'), 'Film profiles and official FUJIFILM LUTs')
  assert.equal(translate('en', 'FUJIFILM 공식 LUT'), 'Official FUJIFILM LUT')
})

test('camera adapter warnings translate into Korean without changing the English report', () => {
  const source = 'For DC-L10 only. This adapter is not compatible with the older DMC-L10.'
  assert.equal(runtimeMessage('ko', source), 'DC-L10 전용입니다. 구형 DMC-L10과 호환되지 않습니다.')
  assert.equal(runtimeMessage('en', source), source)
  assert.match(runtimeMessage('ko', 'Matched controlled capture validation is pending for this camera model.'), /통제 촬영 검증 전/)
})
