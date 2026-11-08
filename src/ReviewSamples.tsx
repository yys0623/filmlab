import { useEffect, useState } from 'react'
import type { ExternalSamples, Sample } from './types'
import { sampleText, type Locale, type Translate } from './i18n'

export function ReviewSamples({ collection, selected, onSelect, locale, t }: {
  collection: ExternalSamples; selected: string; onSelect: (id: string) => void; locale: Locale; t: Translate
}) {
  const [camera, setCamera] = useState(collection.samples.find(sample => sample.id === selected)?.cameraId || collection.models[0]?.id || '')
  const [scene, setScene] = useState('all')
  useEffect(() => {
    const selectedCamera = collection.samples.find(sample => sample.id === selected)?.cameraId
    if (selectedCamera && selectedCamera !== camera) { setCamera(selectedCamera); setScene('all') }
  }, [collection, selected, camera])
  const cameraSamples = collection.samples.filter(sample => sample.cameraId === camera)
  const scenes = collection.scenes.filter(item => cameraSamples.some(sample => sample.scenes?.includes(item.id)))
  const visible = cameraSamples.filter(sample => scene === 'all' || sample.scenes?.includes(scene))
  const missing = collection.missing.filter(item => item.camera === camera)
  function chooseCamera(id: string) {
    setCamera(id); setScene('all')
    const first = collection.samples.find(sample => sample.cameraId === id)
    if (first) onSelect(first.id)
  }
  function chooseScene(id: string) {
    setScene(id)
    const first = cameraSamples.find(sample => id === 'all' || sample.scenes?.includes(id))
    if (first) onSelect(first.id)
  }
  return <div className="review-samples">
    <div className="sample-camera-tabs" role="group" aria-label={t('샘플 카메라')}>
      {collection.models.map(model => <button key={model.id} aria-pressed={camera === model.id} onClick={() => chooseCamera(model.id)}>
        {model.name.replace('LUMIX ', '')}<small>{collection.samples.filter(sample => sample.cameraId === model.id).length}</small>
      </button>)}
    </div>
    <div className="sample-scene-filter"><label>{t('촬영 조건')}<select value={scene} onChange={event => chooseScene(event.target.value)}>
      <option value="all">{t('모든 촬영 조건')}</option>
      {scenes.map(item => <option key={item.id} value={item.id}>{locale === 'en' ? item.nameEn : item.name}</option>)}
    </select></label><span>{visible.length === 1 ? t('사진 1장') : t('{0}장', [visible.length])}</span></div>
    <div key={`${camera}-${scene}`} className="sample-grid review-sample-grid">{visible.map(sample => <button key={sample.id} className={`sample-option ${selected === sample.id ? 'selected' : ''}`} aria-pressed={selected === sample.id} onClick={() => onSelect(sample.id)}>
      <div><img src={sample.thumbnailPath || sample.path} alt="" loading="lazy"/>{selected === sample.id && <span aria-hidden="true">✓</span>}</div><strong>{sampleText(sample, 'name', locale)}</strong>
    </button>)}</div>
    {!!missing.length && <p className="sample-missing">{t('미확보 조건')}: {missing.map(item => { const label = collection.scenes.find(s => s.id === item.scene); return label ? (locale === 'en' ? label.nameEn : label.name) : item.scene }).join(' · ')}</p>}
    <p className="sample-library-note">{t('리뷰 원본을 이용한 로컬 비교입니다. 날씨·조명은 사진과 원문 설명으로 분류했으며, 추정 여부는 각 사진에 표시합니다.')}</p>
  </div>
}

export function ReviewSampleCredit({ sample, locale, t }: { sample: Sample; locale: Locale; t: Translate }) {
  if (sample.inputKind !== 'review-jpeg') return null
  const metadata = sample.cameraMetadata || {}
  const exposure = [metadata.ExposureTime ? `${metadata.ExposureTime}s` : '', metadata.FNumber ? `ƒ/${metadata.FNumber}` : '', metadata.ISO ? `ISO ${metadata.ISO}` : ''].filter(Boolean).join(' · ')
  return <aside className="review-credit" aria-label={t('샘플 출처와 촬영 정보')}>
    <div className="review-credit-heading"><strong>{sample.cameraName}</strong>{sample.preproduction && <span>{t('사전 출시 샘플')}</span>}<span>{exposure}</span></div>
    <p><a href={sample.source || undefined} target="_blank" rel="noreferrer">{sample.credit} ↗</a><span> · {sampleText(sample, 'name', locale)}</span></p>
    <details><summary>{t('촬영 조건과 STD 확인 근거')}</summary>
      <p>{locale === 'en' ? sample.notesEn || sample.notes : sample.notes}</p>
      <p>{locale === 'en' ? sample.stdEvidenceEn || sample.stdEvidence : sample.stdEvidence}</p>
      <p>{t('Standard or Custom은 공장 기본 Standard 설정과 동일하다는 보장이 아닙니다. 샘플은 카메라별 색 정확도 검증용 촬영 쌍이 아닙니다.')}</p>
      {sample.originalUrl && <a href={sample.originalUrl} target="_blank" rel="noreferrer">{t('출처의 원본 JPG')} ↗</a>}
      <p>{t('사진의 권리는 촬영자와 원출처에 있습니다. 출처 표시는 공개 재배포 허가를 뜻하지 않습니다.')}</p>
    </details>
  </aside>
}
