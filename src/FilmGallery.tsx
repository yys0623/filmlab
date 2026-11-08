import { useEffect, useMemo, useRef, useState } from 'react'
import type { Catalog } from './types'
import type { Translate } from './i18n'
import { PAPER_CODES, paperLabel } from './lutNames'
import './filmGallery.css'

export interface GalleryPhoto {
  id: string; sourceFilename: string; filmId: string; paperId: string | null; combinationId: string
  path: string; thumbnailPath: string; width: number; height: number; cameraId: string; cameraName: string; capturedAt: string
  exif: Record<string, string | number | null>; sourceSha256: string; preparedSha256: string
}
interface GalleryManifest {
  schemaVersion: 1; id: string; cameraName: string; items: GalleryPhoto[]
  counts: { photos: number; films: number }
}

const collections = ['examples', 'recommended'] as const
type Collection = typeof collections[number]
const manifestPaths: Record<Collection, string> = {
  examples: '/gallery/manifest.json',
  recommended: '/gallery/recommended/manifest.json',
}
const shortName = (name: string) => name.replace(/^(Kodak|Fujifilm) (Professional )?/, '')
const safePath = (path: unknown, collection: Collection): path is string =>
  typeof path === 'string' && path.startsWith(collection === 'recommended' ? '/gallery/recommended/' : '/gallery/') && !path.includes('..')

function GalleryImage({ photo, full, t }: { photo: GalleryPhoto; full?: boolean; t: Translate }) {
  const [failed, setFailed] = useState(false)
  return failed ? <span className="gallery-image-error" role="status">{t("사진을 불러오지 못했습니다.")}</span> : <img src={full ? photo.path : photo.thumbnailPath} alt={full ? photo.sourceFilename : ''} width={photo.width} height={photo.height} loading={full ? 'eager' : 'lazy'} decoding="async" onError={() => setFailed(true)}/>
}

