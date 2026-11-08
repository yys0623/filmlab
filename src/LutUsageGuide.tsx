import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { Locale, Translate } from './i18n'
import './lutUsageGuide.css'

const manuals = {
  ko: 'https://eww.pavc.panasonic.co.jp/dscoi/DC-S1M2/html/DC-S1M2_DVQP3242_kor/',
  en: 'https://eww.pavc.panasonic.co.jp/dscoi/DC-S1M2/html/DC-S1M2_DVQP3227_eng/',
}

export function LutUsageGuide({ locale, t }: { locale: Locale; t: Translate }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [open, setOpen] = useState(false)
  const titleId = useId()
  useEffect(() => {
    if (!open) return
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = previous }
  }, [open])
  const screens = [
    { number: '01', title: t("LUT 라이브러리 열기"), detail: t("MENU/SET → 사용자 → 이미지 품질 → LUT 라이브러리") },
    { number: '02', title: t("등록할 칸 선택"), detail: t("빈 칸을 선택하세요. 기존 항목을 고르면 덮어씁니다.") },
    { number: '03', title: t("로드 선택"), detail: t("선택한 칸에서 로드를 실행하세요.") },
    { number: '04', title: t("카드 슬롯 선택"), detail: t("파일을 넣은 슬롯을 고르세요. 1은 CFexpress, 2는 SD입니다.") },
    { number: '05', title: t("LUT 파일 확정"), detail: t("원하는 파일을 고르고 MENU/SET으로 등록하세요.") },
  ]
  return <>
    <button className="usage-button" type="button" aria-haspopup="dialog" onClick={() => { dialog.current?.showModal(); setOpen(true) }}>
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 5c-3-2-6-2-9-1v15c3-1 6-1 9 1 3-2 6-2 9-1V4c-3-1-6-1-9 1Zm0 0v15"/></svg>
      {t("사용방법")}
    </button>
    {createPortal(<dialog ref={dialog} className="usage-dialog" aria-labelledby={titleId} onClose={() => setOpen(false)} onClick={event => { if (event.target === event.currentTarget) dialog.current?.close() }}>
      <div className="usage-shell">
        <header className="usage-heading"><div><span className="eyebrow">LUMIX S1II · DC-S1M2</span><h2 id={titleId}>{t("LUT 등록과 촬영")}</h2></div><button className="usage-close" type="button" aria-label={t("사용방법 닫기")} onClick={() => dialog.current?.close()}><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg></button></header>
        <div className="usage-content">
          <p className="usage-lead">{t("카드로 옮기고, 카메라에 등록하고, 원하는 색으로 촬영하세요.")}</p>
          <section className="usage-section" aria-labelledby={`${titleId}-file`}><div className="usage-step-title"><span>1</span><h3 id={`${titleId}-file`}>{t("sosang에서 파일 준비")}</h3></div>
            <p>{t("LUT 내보내기에서 LUMIX S1II와 STD (.cube)를 선택해 다운로드하세요. ZIP을 받았다면 압축을 풀고 STD 파일을 사용하세요.")}</p>
            <div className="usage-file"><code>C200CA.cube</code><span>{t("카드 복사용 파일명 예시")}</span></div>
            <p>{t("파일은 필름명 + 인화지 약자로 저장됩니다. C200CA는 C200 + Crystal Archive Type II (CA)입니다. Portra400EP처럼 필름 이름은 유지합니다.")}</p>
            <p>{t("V-Log 파일은 끝에 VLOG가 붙습니다. C200CAVLOG.cube는 V-Log용입니다. 카메라는 내보내기에서 선택하며, 기종별 파일은 이름이 같으므로 서로 다른 폴더에 보관하세요.")}</p>
            <p>{t("긴 파일명은 exFAT 카드에서 사용하세요. FAT32 카드라면 확장자를 제외한 이름을 영문·숫자 8자 이내로 줄이고 .cube는 유지하세요.")}</p>
            <p>{t("카드를 컴퓨터에서 열고 첫 화면에 .cube 파일을 복사하세요. DCIM 같은 하위 폴더에 넣지 않습니다.")}</p>
            <p className="usage-context">{t("제공된 후지 9종도 S1II STD 파일을 그대로 사용합니다. V-Log 파일은 이 STD 안내와 구분해 주세요.")}</p>
          </section>
          <section className="usage-section" aria-labelledby={`${titleId}-register`}><div className="usage-step-title"><span>2</span><h3 id={`${titleId}-register`}>{t("카메라에 LUT 등록")}</h3></div>
            <p>{t("카드를 카메라에 넣은 뒤 아래 순서로 진행하세요.")}</p>
            <ol className="usage-screens">{screens.map(screen => <li key={screen.number}><figure><img src={`/manual/s1ii/${locale}-library-${screen.number}.png`} alt={t("S1II 설명서 화면: {0}", [screen.title])} width="390" height="260" loading="lazy" decoding="async"/><figcaption><span>{screen.number}</span><div><h4>{screen.title}</h4><p>{screen.detail}</p></div></figcaption></figure></li>)}</ol>
            <a className="usage-source" href={`${manuals[locale]}0079.html`} target="_blank" rel="noreferrer">{t("이미지·등록 절차 출처: Panasonic S1II 공식 설명서 ↗")}</a>
          </section>
          <section className="usage-section" aria-labelledby={`${titleId}-shoot`}><div className="usage-step-title"><span>3</span><h3 id={`${titleId}-shoot`}>{t("등록한 LUT로 촬영")}</h3></div>
            <p>{t("P/A/S/M 모드에서 사진 메뉴 → 이미지 품질 → 사진 스타일 → 실시간 LUT를 선택하세요.")}</p>
            <p>{t("LUT 항목에서 AF 모드 버튼을 누르고 등록한 파일을 고른 뒤 MENU/SET으로 확정하세요.")}</p>
            <div className="usage-recommendation"><strong>{t("sosang 권장 설정")}</strong><p>{t("STD 파일의 기본 사진 스타일은 표준입니다. 사이트 룩의 원래 강도로 보려면 LUT 불투명도를 100%로 두세요.")}</p></div>
            <p>{t("색이 적용된 JPG를 남기려면 JPEG 또는 RAW+JPEG로 촬영하세요. RAW 데이터 자체에는 LUT가 적용되지 않습니다.")}</p>
            <figure className="usage-realtime"><img src={`/manual/s1ii/${locale}-realtime-lut.png`} width="394" height="264" alt={t("S1II 설명서의 Fn 실시간 LUT 선택 화면")} loading="lazy" decoding="async"/><figcaption>{t("실시간 LUT를 지정한 Fn 버튼으로도 불러올 수 있습니다. 이미지는 Fn 버튼으로 연 선택 화면입니다.")} <a href={`${manuals[locale]}0078.html`} target="_blank" rel="noreferrer">{t("Fn 사용 안내 ↗")}</a></figcaption></figure>
            <a className="usage-source" href={`${manuals[locale]}0076.html`} target="_blank" rel="noreferrer">{t("사진 스타일·실시간 LUT 공식 안내 ↗")}</a>
          </section>
          <details className="usage-help"><summary>{t("파일이 목록에 보이지 않나요?")}</summary><p>{t("압축을 푼 .cube인지, 카드의 최상위에 있는지, 영문·숫자로 된 짧은 이름인지 확인하세요. FAT32는 확장자 제외 8자, exFAT는 확장자 포함 255자까지 지원합니다.")}</p></details>
          <p className="usage-attribution">{t("메뉴 이미지는 Panasonic 공식 설명서에서 가져왔습니다. 화면 저작권은 Panasonic에 있으며, 이 안내는 S1II 기준입니다.")}</p>
        </div>
        <footer className="usage-footer"><a href={`${manuals[locale]}0079.html`} target="_blank" rel="noreferrer">{t("공식 설명서 열기 ↗")}</a><button type="button" onClick={() => dialog.current?.close()}>{t("확인")}</button></footer>
      </div>
    </dialog>, document.body)}
  </>
}
