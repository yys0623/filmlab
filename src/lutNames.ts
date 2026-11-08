import type { ProcessMode, Stock } from './types'

type NamedStock = Pick<Stock, 'id' | 'name'>

export const PAPER_CODES: Record<string, string> = {
  fujifilm_crystal_archive_typeii: 'CA', kodak_2383: '83', kodak_2393: '93',
  kodak_ektacolor_edge: 'EE', kodak_endura_premier: 'EP',
  kodak_portra_endura: 'PE', kodak_supra_endura: 'SE', kodak_ultra_endura: 'UE',
}

export function paperLabel(paper: NamedStock, short = false) {
  const name = short ? paper.name.replace(/^(Kodak|Fujifilm) (Professional )?/i, '') : paper.name
  return PAPER_CODES[paper.id] ? `${name} (${PAPER_CODES[paper.id]})` : name
}

/** Keep the complete film name; append the same print code shown in the UI. */
/** Film-cast variants add FC after the print code (Gold200CAFC.cube). */
export function downloadFilename(film: NamedStock, paper: NamedStock | undefined, processMode: ProcessMode, format: 'std' | 'vlog' | 'zip', cameraName: string, filmCast = false) {
  const filmName = film.name.replace(/^(Kodak|Fujifilm) (Professional )?/i, '').replace(/[^A-Za-z0-9]/g, '')
  const output = processMode === 'negative_print' || processMode === 'official_print'
    ? paper && PAPER_CODES[paper.id]
    : processMode === 'negative_digital' ? 'DS'
    : processMode === 'positive_direct' ? 'SL'
    : processMode === 'supplied_direct' ? '' : 'OD'
  if (!filmName || output === undefined) throw new Error('Missing LUT filename code')
  if (filmCast && processMode !== 'negative_print') throw new Error('Film cast requires a print')
  const base = `${filmName}${output}${filmCast ? 'FC' : ''}`
  const name = `${base}${format === 'vlog' ? 'VLOG' : ''}`
  if (format === 'zip') {
    // Camera-specific packages remain identifiable without changing the cube name.
    const camera = cameraName.replace(/^LUMIX\s+/i, '').replace(/[^A-Za-z0-9]/g, '')
    if (!camera) throw new Error('Missing export camera')
    return `${base}-${camera}.zip`
  }
  return `${name}.cube`
}
