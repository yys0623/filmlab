import type { CSSProperties } from 'react'
import type { Stock } from './types'
import './filmCanister.css'

// Restore the original Film Lab cartridge illustration from commit 07a55ba.
// These are decorative marks; the adjacent film name supplies the accessible label.
const stockColor = (stock: Stock) => stock.brand === 'Fujifilm'
  ? '#7cb79e'
  : stock.id.includes('vision') || stock.id.includes('verita')
    ? '#a5a3c5'
    : stock.id.includes('gold') || stock.id.includes('ektar') ? '#dda363' : '#cfb88c'

export function FilmCanister({ stock }: { stock: Stock }) {
  // Digital simulations get a LUT badge rather than a film-stock label.
  if (stock.type === 'official' || stock.type === 'supplied') return <span className="film-canister-official" aria-hidden="true">
    <span>FUJI</span><b>STD</b><small>LUT</small>
  </span>

  const iso = stock.name.match(/(?:^|[^0-9])(\d{2,3})(?:D|T|F|H)?\b/)?.[1] || '35'
  return <span className="film-canister" aria-hidden="true" style={{ '--stock-color': stockColor(stock) } as CSSProperties}>
    <span className="film-canister-cap"/>
    <span className="film-canister-body"><span>{stock.brand === 'Kodak' ? 'K' : 'F'}</span><b>{iso}</b><i/></span>
  </span>
}
