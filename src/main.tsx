import React, { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import type { Asset, Catalog, Combination, NegativeProcessMode, Sample } from './types'
import { fetchVerifiedAsset } from './assets'
import { paperLabel } from './lutNames'
import { renameZipEntries } from './downloadZip'
import { PHOTO_ACCEPT, usePhotoLook, usePhotoUpload, useSamplePhoto } from './usePhoto'
import { CAMERA_STORAGE_KEY, DEFAULT_CAMERA, UNSUPPORTED_L10, cameraForSample, sampleForCamera, downloadFilename, findLook, findFilmCast, processModeFor, selectStdAsset, selectDownloadAsset, selectStdQa, suppliedCombination, previewCameraFor } from './lookSelection'
import { runtimeMessage, sampleText, useLocale, type Locale, type Translate } from './i18n'
import { FilmGallery, type GalleryPhoto } from './FilmGallery'
import { FilmCanister } from './FilmCanister'
import { LutUsageGuide } from './LutUsageGuide'
import { WhiteBalanceGuide } from './WhiteBalanceGuide'
import { usePrintTiming } from './usePrintTiming'
import { filmCastShift, formatShift, sameShift, shiftCode } from './printTiming'
import './style.css'

const paths: Record<string, React.ReactNode> = {
  upload: <><path d="M12 16V4m-5 5 5-5 5 5"/><path d="M4 16v5h16v-5"/></>,
  download: <><path d="M12 3v12m-5-5 5 5 5-5"/><path d="M5 16v5h14v-5"/></>,
  chevron: <path d="m9 5 7 7-7 7"/>,
  splitArrows: <path d="m9 7-5 5 5 5m6-10 5 5-5 5"/>,
  search: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/></>,
  check: <path d="m5 12 4 4L19 6"/>,
  info: <><circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v.1"/></>,
  close: <path d="m6 6 12 12M18 6 6 18"/>,
  compare: <><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M12 2v20M4 15l4-4 4 4m0-2 4-4 4 5"/></>,
  image: <><rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="8" cy="10" r="1"/><path d="m4 17 5-4 3 2 4-6 5 7"/></>,
  arrow: <path d="M4 12h16m-6-6 6 6-6 6"/>,
  camera: <><path d="M3 7h4l2-3h6l2 3h4v14H3z"/><circle cx="12" cy="13" r="4"/></>,
  film: <><rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 3v18M16 3v18M4 8h4m8 0h4M4 16h4m8 0h4"/></>,
  external: <><path d="M14 3h7v7m0-7L10 14"/><path d="M10 4H4v16h16v-6"/></>,
}
function Icon({ name, size = 18 }: { name: string; size?: number }) { return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg> }
const shortName = (name: string) => name.replace(/^(Kodak|Fujifilm) (Professional )?/i, '')
const sizeLabel = (bytes: number) => `${(bytes / 1024 / 1024).toFixed(2)} MB`

function Preview({ sample, combo, mode, resultPath, processingError, retry, lookLabel, blockedReason, locale, t }: { blockedReason?: string; locale: Locale; t: Translate; sample: Sample; combo: Combination; mode: 'original' | 'compare' | 'look'; resultPath?: string; processingError?: string; retry?: () => void; lookLabel: string }) {
  const [split, setSplit] = useState(50)
  const [loaded, setLoaded] = useState({ source: false, result: false })
  const [failed, setFailed] = useState(false)
  const available = combo.status === 'ready' && !blockedReason
  const showResult = available && mode !== 'original'
  const ready = loaded.source && (!showResult || loaded.result)
  const beforeLabel = sample.inputKind === 'review-jpeg' ? t("리뷰 JPG · LUT OFF") : sample.inputKind === 'camera-std' ? t("STD 원본 · LUT OFF") : sample.inputKind === 'uploaded-srgb' ? t("내 사진 · 원본") : t("기준 sRGB")
  const error = blockedReason || (failed ? t("이미지를 불러오지 못했습니다. 다시 시도해 주세요.") : runtimeMessage(locale, processingError))
  const sampleName = sampleText(sample, 'name', locale)
  return <div className={`preview ${mode}`} aria-busy={!ready && !error}>
    <img className="preview-image" src={sample.path} alt={`${sampleName}: ${beforeLabel}`} onLoad={() => setLoaded(s => ({ ...s, source: true }))} onError={() => setFailed(true)} />
    {showResult && resultPath && <div className="result-image" style={{ clipPath: mode === 'compare' ? `inset(0 0 0 ${split}%)` : undefined }}><img className="preview-image" src={resultPath} alt={t("{0}: {1} LUT 적용", [sampleName, lookLabel])} onLoad={() => setLoaded(s => ({ ...s, result: true }))} onError={() => setFailed(true)} /></div>}
    {ready && available && !failed && <>
      {mode !== 'look' && <span className="image-tag before">{beforeLabel}</span>}
      {mode === 'compare' && <><div className="divider" style={{ left: `${split}%` }} aria-hidden="true"><span className="divider-handle"><Icon name="splitArrows" size={20}/></span></div><input className="comparison-range" type="range" min="0" max="100" value={split} onChange={e => setSplit(+e.target.value)} aria-label={t("이미지 비교 경계")} aria-valuetext={t("기준 이미지 {0}%, 필름 적용 {1}%", [split, 100 - split])} /></>}
      {showResult && <span className="image-tag after"><i/> {t("LUT 적용 · 100%")}</span>}
    </>}
    {(!ready || failed || (mode !== 'original' && (!available || error))) && <div className="preview-overlay"><Icon name={error ? 'info' : available ? 'image' : 'film'} size={28}/><strong>{blockedReason ? t("카메라 입력을 확인해 주세요") : error ? t("미리보기를 만들지 못했습니다") : available ? (sample.inputKind === 'uploaded-srgb' ? t("내 사진에 LUT를 적용하는 중") : t("샘플 사진에 LUT를 적용하는 중")) : combo.status === 'unsupported' ? t("이 조합은 아직 지원하지 않아요") : t("아직 준비되지 않은 조합입니다")}</strong><p>{error || (!available ? runtimeMessage(locale, combo.reason) : sample.inputKind === 'uploaded-srgb' ? t("사진은 내 기기 안에서만 처리합니다.") : t("STD LUT로 브라우저에서 계산합니다."))}</p>{error && !blockedReason && retry && <button className="retry-button" onClick={retry}>{t("다시 시도")}</button>}</div>}
  </div>
}

/** Rough name for the hue a recommended development leaves in 18% gray (CIELAB h°). */
function castDirection(hue: number) {
  return hue < 70 || hue >= 345 ? '따뜻한 주황·붉은' : hue < 110 ? '노란' : hue < 160 ? '연두' : hue < 200 ? '초록·청록' : hue < 260 ? '청록·푸른' : hue < 300 ? '보랏빛' : '분홍빛'
}

type View = 'studio' | 'gallery' | 'gallery/recommended'
function viewFromHash(): View {
  if (window.location.hash === '#gallery/recommended') return 'gallery/recommended'
  return window.location.hash === '#gallery' ? 'gallery' : 'studio'
}

function App() {
  const { locale, ready: localeReady, setLocale, t, message } = useLocale()
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [view, setView] = useState<View>(viewFromHash)
  const [loadError, setLoadError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [filmId, setFilmId] = useState('kodak_portra_400')
  const [paperId, setPaperId] = useState('fujifilm_crystal_archive_typeii')
  const [negativeMode, setNegativeMode] = useState<NegativeProcessMode>('negative_print')
  const [filmCastOn, setFilmCastOn] = useState(false)
  // Session-only memory of slider positions per look (film + paper) and per
  // print filter mode; a page reload starts every look from its default again.
  const [timingStore, setTimingStore] = useState<Record<string, { m: number; y: number }>>({})
  const [brand, setBrand] = useState('모두')
  const [search, setSearch] = useState('')
  const [sampleId, setSampleId] = useState('')
  const [cameraId, setCameraId] = useState(() => { try { return window.localStorage.getItem(CAMERA_STORAGE_KEY) || DEFAULT_CAMERA } catch { return DEFAULT_CAMERA } })
  const [mode, setMode] = useState<'original' | 'compare' | 'look'>('compare')
  const [format, setFormat] = useState<'vlog' | 'std' | 'zip'>('std')
  const [downloading, setDownloading] = useState(false)
  const [notice, setNotice] = useState('')
  const dialog = useRef<HTMLDialogElement>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const filmLibrary = useRef<HTMLElement>(null)
  const previewPanel = useRef<HTMLElement>(null)
  const [dragging, setDragging] = useState(false)
  const upload = usePhotoUpload(() => { setSampleId('@upload'); setMode('compare') })
  const activePhoto = sampleId === '@upload' ? upload.photo : null
  const suppliedLooks = catalog?.suppliedFuji?.looks || []
  const libraryFilms = [...(catalog?.films || []), ...suppliedLooks.map(look => look.stock)]
  const selectedFilm = libraryFilms.find(f => f.id === filmId) || libraryFilms[0]
  const selectedPaper = catalog?.papers.find(p => p.id === paperId) || catalog?.papers[0]
  const suppliedLook = suppliedLooks.find(look => look.stock.id === selectedFilm?.id)
  const isSupplied = !!suppliedLook
  const exportCameraId = isSupplied ? catalog!.suppliedFuji!.cameraId : cameraId
  const preference = negativeMode
  const processMode = selectedFilm ? processModeFor(selectedFilm, preference) : 'official_print'
  const baseCombo = !suppliedLook && catalog && selectedFilm && selectedPaper ? findLook(catalog.combinations, selectedFilm, selectedPaper.id, preference) : undefined
  const castCombo = catalog ? findFilmCast(catalog.combinations, baseCombo) : undefined
  // Sliders hold the total M/Y shift from the film's neutral filters. The
  // film-cast button moves them to its preset; on 0/0 or on that preset the
  // published, verified LUT files are used, anywhere else a cube is baked.
  const [methodInfo, setMethodInfo] = useState(false)
  // Phones: the settings sit below the preview, so show a small live copy while it is off screen.
  const [previewOffscreen, setPreviewOffscreen] = useState(false)
  // Keep the last frame while the next one is computed, so the thumbnail does not blink.
  const miniFrame = useRef<string | undefined>(undefined)
  useEffect(() => { if (!methodInfo) return; const close = (e: KeyboardEvent) => { if (e.key === 'Escape') setMethodInfo(false) }; const outside = (e: PointerEvent) => { if (!(e.target as Element)?.closest?.('.film-cast-switch')) setMethodInfo(false) }; window.addEventListener('keydown', close); window.addEventListener('pointerdown', outside); return () => { window.removeEventListener('keydown', close); window.removeEventListener('pointerdown', outside) } }, [methodInfo])
  // Portra 400 is the blend reference: its film-cast variant equals the neutral look.
  const castLocked = !castCombo || baseCombo?.film === catalog?.filmCast?.referenceFilm
  const castSelected = filmCastOn && !castLocked
  const castPreset = castCombo ? filmCastShift(castCombo.filmCast) : { m: 0, y: 0 }
  const timingDefault = castSelected ? castPreset : { m: 0, y: 0 }
  const timingKey = baseCombo ? `${baseCombo.id}|${castSelected ? 'film-cast' : 'neutral'}` : ''
  const timingValue = (timingKey && timingStore[timingKey]) || timingDefault
  const timingM = timingValue.m, timingY = timingValue.y
  const setTiming = (next: Partial<{ m: number; y: number }>) => {
    if (!timingKey) return
    setTimingStore(store => ({ ...store, [timingKey]: { ...((store[timingKey]) || timingDefault), ...next } }))
  }
  const resetTiming = () => setTimingStore(store => { const next = { ...store }; delete next[timingKey]; return next })
  const onCastPreset = castSelected && sameShift({ m: timingM, y: timingY }, castPreset)
  const onNeutral = sameShift({ m: timingM, y: timingY }, { m: 0, y: 0 })
  const activeCombo = suppliedLook ? suppliedCombination(suppliedLook, catalog!.suppliedFuji!.cameraId) : onCastPreset ? castCombo : baseCombo
  function chooseFilmCast(on: boolean) { setFilmCastOn(on); setNotice('') }
  const builtinSample = catalog?.samples.find(s => s.id === sampleId) || catalog?.samples[0] || null
  const previewCameraId = previewCameraFor(builtinSample, !!activePhoto, exportCameraId)
  const camera = catalog?.cameraAdapters?.models.find(model => model.id === exportCameraId)
  const previewCamera = catalog?.cameraAdapters?.models.find(model => model.id === previewCameraId)
  const stdAsset = selectStdAsset(activeCombo, previewCameraId)
  const timing = usePrintTiming(catalog, baseCombo, timingM, timingY, previewCameraId, !!activeCombo && activeCombo.processMode === 'negative_print', onCastPreset || onNeutral)
  const blockedReason = previewCameraId === UNSUPPORTED_L10 ? t("DMC-L10용 STD 변환은 없습니다. DC-L10과 다른 카메라이므로 미리보기를 적용하지 않습니다.")
    : activeCombo && !stdAsset ? t("이 카메라용 STD LUT가 준비되지 않았습니다.") : undefined
  const samplePhoto = useSamplePhoto(view === 'studio' && !activePhoto ? builtinSample : null)
  const photoLook = usePhotoLook(activePhoto || samplePhoto.photo, view === 'studio' && activeCombo?.status === 'ready' && !blockedReason ? (timing.active ? timing.preview : stdAsset) : undefined)
  useEffect(() => {
    const target = previewPanel.current?.querySelector('.preview')
    if (!target || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver(([entry]) => setPreviewOffscreen(!entry.isIntersecting), { threshold: 0.15 })
    observer.observe(target)
    return () => observer.disconnect()
  }, [view, photoLook.path, catalog])
  const processingError = timing.error || (!activePhoto ? samplePhoto.error : undefined) || photoLook.error
  const retryPreview = () => { if (!activePhoto && samplePhoto.error) samplePhoto.retry(); else photoLook.retry() }

  useEffect(() => {
    const controller = new AbortController()
    setLoadError('')
    fetch('/catalog.json', { signal: controller.signal }).then(async r => {
      if (!r.ok) throw new Error(`카탈로그를 불러올 수 없습니다 (${r.status})`)
      const data = await r.json() as Catalog
      if (data.schemaVersion !== 2 || !data.films.length || !data.papers.length || !data.combinations.length) throw new Error('지원하지 않는 카탈로그입니다.')
      const combinations = data.combinations.filter(c => c.processMode !== 'reference_interpretation')
      if (!data.cameraAdapters?.models.length || combinations.some(c => c.status === 'ready' && !selectStdAsset(c, data.cameraAdapters!.defaultCamera))) throw new Error('카메라별 STD LUT 파일 정보를 확인하지 못했습니다. 다시 불러와 주세요.')
      const counts = Object.fromEntries(Object.keys(data.counts).map(status => [status, combinations.filter(c => c.status === status).length]))
      if (controller.signal.aborted) return
      const initialCamera = data.cameraAdapters.models.some(model => model.id === cameraId) ? cameraId : data.cameraAdapters.defaultCamera
      setCameraId(initialCamera)
      const initialSample = sampleForCamera(data.samples, DEFAULT_CAMERA) || data.samples[0]
      setSampleId(initialSample.id)
      setCatalog({ ...data, combinations, counts, referenceStudy: undefined })
    }).catch(e => { if (e.name !== 'AbortError') setLoadError(e instanceof SyntaxError ? '카탈로그 형식을 읽지 못했습니다. 다시 불러와 주세요.' : e.message) })
    return () => controller.abort()
  }, [attempt])

  useEffect(() => {
    const syncView = () => setView(viewFromHash())
    window.addEventListener('hashchange', syncView)
    return () => window.removeEventListener('hashchange', syncView)
  }, [])
  function navigate(next: View, scrollToTop = true) {
    setView(next)
    window.location.hash = next
    if (scrollToTop) window.scrollTo({ top: 0, behavior: 'instant' })
  }
  function useGalleryLook(photo: GalleryPhoto) {
    setFilmId(photo.filmId)
    if (photo.paperId) setPaperId(photo.paperId)
    const recorded = catalog?.combinations.find(combo => combo.id === photo.combinationId)
    const useCast = !!recorded?.castBaseId && recorded.film !== catalog?.filmCast?.referenceFilm
    setNegativeMode('negative_print'); setFilmCastOn(useCast)
    // Reopen the recorded preset even if this look was fine-tuned in the studio.
    if (recorded?.processMode === 'negative_print') {
      const key = (recorded.castBaseId || recorded.id) + '|' + (useCast ? 'film-cast' : 'neutral')
      setTimingStore(store => {
        if (!(key in store)) return store
        const next = { ...store }; delete next[key]; return next
      })
    }
    setCameraId(photo.cameraId)
    const nextSample = sampleForCamera(catalog?.samples || [], photo.cameraId) || catalog?.samples[0]
    if (nextSample) setSampleId(nextSample.id)
    setMode('compare'); setNotice(''); setFormat('std')
    try { window.localStorage.setItem(CAMERA_STORAGE_KEY, photo.cameraId) } catch { /* Keep selection without storage. */ }
    navigate('studio')
    window.requestAnimationFrame(() => previewPanel.current?.focus({ preventScroll: true }))
  }

  async function downloadTiming(filename: string) {
    setDownloading(true); setNotice('')
    try {
      if (format === 'zip') throw new Error('인화 필터를 조정한 LUT는 STD 또는 V-Log 파일로 내려받을 수 있습니다.')
      const text = await timing.bake(format, exportCameraId)
      const url = URL.createObjectURL(new Blob([text], { type: 'text/plain' }))
      const a = document.createElement('a'); a.href = url; a.download = filename; document.body.append(a); a.click(); a.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
      setNotice(`${filename} · 인화 필터 조정값으로 만든 파일을 다운로드했습니다.`)
    } catch (e) { setNotice(e instanceof Error ? e.message : '다운로드하지 못했습니다.') }
    finally { setDownloading(false) }
  }

  async function download(asset: Asset, filename: string) {
    setDownloading(true); setNotice('')
    try {
      const verified = await fetchVerifiedAsset(asset)
      const buffer = format === 'zip' && combo.files ? renameZipEntries(verified, {
        [selectStdAsset(combo, exportCameraId)!.name]: downloadFilename(film, combo.paper ? paper : undefined, combo.processMode, 'std', exportCameraId, !!combo.castBaseId),
        [combo.files.vlog.name]: downloadFilename(film, combo.paper ? paper : undefined, combo.processMode, 'vlog', exportCameraId, !!combo.castBaseId),
      }) : verified
      const url = URL.createObjectURL(new Blob([buffer], { type: asset.name.endsWith('.zip') ? 'application/zip' : 'text/plain' }))
      const a = document.createElement('a'); a.href = url; a.download = filename; document.body.append(a); a.click(); a.remove()
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
      setNotice(`${filename} · 검증된 파일을 다운로드했습니다.`)
    } catch (e) { setNotice(e instanceof Error ? e.message : '다운로드하지 못했습니다.') }
    finally { setDownloading(false) }
  }

  if (!localeReady) return <main className="initial-state" aria-busy="true"><h1>sosang<span className="brand-period">.</span></h1><p role="status">…</p></main>
  if (!catalog) return <main className="initial-state"><h1>sosang<span className="brand-period">.</span></h1><p role="status">{message(loadError) || t("필름 실험실을 준비하고 있습니다.")}</p>{loadError && <button onClick={() => setAttempt(n => n + 1)}>{t("다시 불러오기")}</button>}</main>
  const film = selectedFilm!
  const paper = selectedPaper!
  const isSlide = film.type === 'positive'
  const isDigital = processMode !== 'negative_print' && processMode !== 'official_print'
  const isNegativeDigital = processMode === 'negative_digital'
  const combo: Combination = activeCombo || { id: `${film.id}__${processMode}`, film: film.id, paper: isDigital ? null : paper.id, processMode, number: 0, status: 'not-generated', reason: t("선택한 처리 방식의 LUT가 아직 준비되지 않았습니다.") }
  const castActive = castSelected
  const castLabel = t("추천 현상 방법")
  const timingLabel = timing.active ? `M ${formatShift(timing.total.m)} · Y ${formatShift(timing.total.y)} CC` : ''
  const processLabel0 = isSupplied ? t("후지 필름 시뮬레이션 · 인화지 없음") : isSlide ? t("인화지 없음 · 슬라이드 직접 스캔") : isNegativeDigital ? t("sosang 디지털 변환 · 실험") : onCastPreset ? `${paperLabel(paper)} · ${castLabel}` : paperLabel(paper)
  const processLabel = timingLabel ? `${processLabel0} · ${timingLabel}` : processLabel0
  const referenceLabel = isNegativeDigital ? t("디지털 변환 기준") : t("직접 엔진")
  const sample = activePhoto?.sample || builtinSample!
  const resultPath = photoLook.path
  if (resultPath) miniFrame.current = resultPath
  const miniSrc = resultPath ?? miniFrame.current
  const publishedAsset = selectDownloadAsset(combo, format, exportCameraId)
  const selectedAsset = timing.active ? (format === 'zip' ? undefined : publishedAsset) : publishedAsset
  const publishedFilename = downloadFilename(film, combo.paper ? paper : undefined, combo.processMode, format, camera?.name || exportCameraId, !!combo.castBaseId)
  const selectedFilename = timing.active && format !== 'zip' ? publishedFilename.replace(/(VLOG)?\.cube$/, `${shiftCode(timing.total.m, timing.total.y)}$1.cube`) : publishedFilename
  const castIsReference = baseCombo?.film === catalog.filmCast?.referenceFilm
  const castDescription = !castCombo ? t("이 조합에는 추천 현상 방법 LUT가 없습니다.") : t("Portra 400은 기준 필름이라 중립 현상과 색이 같습니다.")
  const stdLabel = `${camera?.name || '—'} · STD`
  const previewStdLabel = `${previewCamera?.name || '—'} · STD`
  const selectedQa = selectStdQa(combo, exportCameraId)
  const stdMetric = selectedQa.metric
  const stdWarnings = selectedQa.warnings
  const filtered = libraryFilms.filter(f => (brand === '모두' || f.brand === brand) && f.name.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => (a.id === 'kodak_portra_400' ? -1 : b.id === 'kodak_portra_400' ? 1
      : Number(a.type === 'supplied') - Number(b.type === 'supplied') || a.brand.localeCompare(b.brand) || a.name.localeCompare(b.name)))
  const formatName = format === 'vlog' ? 'V-Log' : format === 'std' ? stdLabel : `${camera?.name || '—'} STD + V-Log`
  function chooseCamera(id: string) {
    setCameraId(id); setNotice('')
    try { window.localStorage.setItem(CAMERA_STORAGE_KEY, id) } catch { /* Keep selection without storage. */ }
  }
  function chooseSample(id: string) { setSampleId(id); setNotice('') }
  function selectFilm(id: string) {
    setFilmId(id); setNotice('')
    if (suppliedLooks.some(look => look.stock.id === id)) setFormat('std')
    if (window.matchMedia('(max-width: 650px)').matches) previewPanel.current?.scrollIntoView({ block: 'start' })
  }

  return <>
    <header className="topbar"><div className="topbar-left"><a className="brand-link" href="#studio" onClick={event => { event.preventDefault(); navigate('studio') }} aria-label={t("sosang 홈")}><span className="brand-word">sosang<span className="brand-period">.</span></span><span className="brand-descriptor">{t("컬러 스튜디오")}</span></a><nav className="site-nav" aria-label={t("주요 메뉴")}><a href="#studio" aria-current={view === 'studio' ? 'page' : undefined} onClick={event => { event.preventDefault(); navigate('studio') }}>{t("스튜디오")}</a><a href="#gallery" aria-current={view !== 'studio' ? 'page' : undefined} onClick={event => { event.preventDefault(); navigate('gallery') }}>{t("갤러리")}</a></nav></div><div className="topbar-right"><div className="locale-switch" role="group" aria-label={t("언어 선택")}><button type="button" aria-label={t("한국어로 전환")} aria-pressed={locale === 'ko'} className={locale === 'ko' ? 'active' : ''} onClick={() => setLocale('ko')}>KO</button><button type="button" aria-label={t("영어로 전환")} aria-pressed={locale === 'en'} className={locale === 'en' ? 'active' : ''} onClick={() => setLocale('en')}>EN</button></div><button className="about-button" aria-label={t("제작 정보")} onClick={() => dialog.current?.showModal()}><Icon name="info" size={17}/><span>{t("제작 정보")}</span></button></div></header>
    <main className={view !== 'studio' ? 'gallery-main' : undefined}>
      {view !== 'studio' ? <FilmGallery catalog={catalog} t={t} collection={view === 'gallery/recommended' ? 'recommended' : 'examples'} onSelectCollection={next => navigate(next === 'recommended' ? 'gallery/recommended' : 'gallery', false)} onUseLook={useGalleryLook}/> : <>
      <div className="intro"><div className="studio-title"><h1>{t("스튜디오")}</h1><LutUsageGuide locale={locale} t={t}/></div><div className="catalog-stat"><b>{catalog.counts.ready + suppliedLooks.length}</b><span>{t("가지 컬러 조합")}<small>33³ LUT · sRGB</small></span></div></div>
      <div className="workspace">
        <aside id="film-library" className="film-library" ref={filmLibrary} tabIndex={-1} aria-label={t("필름 선택")}>
          <div className="section-label"><span>{t("필름 & 인화지")}</span><small>{libraryFilms.length}</small></div><p className="library-description">{t("필름 프로파일과 후지 필름 시뮬레이션")}</p>
          <label className="search-field"><Icon name="search" size={16}/><input placeholder={t("필름 검색")} aria-label={t("필름 검색")} value={search} onChange={e => setSearch(e.target.value)}/>{search && <button aria-label={t("검색 지우기")} onClick={() => setSearch('')}><Icon name="close" size={14}/></button>}</label>
          <div className="brand-filters" aria-label={t("필름 브랜드")}>{['모두','Kodak','Fujifilm'].map(b => <button key={b} aria-pressed={brand === b} className={brand === b ? 'active' : ''} onClick={() => setBrand(b)}>{t(b)}</button>)}</div>
          <div className="film-list">{filtered.length ? filtered.map(f => <button key={f.id} className={`film-option ${f.id === film.id ? 'selected' : ''}`} aria-pressed={f.id === film.id} onClick={() => selectFilm(f.id)}><FilmCanister stock={f}/><span className="film-copy"><small>{f.brand.toUpperCase()}</small><strong>{shortName(f.name)}</strong><span>{f.type === 'supplied' ? t("필름 시뮬레이션 · STD") : f.type === 'positive' ? t("슬라이드 · 직접 스캔") : f.use === 'movie' ? t("컬러 네거티브 · 시네마") : t("컬러 네거티브")}</span></span>{f.id === film.id && <span className="selected-check"><Icon name="check" size={12}/></span>}</button>) : <div className="no-results">{t("검색 결과가 없습니다.")}<button onClick={() => { setSearch(''); setBrand('모두') }}>{t("모든 필름 보기")}</button></div>}</div>
          <div className="library-foot"><Icon name="film" size={16}/><span><a href="https://github.com/andreavolpato/spektrafilm" target="_blank" rel="noreferrer">spektrafilm ↗</a></span></div>
        </aside>

        <section className="preview-panel" ref={previewPanel} tabIndex={-1} aria-label={t("룩 미리보기")}>
          <div className="preview-heading"><div><span className="eyebrow">{isSupplied ? t("FUJIFILM 시뮬레이션") : film.brand.toUpperCase()}</span><div className="film-title-row"><h2>{shortName(film.name)}</h2><WhiteBalanceGuide locale={locale} t={t}/></div><p className="selected-paper">{isDigital ? (isSupplied ? t("STD LUT · 인화지 없음") : isSlide ? t("슬라이드 직접 스캔") : t("디지털 스캔 · 실험")) : `+ ${paperLabel(paper, true)}`}</p>{onCastPreset && <p className="film-cast-badge">{castLabel}</p>}{timing.active && <p className="film-cast-badge">{t("인화 필터 조정 · {0}", [timingLabel])}</p>}</div><button className="upload-button" disabled={upload.loading} onClick={() => fileInput.current?.click()}><Icon name="upload" size={16}/><span>{upload.loading ? t("읽는 중…") : upload.photo ? t("사진 바꾸기") : t("사진 업로드")}</span></button></div>
          <div className="camera-input-panel"><Icon name="camera" size={19}/><p>{activePhoto ? t("업로드 사진에는 LUT 내보내기에서 선택한 카메라의 STD LUT를 적용합니다.") : sample.inputKind === 'synthetic-srgb' ? t("sRGB 테스트 패턴 · S1II STD 기준") : t("해당 STD 촬영본은 S1II에서 촬영되었습니다.")}</p></div>
          <div className="preview-toolbar"><button className="film-jump" aria-controls="film-library" aria-label={t("필름 선택")} onClick={() => { filmLibrary.current?.focus({ preventScroll: true }); filmLibrary.current?.scrollIntoView({ block: 'start' }) }}>{t("필름 고르기")}<Icon name="chevron" size={13}/></button><span className="preview-status"><i className={combo.status === 'ready' && !blockedReason ? 'live-dot' : 'muted-dot'}/>{combo.status === 'ready' && !blockedReason ? previewStdLabel : t("미지원 / 미생성")}</span><div className="view-switch"><button title={t("원본 보기")} aria-label={t("원본 보기")} aria-pressed={mode === 'original'} className={mode === 'original' ? 'active' : ''} onClick={() => setMode('original')}>{t("원본")}</button><button title={t("비교 보기")} aria-label={t("비교 보기")} aria-pressed={mode === 'compare'} className={mode === 'compare' ? 'active' : ''} onClick={() => setMode('compare')}><Icon name="compare" size={16}/>{t("비교")}</button><button title={t("적용 결과만 보기")} aria-label={t("적용 결과만 보기")} aria-pressed={mode === 'look'} className={mode === 'look' ? 'active' : ''} onClick={() => setMode('look')}>{t("적용")}</button></div></div>
          <Preview locale={locale} t={t} key={`${combo.id}-${previewCameraId}-${timing.active ? timing.preview?.key ?? 'timing' : stdAsset?.sha256}-${sample.id}-${resultPath || processingError || 'pending'}`} sample={sample} combo={combo} blockedReason={blockedReason} mode={mode} resultPath={resultPath} processingError={processingError} retry={retryPreview} lookLabel={`${film.name} · ${processLabel} · ${previewStdLabel}`}/>
          <div className="preview-caption"><span>{sampleText(sample, 'category', locale)}</span><span>{blockedReason ? t("LUT 미적용 · 원본만 표시") : combo.status !== 'ready' ? t("선택한 룩의 준비 상태를 확인해 주세요") : mode === 'compare' ? t("경계를 드래그해 비교하세요 ↔") : mode === 'original' ? t("LUT 적용 전 원본") : t("다운로드용 STD LUT · 100% 적용")}</span></div>
          <div className={`photo-upload ${dragging ? 'dragging' : ''}`} onDragOver={e => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; setDragging(true) }} onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false) }} onDrop={e => { e.preventDefault(); setDragging(false); const file = e.dataTransfer.files[0]; if (file) void upload.upload(file) }}>
            <input ref={fileInput} className="file-input" type="file" accept={PHOTO_ACCEPT} aria-label={t("사진 파일 선택")} onChange={e => { const file = e.target.files?.[0]; e.target.value = ''; if (file) void upload.upload(file) }}/>
            <p className="upload-hint"><Icon name="upload" size={15}/><span>{t("여기에 사진을 놓아보세요")} <small>{t("JPG · PNG · WebP / 최대 30 MB · 기기 안에서 처리")}</small></span></p>
            {upload.photo && <div className="uploaded-photo"><button className={`uploaded-choice ${activePhoto ? 'selected' : ''}`} aria-pressed={!!activePhoto} onClick={() => { setSampleId('@upload') }}><img src={upload.photo.sample.path} alt=""/><span><strong>{upload.photo.sample.name}</strong><small>{upload.photo.originalWidth} × {upload.photo.originalHeight} {t("· 미리보기")} {upload.photo.sample.width} × {upload.photo.sample.height}</small></span>{activePhoto && <Icon name="check" size={15}/>}</button><button className="remove-photo" aria-label={t("업로드한 사진 제거")} onClick={() => { upload.clear(); if (activePhoto) chooseSample(catalog.samples[0].id) }}><Icon name="close" size={16}/></button></div>}
            <p className="upload-error" role="alert">{message(upload.error)}</p>
            <span className="sr-only" role="status">{upload.loading ? t("사진을 읽고 있습니다.") : upload.photo ? t("{0} 사진을 불러왔습니다.", [upload.photo.sample.name]) : ''}</span>
          </div>
          <div className="samples-heading"><span className="section-label">{t("샘플로 둘러보기")}</span><span>{t("직접 촬영 · Standard / LUT OFF")}</span></div>
          <div className="sample-grid">{catalog.samples.map(s => <button key={s.id} className={`sample-option ${sample.id === s.id ? 'selected' : ''}`} aria-pressed={sample.id === s.id} onClick={() => chooseSample(s.id)}><div><img src={s.thumbnailPath || s.path} alt="" loading="lazy"/>{sample.id === s.id && <span><Icon name="check" size={12}/></span>}</div><strong>{sampleText(s, 'name', locale)}</strong></button>)}</div>
          <div className="preview-note"><Icon name="info" size={15}/><p>{blockedReason ? t("카메라 입력을 확인하기 전에는 LUT를 적용하지 않습니다. 현재 사진은 원본입니다.") : activePhoto ? t("선택한 카메라의 STD LUT를 100% 적용합니다. 미리보기는 최대 2,048px입니다.") : sample.inputKind === 'synthetic-srgb' ? t("sRGB 테스트 패턴 · S1II STD 기준") : sample.inputKind === 'review-jpeg' ? t("리뷰 JPG에 선택한 다운로드용 STD LUT를 100% 적용합니다.") : t("Standard 샘플에는 S1II STD LUT를 100% 적용합니다.")} <button onClick={() => dialog.current?.showModal()}>{t("생성 방식")}</button></p></div>
          {sample.inputKind !== 'review-jpeg' && <div className="sample-credit">{sampleText(sample, 'credit', locale)}{sample.source && <a href={sample.source} target="_blank" rel="noreferrer">{t("출처")} <Icon name="external" size={10}/></a>}</div>}
        </section>

        <aside className="recipe-panel" aria-label={t("처리 방식과 다운로드")}>
          <div className="paper-section"><div className="section-label"><span>{t("처리 방식")}</span><small>{isSupplied ? 'FUJI LUT' : isDigital ? 'SCAN' : 'PRINT'}</small></div>
            {!isSupplied && <fieldset className="process-switch"><legend className="sr-only">{t("처리 방식 선택")}</legend>
              <label className={`process-option ${!isDigital ? 'selected' : ''}`}><input type="radio" name="process-mode" value="negative_print" aria-label={t("인화지 인화")} disabled={isSlide} checked={!isDigital} onChange={() => { setNegativeMode('negative_print'); setNotice('') }}/><span>{t("인화지 인화")}</span></label>
              <label className={`process-option ${isDigital ? 'selected' : ''}`}><input type="radio" name="process-mode" value="digital_scan" aria-label={t("디지털 스캔")} checked={isDigital} onChange={() => { if (!isSlide) setNegativeMode('negative_digital'); setNotice('') }}/><span>{t("디지털 스캔")}</span></label>
            </fieldset>}
            {isDigital ? <div className={`direct-scan-note ${isNegativeDigital ? 'experimental-scan' : ''}`} role="status"><Icon name={isSupplied ? 'camera' : 'film'} size={22}/><strong>{processLabel}</strong><p>{isSupplied ? t("제공된 STD LUT를 그대로 적용합니다.") : isSlide ? t("슬라이드는 현상한 필름 자체를 스캔합니다. 인화지 프로파일은 적용하지 않습니다.") : t("인화지 없이 네거티브를 양화로 바꾸는 sosang의 실험 모드입니다.")}</p></div> : <p className="section-description">{t("인화지 · 프린트 필름")}</p>}
            {!isSupplied && <fieldset className="paper-fieldset" disabled={isDigital} aria-label={isDigital ? t("인화지·프린트 필름 선택 (직접 출력에서는 사용하지 않음)") : t("인화지·프린트 필름")}><div className="paper-list" role="radiogroup" aria-label={t("인화지·프린트 필름")}>{catalog.papers.map(p => <label className={`paper-option ${!isDigital && p.id === paper.id ? 'selected' : ''}`} key={p.id}><input type="radio" name="paper" value={p.id} checked={!isDigital && p.id === paper.id} onChange={() => { setPaperId(p.id); setNotice('') }}/><span className="paper-radio"/><span><strong>{paperLabel(p, true)}</strong><small>{/2383|2393/.test(p.id) ? t("영화용 프린트 필름") : p.brand} {!isDigital && p.id === film.recommendedPrint && <em>{t("권장 조합")}</em>}</small></span></label>)}</div></fieldset>}
            {!isDigital && !isSupplied && <fieldset className="film-cast-switch"><legend className="section-description method-legend"><span>{t("현상 방법")}</span><button type="button" className="method-info-button" aria-label={t("현상 방법 설명")} aria-expanded={methodInfo} onClick={() => setMethodInfo(v => !v)}><Icon name="info" size={15}/></button></legend>{methodInfo && <div className="method-info-layer" role="dialog" aria-label={t("현상 방법 설명")}><button type="button" className="method-info-close" aria-label={t("닫기")} onClick={() => setMethodInfo(false)}>×</button><h4>{t("중립 현상 방법")}</h4><p>{t("18% 회색이 R·G·B 값이 같은 회색으로 나오도록 필름·인화지마다 인화 필터를 맞춘 그레이 밸런스 버전입니다. 그래서 같은 인화지에서는 필름 간 색 차이가 작아집니다.")}</p><h4>{t("추천 현상 방법")}</h4><p><>{t("현상소가 모든 필름을 같은 기준 필터(Portra 400)로 인화한 것처럼, 필름이 원래 가진 색 기운을 조금 남긴 버전입니다. 18% 회색에 남는 색의 세기는 필름마다 비슷하게 맞췄고, 색의 방향은 대부분 필름 데이터가 정합니다.")}{castCombo?.filmCast && <> {castIsReference ? t("Portra 400은 기준 필름이라 중립 현상과 색이 같습니다.") : castCombo.filmCast.directionPolicy === 'editorial-hue' ? t("이 필름은 필름 데이터대로면 알려진 색과 다른 쪽으로 남아서, 알려진 느낌에 맞춰 {0} 쪽으로 방향을 정했습니다.", [t(castDirection(castCombo.filmCast.grayHue))]) : t("이 조합은 {0} 쪽으로 남습니다.", [t(castDirection(castCombo.filmCast.grayHue))])}</>}</></p><h4>{t("슬라이더 원리")}</h4><p>{t("슬라이더 값은 중립 현상 방법 기준의 인화 필터 이동량(Kodak CC)으로, spektrafilm GUI의 Print M·Y filter shift와 같습니다. 그 필터를 더 넣으면(+) 그 색이 빠집니다. ±{0} CC 안에서 미리 계산한 9개 지점을 보간합니다.", [timing.span])}</p></div>}
              <label className={`cast-option ${!castActive ? 'selected' : ''}`}><input type="radio" name="film-cast" value="neutral" checked={!castActive} onChange={() => chooseFilmCast(false)}/><span className="paper-radio"/><span><strong>{t("중립 현상 방법")}</strong></span></label>
              <label className={`cast-option ${castActive ? 'selected' : ''} ${castLocked ? 'unavailable' : ''}`}><input type="radio" name="film-cast" value="film-cast" disabled={castLocked} checked={castActive} onChange={() => chooseFilmCast(true)}/><span className="paper-radio"/><span><strong>{castLabel}</strong>{castLocked && <small>{castDescription}</small>}</span></label>
            </fieldset>}
            {!isDigital && !isSupplied && timing.available && <fieldset className="timing-panel"><legend className="section-description">{t("인화 필터 미세 조정 · 실험")}</legend>
              {(['M', 'Y'] as const).map(channel => { const value = channel === 'M' ? timingM : timingY, set = (v: number) => setTiming(channel === 'M' ? { m: v } : { y: v })
                return <label className="timing-row" key={channel}><span className={`timing-channel timing-${channel.toLowerCase()}`}>{channel}</span><input type="range" min={-timing.span} max={timing.span} step={0.1} value={value} aria-label={t("{0} 필터 이동 (Kodak CC)", [channel])} onChange={e => { set(Number(e.target.value)); setNotice('') }}/><output>{formatShift(value)}</output></label> })}
              <div className="timing-actions"><small>{timing.loading ? t("조정값으로 LUT를 계산하는 중…") : timing.active ? t("최종 필터 이동: {0}", [timingLabel]) : null}</small><button type="button" disabled={castSelected ? onCastPreset : onNeutral} onClick={() => { resetTiming(); setNotice('') }}>{t("초기화")}</button></div>
              <p className="film-cast-note">{t("미리보기와 다운로드 LUT에 바로 반영됩니다. 값은 새로고침 전까지 조합마다 기억합니다.")}</p>
              {timing.active && format === 'zip' && <p className="film-cast-note">{t("인화 필터를 조정한 LUT는 STD 또는 V-Log 파일로 내려받을 수 있습니다.")}</p>}
            </fieldset>}
            {!isDigital && !castActive && <p className="paper-balance-note">{t("중간 회색을 맞추는 인화 보정으로 같은 인화지의 필름 룩은 비슷해질 수 있습니다.")} <button onClick={() => dialog.current?.showModal()}>{t("생성 기준 보기")}</button></p>}
          </div>
          <div className="export-section">{previewOffscreen && miniSrc && <button type="button" className="mini-preview" onClick={() => previewPanel.current?.scrollIntoView({ block: 'start', behavior: 'smooth' })} aria-label={t("미리보기로 돌아가기")}><img src={miniSrc} alt=""/><span>{t("미리보기")}</span></button>}<div className="section-label"><span>{t("LUT 내보내기")}</span><Icon name="download" size={16}/></div><div className="export-spec"><span>{t("출력")} <b>sRGB</b></span><span>{t("격자")} <b>33 × 33 × 33</b></span></div>
            <div className="export-camera-control"><label className="output-label" htmlFor="export-camera">{t("카메라 선택")}</label><select id="export-camera" value={exportCameraId} disabled={format === 'vlog' || isSupplied} onChange={event => chooseCamera(event.target.value)}>{catalog.cameraAdapters?.models.filter(model => !isSupplied || model.id === exportCameraId).map(model => <option key={model.id} value={model.id}>{model.name}{model.cameraUse === 'post-only' ? ' · ' + t("편집용") : ''}</option>)}</select></div>
            {isSupplied && <p className="reference-export-note">{t("이 후지 LUT는 S1II Standard용 파일입니다.")}</p>}
            {!isSupplied && camera?.cameraUse === 'post-only' && format !== 'vlog' && <p className="reference-export-note">{t("이 모델의 STD LUT는 편집 프로그램용입니다. 카메라 내 LUT 적용 지원을 뜻하지 않습니다.")}</p>}
            <label className="output-label" htmlFor="output-format">{t("파일 형식")}</label><select id="output-format" value={format} onChange={e => { setFormat(e.target.value as typeof format); setNotice('') }}><option value="std">{`${stdLabel} (.cube)`}</option>{!isSupplied && <><option value="vlog">V-Log / V-Gamut (.cube)</option><option value="zip">{t("카메라별 STD + V-Log (ZIP)")}</option></>}</select>
            <p className="export-process">{shortName(film.name)} <span>· {isDigital ? t("인화지 없음") : paperLabel(paper, true)}</span><code className="export-filename">{selectedFilename}</code></p>
            <button className="download-button" aria-label={t("{0} LUT 다운로드", [`${processLabel} · ${formatName}`])} title={selectedFilename} disabled={!selectedAsset || combo.status !== 'ready' || downloading} onClick={() => selectedAsset && void (timing.active ? downloadTiming(selectedFilename) : download(selectedAsset, selectedFilename))}><Icon name="download" size={18}/><span>{downloading ? t("파일 검증 중…") : combo.status === 'ready' ? t("LUT 다운로드") : t("다운로드 준비 전")}</span>{!downloading && <Icon name="arrow" size={17}/>}</button>
            <div className="download-meta">{selectedAsset ? <><span>{formatName}</span><span>{sizeLabel(selectedAsset.bytes)}</span></> : <span>{combo.status === 'unsupported' ? t("이 조합은 지원하지 않습니다.") : t("생성된 파일이 없습니다.")}</span>}</div>
            <p className="download-notice" role="status" aria-live="polite">{message(notice)}</p>
            <div className="camera-notice"><button onClick={() => dialog.current?.showModal()}><Icon name="info" size={16}/><span>{t("출처/라이선스")}</span></button></div>
          </div>
        </aside>
      </div>
      <footer className="page-footer"><span>sosang</span><p>{isSupplied ? t("후지 필름 시뮬레이션 · 제공된 STD LUT") : <>spektrafilm / Andrea Volpato · V-Log Alchemy / shenmintao</>}</p><button onClick={() => dialog.current?.showModal()}>{t("출처/라이선스")} <Icon name="external" size={12}/></button></footer>
      </>}
    </main>

    <dialog ref={dialog} className="details-dialog" onClick={e => { if (e.target === dialog.current) dialog.current?.close() }}>
      <div className="dialog-inner"><div className="dialog-heading"><div><span className="eyebrow">sosang</span><h2>{t("출처/라이선스")}</h2></div><button className="icon-button" onClick={() => dialog.current?.close()} aria-label={t("상세 정보 닫기")}><Icon name="close"/></button></div>
      <p className="detail-intro">{film.name} · {processLabel}</p>
      {isSupplied ? <>
        <h3>{t("후지 필름 시뮬레이션 · 제공된 STD LUT")}</h3><p>{t("ALL_FUJI_LUT 폴더에서 제공된 S1II Standard용 LUT입니다. RGB 데이터는 변경하지 않고 카메라 포토스타일과 기본 입력 범위 헤더만 명시했습니다.")}</p>
        <dl className="details-grid"><dt>{t("원본 LUT")}</dt><dd>{suppliedLook.sourceFile}</dd><dt>SHA-256</dt><dd><code>{suppliedLook.sourceSha256}</code></dd></dl>
        <p>{t("이 파일들은 사용자 제공 LUT이며 FUJIFILM 공식 원본 배포본으로 표시하지 않습니다. 별도 저작자·이용허락 정보는 제공되지 않았습니다.")}</p>
        <div className="detail-links"><a href={catalog.suppliedFuji?.provenance.path} target="_blank" rel="noreferrer">{t("파일 출처 · 해시 ↗")}</a><a href={catalog.suppliedFuji?.notice.path} target="_blank" rel="noreferrer">{t("이용 안내 ↗")}</a></div>
      </> : <>
        <h3>spektrafilm · Andrea Volpato</h3><p>{t("필름·인화지 프로파일은 spektrafilm에서 파생했습니다. 원본 라이선스와 생성 정보는 LUT 패키지에 포함됩니다.")}</p>
        <h3>V-Log Alchemy · shenmintao</h3><p>{t("선택한 카메라의 Standard → V-Log 변환과 필름·인화지 V-Log LUT를 합성합니다. 내보내는 STD 파일은 선택한 카메라에 맞춰집니다.")}</p><code>{catalog.cameraAdapters?.commit}</code>
        <p>{t("Standard의 클리핑과 색역 압축은 완전히 역변환할 수 없습니다. 잘린 하이라이트와 색은 복원하지 못합니다.")}</p>
        {combo.qa && <details><summary>{t("측정된 보간 오차")}</summary><p>{t("STD 합성 파일과 카메라 변환·V-Log 룩을 순서대로 적용한 결과의 출력 sRGB 오차입니다. 카메라나 실제 필름의 색 일치를 나타내는 점수가 아닙니다.")}</p><table><thead><tr><th>{t("비교")}</th><th>{t("평균")}</th><th>{t("99백분위")}</th><th>{t("최대")}</th></tr></thead><tbody>{[[`V-Log ↔ ${referenceLabel}`,combo.qa.vlogVsDirectEngine.tetrahedral],...(stdMetric ? [[t("STD 합성 ↔ 순차 적용 · 사면체"),stdMetric.tetrahedral],[t("STD 합성 ↔ 순차 적용 · 삼선형"),stdMetric.trilinear]] : [])].map(([name,m]) => { const metric = m as { mean: number; p99: number; max: number }; return <tr key={String(name)}><td>{String(name)}</td><td>{metric.mean.toFixed(5)}</td><td>{metric.p99.toFixed(5)}</td><td>{metric.max.toFixed(5)}</td></tr> })}</tbody></table>{stdWarnings.map(w => <p key={w}>{message(w)}</p>)}</details>}
        <div className="detail-links"><a href="https://github.com/andreavolpato/spektrafilm" target="_blank" rel="noreferrer">spektrafilm ↗</a><a href={catalog.cameraAdapters?.sourceUrl} target="_blank" rel="noreferrer">V-Log Alchemy ↗</a><a href="/licenses/SPEKTRAFILM_LICENSE.txt" target="_blank" rel="noreferrer">{t("spektrafilm 라이선스 ↗")}</a><a href="/camera-adapters/V-Log-Alchemy-LICENSE.txt" target="_blank" rel="noreferrer">{t("카메라 변환 라이선스 ↗")}</a>{combo.files && <><a href={combo.files.qa.path} target="_blank" rel="noreferrer">{t("S1II 기본 QA 보고서 ↗")}</a><a href={combo.files.provenance.path} target="_blank" rel="noreferrer">{t("S1II 기본 생성 설정 · 해시 ↗")}</a></>}</div>
      </>}
      <h3>{t("사진과 미리보기")}</h3><p>{t("샘플과 갤러리 사진의 권리는 촬영자에게 있습니다. 샘플 미리보기는 S1II STD 기준이며, 갤러리는 촬영 당시 LUT가 적용된 JPG입니다.")}</p><p>{t("업로드 사진에는 내보내기에서 선택한 카메라의 STD LUT를 적용합니다. 사진은 브라우저 안에서 처리하며 서버에 저장하지 않습니다.")}</p>
      {catalog.sourceCode && <div className="detail-links"><a href={catalog.sourceCode.path} download>{t("sosang 소스 코드 · GPLv3 ↓")}</a></div>}
      </div>
    </dialog>
  </>
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>)
