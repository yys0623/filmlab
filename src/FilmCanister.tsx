import type { CSSProperties } from 'react'
import type { Stock } from './types'
import './filmCanister.css'

const packLabel = (stock: Stock) => {
  if (stock.id.includes('vision3')) return stock.name.replace('Kodak Vision3 ', 'VISION3\n')
  if (stock.id.includes('verita')) return 'VERITA\n200D'
  if (stock.id.includes('kodachrome')) return 'KODACHROME\n64'
  if (stock.id.includes('ultramax')) return 'ULTRAMAX\n400'
  if (stock.id.includes('portra')) return stock.name.replace('Kodak ', '').replace(' (Push ', '\nPUSH +').replace(')', '')
  if (stock.id.includes('gold')) return 'GOLD\n200'
  if (stock.id.includes('c200')) return 'FUJICOLOR\nC200'
  return stock.name.replace(/^(Kodak|Fujifilm) /, '').replace(' ', '\n')
}

const rollTone = (stock: Stock): CSSProperties => {
  if (stock.use === 'cine') return { '--label-top': '#20211e', '--label-bottom': '#d8b740', '--ink': '#f6e98e', '--leader': '#703d27' } as CSSProperties
  if (stock.id.includes('portra')) return { '--label-top': '#252126', '--label-bottom': '#785093', '--ink': '#f6d64d', '--leader': '#754a2d' } as CSSProperties
  if (stock.id.includes('ektar')) return { '--label-top': '#151617', '--label-bottom': '#d84d39', '--ink': '#f3d45a', '--leader': '#744a2d' } as CSSProperties
  if (stock.id.includes('gold') || stock.id.includes('ultramax')) return { '--label-top': '#f1c541', '--label-bottom': '#e56632', '--ink': '#1f1e18', '--leader': '#754a2d' } as CSSProperties
  if (stock.id.includes('ektachrome') || stock.id.includes('kodachrome')) return { '--label-top': '#204c83', '--label-bottom': '#e6bd35', '--ink': '#f8f5e9', '--leader': '#563b29' } as CSSProperties
  if (stock.id.includes('pro_400h')) return { '--label-top': '#252128', '--label-bottom': '#31a05e', '--ink': '#f4db4e', '--leader': '#764b31' } as CSSProperties
  if (stock.id.includes('provia') || stock.id.includes('velvia')) return { '--label-top': '#178351', '--label-bottom': '#74356f', '--ink': '#f5f7ed', '--leader': '#74482f' } as CSSProperties
  return { '--label-top': '#258958', '--label-bottom': '#e34e38', '--ink': '#f5f7ed', '--leader': '#71462e' } as CSSProperties
}

export function FilmCanister({ stock }: { stock: Stock }) {
  if (stock.type === 'official' || stock.type === 'supplied') return <span className="film-simulation" aria-hidden="true"><span>FUJIFILM</span><b>{stock.name.replace(/^FUJIFILM /, '').split(' ')[0]}</b><small>SIMULATION</small></span>
  return <span className={`film-roll ${stock.use === 'cine' ? 'cine' : ''}`} aria-hidden="true" style={rollTone(stock)}><span className="film-leader"/><span className="film-cap"/><span className="film-label"><span>{stock.brand === 'Kodak' ? 'KODAK' : 'FUJIFILM'}</span><b>{packLabel(stock).split('\n').map((line, index) => <span key={index}>{line}</span>)}</b><i>{stock.type === 'positive' ? 'E-6' : stock.use === 'cine' ? 'ECN-2' : 'C-41'}</i></span></span>
}
