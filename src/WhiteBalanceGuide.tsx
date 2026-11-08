import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { Locale, Translate } from './i18n'
import './lutUsageGuide.css'
import './whiteBalanceGuide.css'

const manuals = {
  ko: 'https://eww.pavc.panasonic.co.jp/dscoi/DC-S1M2/html/DC-S1M2_DVQP3242_kor/0075.html#00002',
  en: 'https://eww.pavc.panasonic.co.jp/dscoi/DC-S1M2/html/DC-S1M2_DVQP3227_eng/0075.html#00002',
}

export function WhiteBalanceGuide({ locale, t }: { locale: Locale; t: Translate }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [open, setOpen] = useState(false)
  const titleId = useId()
  useEffect(() => {
    if (!open) return
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = previous }
  }, [open])
  const directions = [
    { arrow: '←', direction: t("왼쪽"), code: 'A', label: t("호박색 · 오렌지 톤") },
    { arrow: '→', direction: t("오른쪽"), code: 'B', label: t("청색 · 푸른 톤") },
    { arrow: '↑', direction: t("위쪽"), code: 'G', label: t("녹색 · 초록 톤") },
    { arrow: '↓', direction: t("아래쪽"), code: 'M', label: t("마젠타 · 붉은 톤") },
  ]
  return <>
    <button className="usage-button color-tips-button" type="button" aria-haspopup="dialog" onClick={() => { dialog.current?.showModal(); setOpen(true) }}>
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true"><path d="M4 7h2m6 0h8M4 17h8m6 0h2"/><circle cx="9" cy="7" r="3"/><circle cx="15" cy="17" r="3"/></svg>
      {t("추가 색감 조절팁")}
    </button>
    {createPortal(<dialog ref={dialog} className="usage-dialog wb-dialog" aria-labelledby={titleId} onClose={() => setOpen(false)} onClick={event => { if (event.target === event.currentTarget) dialog.current?.close() }}>
      <div className="usage-shell">
        <header className="usage-heading"><div><span className="eyebrow">LUMIX S1II · DC-S1M2</span><h2 id={titleId}>{t("추가 색감 조절팁")}</h2></div><button className="usage-close" type="button" aria-label={t("색감 조절팁 닫기")} onClick={() => dialog.current?.close()}><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg></button></header>
        <div className="usage-content">
          <p className="usage-lead">{t("카메라의 화이트 밸런스를 미세 조정해 선택한 필름 룩의 색조를 바꿀 수 있습니다.")}</p>
          <section className="usage-section" aria-labelledby={`${titleId}-open`}>
            <div className="usage-step-title"><span>1</span><h3 id={`${titleId}-open`}>{t("화이트 밸런스 조정 화면 열기")}</h3></div>
            <p>{t("WB 버튼을 눌러 사용할 화이트 밸런스를 선택한 다음, 아래 방향 버튼(↓)을 누르세요.")}</p>
            <div className="wb-entry-screens">
              <figure><img src={`/manual/s1ii/${locale}-wb-button.png`} width="390" height="260" alt={t("S1II 카메라의 WB 버튼 위치")} loading="lazy" decoding="async"/><figcaption>{t("WB 버튼")}</figcaption></figure>
              <figure><img src={`/manual/s1ii/${locale}-wb-select.png`} width="394" height="264" alt={t("S1II 설명서의 화이트 밸런스 선택 화면")} loading="lazy" decoding="async"/><figcaption>{t("화이트 밸런스 선택 → ↓")}</figcaption></figure>
            </div>
          </section>
          <section className="usage-section" aria-labelledby={`${titleId}-adjust`}>
            <div className="usage-step-title"><span>2</span><h3 id={`${titleId}-adjust`}>{t("원하는 색 방향으로 조정")}</h3></div>
            <div className="wb-adjust-layout">
              <figure className="wb-adjust-screen"><img src={`/manual/s1ii/${locale}-wb-adjust.png`} width="391" height="261" alt={t("S1II 설명서의 A·B·G·M 화이트 밸런스 미세 조정 화면")} loading="lazy" decoding="async"/><figcaption>{t("공식 설명서 · 화이트 밸런스 조정하기")}</figcaption></figure>
              <ul className="wb-directions">{directions.map(direction => <li key={direction.code}><span className="wb-arrow" role="img" aria-label={direction.direction}>{direction.arrow}</span><strong>{direction.code}</strong><span>{direction.label}</span></li>)}</ul>
            </div>
            <p>{t("방향 버튼으로 조정하거나 그래프를 터치하세요. 조이스틱으로는 대각선 조정도 가능합니다.")}</p>
          </section>
          <section className="usage-section" aria-labelledby={`${titleId}-finish`}>
            <div className="usage-step-title"><span>3</span><h3 id={`${titleId}-finish`}>{t("확정하거나 초기화")}</h3></div>
            <p>{t("셔터 버튼을 반쯤 누르면 확정됩니다. 조정값을 되돌리려면 이 화면에서 DISP.를 누르세요.")}</p>
          </section>
          <div className="usage-recommendation"><strong>{t("sosang 촬영 팁")}</strong><p>{t("LUT를 적용한 화면을 보면서 작은 폭으로 조정해 보세요. 같은 장면에서 필름을 비교할 때는 WB와 조정값을 동일하게 유지하면 차이를 보기 쉽습니다.")}</p></div>
          <a className="usage-source" href={manuals[locale]} target="_blank" rel="noreferrer">{t("이미지·조작 방법 출처: Panasonic S1II 공식 설명서 ↗")}</a>
          <p className="usage-attribution">{t("메뉴 이미지는 Panasonic 공식 설명서에서 가져왔습니다. 화면 저작권은 Panasonic에 있으며, 이 안내는 S1II 기준입니다.")}</p>
        </div>
        <footer className="usage-footer"><a href={manuals[locale]} target="_blank" rel="noreferrer">{t("공식 설명서 열기 ↗")}</a><button type="button" onClick={() => dialog.current?.close()}>{t("확인")}</button></footer>
      </div>
    </dialog>, document.body)}
  </>
}