export function FilmGallery({ catalog, t, collection, onSelectCollection, onUseLook }: {
  catalog: Catalog; t: Translate; collection: Collection
  onSelectCollection: (next: Collection) => void; onUseLook: (photo: GalleryPhoto) => void
}) {
  const [manifests, setManifests] = useState<Partial<Record<Collection, GalleryManifest>>>({})
  const [failedCollection, setFailedCollection] = useState<Collection | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [filters, setFilters] = useState<Record<Collection, string>>({ examples: 'all', recommended: 'all' })
  const [opened, setOpened] = useState<{ collection: Collection; id: string } | null>(null)
  const lightbox = useRef<HTMLDialogElement>(null)
  const opener = useRef<HTMLButtonElement | null>(null)
  const recommended = collection === 'recommended'
  const manifest = manifests[collection]
  const filmById = useMemo(() => new Map(catalog.films.map(film => [film.id, film])), [catalog])
  const recipeById = useMemo(() => new Map(catalog.combinations.map(combo => [combo.id, combo])), [catalog])

  useEffect(() => {
    if (manifest) return
    const controller = new AbortController()
    setFailedCollection(null)
    fetch(manifestPaths[collection], { signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error('Gallery unavailable')
      const data = await response.json() as GalleryManifest
      if (data.schemaVersion !== 1 || !Array.isArray(data.items) || data.items.length !== data.counts?.photos ||
          data.items.some(item => {
            const recipe = recipeById.get(item.combinationId)
            return !safePath(item.path, collection) || !safePath(item.thumbnailPath, collection) || !item.id ||
              !filmById.has(item.filmId) || !recipe || recipe.status !== 'ready' || recipe.film !== item.filmId || recipe.paper !== item.paperId
          })) throw new Error('Invalid gallery')
      if (!controller.signal.aborted) setManifests(previous => ({ ...previous, [collection]: data }))
    }).catch(() => { if (!controller.signal.aborted) setFailedCollection(collection) })
    return () => controller.abort()
  }, [attempt, collection, manifest, filmById, recipeById])

  const filter = filters[collection]
  const { photos, groups, visible } = useMemo(() => {
    const photos = manifest?.items || []
    const keyOf = (photo: GalleryPhoto) => recommended ? photo.combinationId : photo.filmId
    const groups = new Map<string, { key: string; label: string; count: number }>()
    for (const photo of photos) {
      const key = keyOf(photo), group = groups.get(key)
      if (group) { group.count++; continue }
      const film = filmById.get(photo.filmId)!
      const code = recommended && photo.paperId ? PAPER_CODES[photo.paperId] : null
      groups.set(key, { key, label: shortName(film.name) + (code ? ' · ' + code : ''), count: 1 })
    }
    const ordered = recommended ? [...groups.values()].sort((a, b) => a.label.localeCompare(b.label))
      : catalog.films.map(film => groups.get(film.id)).filter(group => group !== undefined)
    return { photos, groups: ordered, visible: filter === 'all' ? photos : photos.filter(photo => keyOf(photo) === filter) }
  }, [catalog, manifest, recommended, filter, filmById])

  const activeIndex = opened?.collection === collection ? visible.findIndex(photo => photo.id === opened.id) : -1
  const active = visible[activeIndex]
  const activeFilm = active && filmById.get(active.filmId)
  const methodName = (photo: GalleryPhoto) => recipeById.get(photo.combinationId)?.castBaseId ? t("추천 현상 방법") : t("중립 현상 방법")
  const paperName = (photo: GalleryPhoto) => {
    if (!photo.paperId) return t("인화지 없음 · 슬라이드 직접 스캔")
    const paper = catalog.papers.find(item => item.id === photo.paperId)
    return paper ? paperLabel(paper, true) : photo.paperId
  }

  useEffect(() => {
    const element = lightbox.current
    if (!element) return
    if (active && !element.open) element.showModal()
    if (!active && element.open) element.close()
    if (!active) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = previousOverflow }
  }, [active])

  function close() { lightbox.current?.close(); setOpened(null); opener.current?.focus({ preventScroll: true }) }
  function move(delta: number) { if (visible.length) setOpened({ collection, id: visible[(activeIndex + delta + visible.length) % visible.length].id }) }
  const value = (key: string) => active?.exif[key] == null || active.exif[key] === '' ? '—' : String(active.exif[key])
  const aperture = (input: string) => input === '—' ? input : input.startsWith('f/') ? input : `f/${input}`
  const exposure = (input: string) => {
    const number = Number(input)
    return input === '—' ? input : number > 0 && number < 1 ? `1/${Math.round(1 / number)} s` : /s$/.test(input) ? input : `${input} s`
  }
  const selectFilter = (key: string) => setFilters(previous => ({ ...previous, [collection]: key }))
  const tabText = (key: Collection) => key === 'examples' ? t("실촬영 예제") : t("추천 조합")
  const inactiveCollection = recommended ? 'examples' : 'recommended'

  return <section className="film-gallery" aria-labelledby="gallery-title">
    <div className="gallery-intro">
      <h1 id="gallery-title">{t("LUT 적용 예제 갤러리")}</h1>
      <div className="gallery-total"><b>{manifest ? photos.length : '—'}</b><span>{t("장의 실촬영")}<small>{manifest?.cameraName}</small></span></div>
    </div>
    <div className="gallery-tabs" role="tablist" aria-label={t("갤러리 분류")} onKeyDown={event => {
      const next = event.key === 'Home' ? 'examples' : event.key === 'End' ? 'recommended'
        : event.key === 'ArrowLeft' || event.key === 'ArrowRight' ? inactiveCollection : null
      if (next) { event.preventDefault(); onSelectCollection(next); document.getElementById('gallery-tab-' + next)?.focus() }
    }}>
      {collections.map(key => <button key={key} id={'gallery-tab-' + key} role="tab" type="button" aria-controls={'gallery-panel-' + key} aria-selected={key === collection} tabIndex={key === collection ? 0 : -1} onClick={() => onSelectCollection(key)}>{tabText(key)}</button>)}
    </div>
    <div id={'gallery-panel-' + inactiveCollection} role="tabpanel" aria-labelledby={'gallery-tab-' + inactiveCollection} hidden/>
    <div id={'gallery-panel-' + collection} role="tabpanel" aria-labelledby={'gallery-tab-' + collection} tabIndex={0}>
      {failedCollection === collection ? <div className="gallery-state" role="alert"><h2>{t("갤러리를 불러오지 못했습니다.")}</h2><p>{t("연결을 확인하고 다시 시도해 주세요.")}</p><button onClick={() => setAttempt(number => number + 1)}>{t("다시 불러오기")}</button></div>
        : !manifest ? <div className="gallery-state" role="status" aria-busy="true">{t("사진을 불러오는 중…")}</div>
        : !photos.length ? <div className="gallery-state" role="status">{t("아직 등록된 갤러리 사진이 없습니다.")}</div> : <>
        <div className="gallery-filter-bar"><div className={recommended ? 'gallery-filters gallery-pair-filters' : 'gallery-filters'} role="group" aria-label={recommended ? t("갤러리 조합 필터") : t("갤러리 필름 필터")}>
          <button aria-pressed={filter === 'all'} onClick={() => selectFilter('all')}>{t("전체")}<small>{photos.length}</small></button>
          {groups.map(group => <button key={group.key} aria-pressed={filter === group.key} onClick={() => selectFilter(group.key)}>{group.label}<small>{group.count}</small></button>)}
        </div><span className="gallery-count" role="status">{t("{0}장", [visible.length])}</span></div>
        <div className="gallery-grid">{visible.map((photo, index) => {
          const film = filmById.get(photo.filmId)!
          return <article className="gallery-card" key={photo.id}><button className="gallery-open" aria-label={t("{0} · {1} 크게 보기", [film.name, photo.sourceFilename])} onClick={event => { opener.current = event.currentTarget; setOpened({ collection, id: photo.id }) }}>
            <span className="gallery-frame"><GalleryImage photo={photo} t={t}/><span className="gallery-expand" aria-hidden="true">↗</span></span>
            <span className="gallery-card-caption"><span><strong>{shortName(film.name)}</strong><small>{photo.paperId ? '+ ' + paperName(photo) : t("슬라이드 직접 스캔")}</small></span><span className="gallery-card-index">{String(index + 1).padStart(2, '0')}</span></span>
          </button></article>
        })}</div>
        <div className="gallery-footnote"><p>{t("사진에는 촬영 시 LUT가 이미 적용되어 있습니다. 갤러리에서는 추가 변환 없이 표시하며, 실제 필름 촬영이나 실물 인화 결과가 아닙니다.")}</p><span>{t("사진 © 촬영자 · 무단 재사용 금지")}</span></div>
      </>}
    </div>
    <dialog className="gallery-lightbox" ref={lightbox} aria-labelledby="gallery-photo-title" onCancel={event => { event.preventDefault(); close() }} onClose={() => setOpened(null)} onClick={event => { if (event.target === lightbox.current) close() }} onKeyDown={event => { if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); move(event.key === 'ArrowLeft' ? -1 : 1) } }}>
      {active && activeFilm && <div className="gallery-lightbox-inner">
        <div className="gallery-lightbox-top"><span>{recommended ? tabText(collection) : t("LUT 적용 예제 갤러리")}<span>{activeIndex + 1} / {visible.length}</span></span><button className="gallery-close" autoFocus onClick={close} aria-label={t("사진 닫기")}><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg></button></div>
        <div className="gallery-lightbox-body"><div className="gallery-lightbox-image"><GalleryImage key={active.id} photo={active} full t={t}/><button className="gallery-previous" onClick={() => move(-1)} aria-label={t("이전 사진")}>‹</button><button className="gallery-next" onClick={() => move(1)} aria-label={t("다음 사진")}>›</button></div>
        <aside className="gallery-photo-info">
          <span className="eyebrow">{activeFilm.brand.toUpperCase()}</span><h2 id="gallery-photo-title">{shortName(activeFilm.name)}</h2>
          <p className="gallery-photo-paper">{active.paperId ? '+ ' + paperName(active) : paperName(active)}</p>
          <span className="gallery-recipe-note">{recommended ? methodName(active) : active.paperId ? t("촬영자 확인 · 추천 인화지") : t("슬라이드 룩 · 인화지 미사용")}</span>
          <button className="gallery-use-look" onClick={() => { close(); onUseLook(active) }}>{t("이 룩으로 내 사진 보기")}<span aria-hidden="true">↗</span></button>
          <p className="gallery-use-note">{t("스튜디오에서 STD 원본에 이 조합을 적용합니다.")}</p>
          <dl className="gallery-exif">
            <dt>{t("촬영 카메라")}</dt><dd>{active.cameraName}</dd>
            <dt>{t("촬영 파일")}</dt><dd>{active.sourceFilename}</dd>
            <dt>{t("촬영 일시")}</dt><dd>{active.capturedAt?.replace('T', ' ') || '—'}</dd>
            <dt>{t("노출")}</dt><dd>{aperture(value('FNumber'))} · {exposure(value('ExposureTime'))}<br/>ISO {value('ISO')} · {value('ExposureCompensation')} EV</dd>
            <dt>{t("렌즈")}</dt><dd>{value('LensModel')}</dd>
            <dt>{t("화이트밸런스")}</dt><dd>{value('WhiteBalance') === 'Auto' ? t("자동") : value('WhiteBalance')}</dd>
            <dt>{t("포토스타일")}</dt><dd>{value('PhotoStyle')}</dd>
            <dt>LUT 1</dt><dd>{value('LUT1Name')}<small>{t("적용 강도")} {value('LUT1Opacity')}%</small></dd>
            <dt>LUT 2</dt><dd>{value('LUT2Name') === '—' && Number(active.exif.LUT2Opacity) === 0 ? 'OFF' : value('LUT2Name')}</dd>
          </dl>
          <p className="gallery-exif-note">{recommended ? t("필름과 인화지, 현상 방법은 촬영 정보에 기록된 LUT 파일명으로 확인했습니다.") : t("필름 이름은 EXIF, 인화지 조합은 촬영자 확인을 근거로 표시합니다. 인화지 이름은 EXIF에 기록되지 않습니다.")}</p>
        </aside></div>
      </div>}
    </dialog>
  </section>
}
