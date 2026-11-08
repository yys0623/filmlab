import type { Combination, ProcessPreference, ProcessMode, Sample, Stock, SuppliedFujiLook } from './types'
export { downloadFilename } from './lutNames.ts'

export const CAMERA_STORAGE_KEY = 'film-lab-std-camera'
export const DEFAULT_CAMERA = 'S1II'
export const STD_METHOD = 'camera-vlog-alchemy-v1'
export const UNSUPPORTED_L10 = 'unsupported:DMC-L10'

/** A camera must be explicit: never substitute another model or a retired STD. */
export function selectStdAsset(combo: Combination | undefined, cameraId: string) {
  if (combo?.stdMethod === 'supplied-fuji-std-v1') return combo.suppliedStd?.cameraId === cameraId ? combo.suppliedStd.asset : undefined
  return combo?.stdMethod === STD_METHOD ? combo.stdByCamera?.[cameraId]?.std : undefined
}

export function selectDownloadAsset(combo: Combination | undefined, format: 'std' | 'vlog' | 'zip', cameraId: string) {
  if (combo?.status !== 'ready') return undefined
  if (combo.stdMethod === 'supplied-fuji-std-v1') return format === 'std' ? selectStdAsset(combo, cameraId) : undefined
  if (combo.stdMethod !== STD_METHOD) return undefined
  if (format === 'vlog') return combo.files?.vlog
  return selectStdAsset(combo, cameraId) ? combo.stdByCamera?.[cameraId]?.[format] : undefined
}

export function selectStdQa(combo: Combination | undefined, cameraId: string) {
  const entry = selectStdAsset(combo, cameraId) ? combo?.stdByCamera?.[cameraId] : undefined
  return { metric: entry?.qa, warnings: entry?.warnings || [], method: entry ? combo?.stdMethod : undefined }
}

/** Match explicit metadata only. The 2007 DMC-L10 is not the modern DC-L10. */
export function cameraForSample(sample: Pick<Sample, 'cameraId' | 'cameraName' | 'cameraMetadata'> | null | undefined): string | undefined {
  if (!sample) return undefined
  const raw = [sample.cameraMetadata?.Model, sample.cameraName, sample.cameraId].filter(value => typeof value === 'string') as string[]
  if (raw.some(value => /DMC[ -]?L10/i.test(value)) || sample.cameraId?.toLowerCase() === 'l10') return UNSUPPORTED_L10
  const aliases: Record<string, string> = {
    G9M2: 'G9II', G9II: 'G9II', S5M2: 'S5II', S5II: 'S5II', S5M2X: 'S5IIX', S5IIX: 'S5IIX',
    S1M2: 'S1II', S1II: 'S1II', S1M2E: 'S1IIE', S1IIE: 'S1IIE', S1RM2: 'S1RII', S1R2: 'S1RII', S1RII: 'S1RII',
    GH6: 'GH6', GH7: 'GH7', S9: 'S9', DCL10: 'DC-L10',
  }
  for (const value of raw) {
    const normalized = value.toUpperCase().replace(/^(PANASONIC\s+)?LUMIX\s+/, '').replace(/^DC-(?!L10)/, '').replace(/[\s-]/g, '')
    if (aliases[normalized]) return aliases[normalized]
  }
  return undefined
}

/** Keep a matching photo, otherwise use a matching sample or an explicitly synthetic chart. */
export function sampleForCamera(samples: Sample[], cameraId: string, currentId?: string): Sample | undefined {
  const matching = samples.filter(sample => cameraForSample(sample) === cameraId)
  return matching.find(sample => sample.id === currentId) || matching[0] || samples.find(sample => sample.inputKind === 'synthetic-srgb')
}

export function processModeFor(film: Pick<Stock, 'type'>, preference: ProcessPreference): ProcessMode {
  if (film.type === 'supplied') return 'supplied_direct'
  if (film.type === 'official') return preference === 'official_direct' ? 'official_direct' : 'official_print'
  if (film.type === 'positive') return 'positive_direct'
  return preference === 'official_direct' || preference === 'official_print' ? 'negative_print' : preference
}

export function findLook(combinations: Combination[], film: Pick<Stock, 'id' | 'type'>, paperId: string, preference: ProcessPreference): Combination | undefined {
  const processMode = processModeFor(film, preference)
  const paper = processMode === 'negative_print' || processMode === 'official_print' ? paperId : null
  return combinations.find(combo => !combo.castBaseId && combo.film === film.id && combo.processMode === processMode && combo.paper === paper)
}

/** The optional film-cast variant that belongs to one base negative print. */
export function findFilmCast(combinations: Combination[], base: Combination | undefined): Combination | undefined {
  if (!base || base.castBaseId || base.processMode !== 'negative_print') return undefined
  return combinations.find(combo => combo.castBaseId === base.id && combo.status === 'ready')
}

/** Supplied cubes are finished S1II STD looks; no paper, camera bridge, or V-Log is fabricated. */
export function suppliedCombination(look: SuppliedFujiLook, cameraId: string): Combination {
  return { id: look.stock.id, film: look.stock.id, paper: null, number: 0,
    processMode: 'supplied_direct', status: 'ready', stdMethod: 'supplied-fuji-std-v1',
    suppliedStd: { cameraId, asset: look.std }, previewMode: 'runtime-std' }
}

/** Built-in samples keep their capture camera while export selection is independent. */
export function previewCameraFor(sample: Sample | null, uploaded: boolean, exportCamera: string): string {
  return uploaded ? exportCamera : cameraForSample(sample) || DEFAULT_CAMERA
}
