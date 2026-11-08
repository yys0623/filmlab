import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { english } from './translations/en.ts'
import type { Sample } from './types.ts'

export type Locale = 'ko' | 'en'
export type Translate = (message: string | undefined, values?: readonly unknown[]) => string
export const LOCALE_STORAGE_KEY = 'film-lab-locale'
export const isLocale = (value: unknown): value is Locale => value === 'ko' || value === 'en'
export const browserLocale = (language: string): Locale => language.toLowerCase().startsWith('ko') ? 'ko' : 'en'

export function readSavedLocale(storage: Pick<Storage, 'getItem'> | undefined): Locale | null {
  try { const value = storage?.getItem(LOCALE_STORAGE_KEY); return isLocale(value) ? value : null }
  catch { return null }
}

// Manual choices are authoritative, including while the location request is
// pending. Automatic defaults are deliberately not persisted as user choices.
export function createLocalePreference(saved: unknown) {
  let current: Locale | null = isLocale(saved) ? saved : null
  let manual = current !== null
  return {
    select(locale: Locale) { current = locale; manual = true; return locale },
    async resolve(request: () => Promise<unknown>, language: string): Promise<Locale> {
      if (manual && current) return current
      let next = browserLocale(language)
      try {
        const data = await request()
        if (data && typeof data === 'object' && 'locale' in data && isLocale(data.locale)) next = data.locale
      } catch { /* Offline, timeout, and unavailable geolocation use the browser. */ }
      if (!manual) current = next
      return current || next
    },
  }
}

export function translate(locale: Locale, message: string | undefined, values: readonly unknown[] = []): string {
  if (!message) return ''
  const template = locale === 'en' ? english[message] || message : message
  return template.replace(/\{(\d+)\}/g, (token, index: string) => Number(index) < values.length ? String(values[Number(index)]) : token)
}

// Rendering translations here keeps worker requests, pixel buffers, filenames,
// and the original catalog independent of the selected interface language.
const cameraWarningMessages: Record<string, string> = {
  "Standard clipping and gamut compression cannot be inverted exactly; clipped highlights and colours cannot be restored.": "Standard의 클리핑과 색역 압축은 완전히 역변환할 수 없습니다. 잘린 하이라이트와 색은 복원하지 못합니다.",
  "Use the exact camera model and unadjusted Standard Photo Style. No automatic exposure or image statistics are applied.": "정확한 카메라 모델과 조정하지 않은 Standard 포토스타일을 사용해 주세요. 자동 노출이나 이미지 통계는 사용하지 않습니다.",
  "Camera cube interpolation is undocumented; tetrahedral and trilinear rebake error are both reported.": "카메라의 LUT 보간 방식은 공개되지 않았습니다. 사면체와 삼선형 보간의 합성 오차를 모두 제공합니다.",
  "Native V-Log acquisition gain, noise and highlight headroom cannot be recreated by an output LUT.": "출력 LUT로 실제 V-Log 촬영의 센서 게인, 노이즈, 하이라이트 여유를 재현할 수 없습니다.",
  "Matched controlled capture validation is pending for this camera model.": "이 카메라 모델은 조건을 맞춘 통제 촬영 검증 전입니다.",
  "Upstream support is qualitative field feedback, not controlled quantitative camera validation.": "원본 제작자의 지원 근거는 실촬영 육안 평가이며, 통제된 정량 카메라 검증은 아닙니다.",
  "GH6: post-processing only; Standard capture cannot bake this LUT in camera.": "GH6는 편집용입니다. Standard 촬영 시 이 LUT를 카메라 안에서 적용할 수 없습니다.",
  "For DC-L10 only. This adapter is not compatible with the older DMC-L10.": "DC-L10 전용입니다. 구형 DMC-L10과 호환되지 않습니다."
}

export function runtimeMessage(locale: Locale, message: string | undefined): string {
  if (!message) return ''
  if (cameraWarningMessages[message]) return translate(locale, cameraWarningMessages[message])
  if (['Failed to fetch', 'Load failed', 'NetworkError when attempting to fetch resource.', 'The network connection was lost.'].includes(message)) return translate(locale, '네트워크 연결을 확인한 뒤 다시 시도해 주세요.')
  if (message === 'Film Lab · generated technical test pattern · CC0') return translate(locale, 'Film Lab · 생성된 기술 테스트 패턴 · CC0')
  const exact = translate(locale, message)
  if (exact !== message || locale === 'ko') return exact
  const catalog = message.match(/^카탈로그를 불러올 수 없습니다 \((\d+)\)$/)
  if (catalog) return translate(locale, '카탈로그를 불러올 수 없습니다 ({0})', [catalog[1]])
  const sample = message.match(/^샘플 사진을 불러오지 못했습니다 \((\d+)\)\.$/)
  if (sample) return translate(locale, '샘플 사진을 불러오지 못했습니다 ({0}).', [sample[1]])
  const download = message.match(/^([\s\S]+) · 검증된 파일을 다운로드했습니다\.$/)
  if (download) return translate(locale, '{0} · 검증된 파일을 다운로드했습니다.', [download[1]])
  const timed = message.match(/^([\s\S]+) · 인화 필터 조정값으로 만든 파일을 다운로드했습니다\.$/)
  if (timed) return translate(locale, '{0} · 인화 필터 조정값으로 만든 파일을 다운로드했습니다.', [timed[1]])
  const credit = message.match(/^사용자 촬영 · ([\s\S]+)$/)
  if (credit) return translate(locale, '사용자 촬영 · {0}', [credit[1]])
  return exact
}

export function sampleText(sample: Sample, field: 'name' | 'category' | 'credit', locale: Locale): string {
  if (field === 'name' && sample.inputKind === 'uploaded-srgb') return sample.name
  if (locale === 'en' && field === 'name' && sample.nameEn) return sample.nameEn
  if (locale === 'en' && field === 'category' && sample.categoryEn) return sample.categoryEn
  return runtimeMessage(locale, sample[field])
}

export function useLocale() {
  const [saved] = useState(() => {
    try { return readSavedLocale(window.localStorage) } catch { return null }
  })
  const preference = useRef<ReturnType<typeof createLocalePreference> | null>(null)
  if (!preference.current) preference.current = createLocalePreference(saved)
  const [locale, updateLocale] = useState<Locale>(saved || browserLocale(navigator.language))
  const [ready, setReady] = useState(!!saved)
  useEffect(() => {
    if (saved) return
    let active = true
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 2000)
    void preference.current!.resolve(async () => {
      const response = await fetch('/api/locale', { cache: 'no-store', signal: controller.signal })
      if (!response.ok) throw new Error('Locale unavailable')
      return response.json()
    }, navigator.language).then(next => {
      if (active) { updateLocale(next); setReady(true) }
    }).finally(() => window.clearTimeout(timeout))
    return () => { active = false; controller.abort(); window.clearTimeout(timeout) }
  }, [saved])
  const setLocale = useCallback((next: Locale) => {
    preference.current!.select(next)
    updateLocale(next); setReady(true)
    try { window.localStorage.setItem(LOCALE_STORAGE_KEY, next) } catch { /* Still switch in privacy modes. */ }
  }, [])
  const t = useCallback<Translate>((message, values) => translate(locale, message, values), [locale])
  const message = useCallback((value: string | undefined) => runtimeMessage(locale, value), [locale])
  useEffect(() => {
    if (!ready) return
    document.documentElement.lang = locale
    document.title = locale === 'ko' ? 'sosang — LUT 스튜디오' : 'sosang — LUT Studio'
    document.querySelector('meta[name="description"]')?.setAttribute('content', locale === 'ko'
      ? '필름과 인화지를 조합하고, 내 사진으로 비교하고, V-Log·Standard용 LUT를 다운로드하세요.'
      : 'Combine film looks and print materials, compare them on your photos, and download V-Log or Standard LUTs.')
  }, [locale, ready])
  return useMemo(() => ({ locale, ready, setLocale, t, message }), [locale, ready, setLocale, t, message])
}
