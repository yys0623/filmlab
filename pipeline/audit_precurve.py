"""Independent audit of exported-VLOG single-tone A/B STD assets.

Run after generation: .venv/bin/python -m pipeline.audit_precurve
Uses colour-science's reader/tetrahedral interpolator, independently spells out
F, N, P and T, and verifies immutable baseline hashes. Production precurve is
used only as an implementation under test, never as its own expected result.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path

import colour
import numpy as np
from PIL import Image, ImageCms

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / 'public'
IDS = ['kodak_portra_400__kodak_portra_endura',
       'fujifilm_c200__fujifilm_crystal_archive_typeii',
       'fujifilm_velvia_100__direct_scan',
       'gfx_classic_chrome__fujifilm_crystal_archive_typeii']
W = np.array([.2126, .7152, .0722])
# Published coefficient contract, duplicated intentionally, not imported.
TO_V = np.linalg.inv(np.array([[1.806576,-.695697,-.110879],
                              [-.170090,1.305955,-.135865],
                              [-.025206,-.154468,1.179674]]))
REQUESTED_CODES = [0,10,20,30,44,60,89,118,150,180,225,255]
CAST_CODES = [20,44,89,118,180]
CODES = sorted(set(REQUESTED_CODES + [1,2,4,8,13,16,24,32,48,64,96,128,160,192,224,236,240,248,254]))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decode(x):
    return colour.models.eotf_sRGB(np.asarray(x, dtype=float))


def encode(x):
    return colour.models.eotf_inverse_sRGB(np.asarray(x, dtype=float))


def F(x):
    lin = decode(x) @ TO_V.T
    return np.where(lin < .01, 5.6*lin+.125,
                    .241514*np.log10(np.maximum(lin+.00873, 1e-12))+.598206)


def Y(rgb):
    return decode(rgb) @ W


def ey(rgb):
    return encode(Y(rgb))


def lab(rgb):
    # colour-science's standard sRGB / D65 conversion; diagnostic only.
    return colour.XYZ_to_Oklab(colour.sRGB_to_XYZ(rgb))


def apply(lut, rgb):
    x = np.asarray(rgb)
    return lut.apply(np.clip(x, 0, 1), interpolator=colour.algebra.table_interpolation_tetrahedral)


def read_lut(path, expected=None):
    if expected and digest(path) != expected:
        raise ValueError(f'LUT hash differs from declared snapshot: {path}')
    lut = colour.read_LUT(str(path))
    if not isinstance(lut, colour.LUT3D):
        raise TypeError(f'Expected a 3D cube: {path}')
    return lut


class IndependentReference:
    def __init__(self, lut):
        self.lut = lut
        self.axis = np.linspace(0, 1, 4097)
        self.gray = np.repeat(self.axis[:,None],3,axis=1)
        self.response = self.raw(self.gray)
        self.measured = ey(self.response)
        self.monotone = np.maximum.accumulate(self.measured)
        self.levels, ix = np.unique(self.monotone, return_index=True)
        self.positions = self.axis[ix]
        self.ends = self.axis[np.r_[ix[1:]-1,len(self.axis)-1]]
        self.b, self.w = Y(self.response[[0,-1]])
        if self.w <= .18:
            raise ValueError('B has no attainable 18% gray')
        self.k = (1-self.w)/(self.w-.18)

    def raw(self, rgb):
        return apply(self.lut,F(rgb))

    def inverse(self, x):
        # First-occurrence generalized inverse; exact endpoint exceptions do
        # not distort the interior interpolation next to an endpoint plateau.
        upper = np.clip(np.searchsorted(self.levels,x,side='left'),1,len(self.levels)-1)
        lower = upper-1
        weight = (x-self.levels[lower])/(self.levels[upper]-self.levels[lower])
        result = self.ends[lower]+np.clip(weight,0,1)*(self.positions[upper]-self.ends[lower])
        return np.where(x <= self.levels[0],0,np.where(x >= self.levels[-1],1,result))

    def target(self, x, variant):
        y = decode(x)
        if variant == 'A':
            return encode(self.b+(self.w-self.b)*y)
        high = np.maximum(y-.18,0)
        return encode(np.where(y <= .18,y,.18+high/(1+self.k*high/.82)))

    def warp(self, x, variant):
        return self.inverse(self.target(x,variant))

    def render(self, x, variant):
        return self.raw(self.warp(x,variant))


def stat(v):
    v = np.asarray(v)
    if not v.size:
        return None
    return {'n':int(v.size),'mean':float(v.mean()),'p50':float(np.median(v)),
            'p95':float(np.quantile(v,.95)),'p99':float(np.quantile(v,.99)),
            'min':float(v.min()),'max':float(v.max())}


def error(a,b):
    return stat(np.max(np.abs(np.asarray(a)-b),axis=-1))


def color_metrics(output, original):
    a,b = lab(output),lab(original)
    c0,c1 = np.linalg.norm(b[:,1:],axis=1),np.linalg.norm(a[:,1:],axis=1)
    eligible = c0 > .02
    ratio = c1[eligible]/c0[eligible]
    return {'deltaL':stat(a[:,0]-b[:,0]),
            'fullDeltaEOKx100':stat(100*np.linalg.norm(a-b,axis=1)),
            'isoLChromaDeltaOKx100':stat(100*np.linalg.norm(a[:,1:]-b[:,1:],axis=1)),
            'chromaRatioSourceCAbove002':stat(ratio),
            'chromaHigherPercent':float(np.mean(ratio>1)*100) if ratio.size else None,
            'chromaLowerPercent':float(np.mean(ratio<1)*100) if ratio.size else None}


def direction_metrics(old, new, original):
    source = lab(original)[:,1:]
    first,second = lab(old)[:,1:]-source,lab(new)[:,1:]-source
    eligible = (np.linalg.norm(first,axis=1)>=.005)&(np.linalg.norm(second,axis=1)>=.005)
    dot = np.sum(first[eligible]*second[eligible],axis=1)
    return {'definition':'dot(old_ab-source_ab, new_ab-source_ab)<0; both delta-ab norms >=0.005 OKLab',
            'thresholdOKLab':.005,'eligible':int(eligible.sum()),'totalMidtones':int(len(eligible)),
            'eligiblePercent':float(eligible.mean()*100),
            'opposedDirectionPercent':float(np.mean(dot<0)*100) if dot.size else None}


def gray_stats(rgb):
    y=Y(rgb); d=np.diff(y); codes=np.rint(ey(rgb)*255).astype(int)
    return {'floatMinLinearYStep':float(d.min()),
            'floatDescendingSteps':int(np.count_nonzero(d < -1e-12)),
            'floatExactTies':int(np.count_nonzero(d == 0)),
            'quantized8bitEncodedYUniqueLevels':int(len(np.unique(codes))),
            'quantized8bitEncodedYTies':int(np.count_nonzero(np.diff(codes)==0)),
            'blackRgb':rgb[0].tolist(),'whiteRgb':rgb[-1].tolist(),
            'first16MinLinearYStep':float(np.diff(y[:17]).min()),
            'last20MinLinearYStep':float(np.diff(y[-21:]).min())}


def native_reference(combo, points):
    """Optional continuous native comparison, never used as new STD truth."""
    if combo['processMode'].startswith('official_'):
        return None
    from pipeline.common import CONFIG
    from spektrafilm_lut_creator.bundles import BundleSpec
    from spektrafilm_lut_creator.builders import BundleBuilder
    from spektrafilm_lut_creator.qa.reference import run_pipeline_at
    from pipeline.slide import INIT_PRINT_PROFILE, SlideBundleBuilder, run_slide_reference
    from pipeline.digital import DigitalScanBundleBuilder, run_digital_reference
    slide = combo['processMode']=='positive_direct'
    digital = combo['processMode']=='negative_digital'
    spec=BundleSpec(film_profile=combo['film'],print_profiles=(combo.get('paper') or INIT_PRINT_PROFILE,),
        input_color_space=CONFIG['input'],output_color_space=CONFIG['output'],topology=CONFIG['topology'],
        resolution=CONFIG['resolution'],target=CONFIG['target'],stops_above_midgray=CONFIG['stops_above_midgray'],
        output_gamut_compress=CONFIG['output_gamut_compress'])
    bundle=(SlideBundleBuilder if slide else DigitalScanBundleBuilder if digital else BundleBuilder)(spec).build()
    if slide:
        return run_slide_reference(spec,F(points))
    if digital:
        return run_digital_reference(spec,F(points))
    return run_pipeline_at(spec,bundle,0,F(points))


def catalog_qa_summary(catalog):
    """Aggregate all generated QA, explicitly distinct from 4-look re-evaluation."""
    active=[c for c in catalog['combinations'] if 'stdB' in c.get('files',{})]
    if len(active)!=238:
        raise ValueError(f'Expected 238 A/B combinations, found {len(active)}')
    summary={'scope':'All 238 A/B combinations; 4 archived reference combinations excluded',
        'source':'Aggregation of generated qa.json, SHA-checked against catalog; not an independent re-evaluation of every combination',
        'thresholdEncodedRGB':.02,'metric':'Largest absolute encoded sRGB channel difference per pixel, tetrahedral',
        'sampling':'Each combination: 4096 random RGB +129 gray +125 grid =4350; photos:1024 fixed sampled pixels per photo',
        'combinationCount':len(active),'archivedReferenceCombinations':len(catalog['combinations'])-len(active),
        'variants':{}}
    for variant,qkey,pkey in [('A','stdVsDirectEngine','photoPixelFidelity'),('B','stdBVsDirectEngine','photoPixelFidelityB')]:
        rows=[]; photos=[]
        for c in active:
            qa_file=PUBLIC/c['files']['qa']['path'].lstrip('/')
            if digest(qa_file)!=c['files']['qa']['sha256']:
                raise ValueError(f'QA bytes differ from catalog: {c["id"]}')
            q=json.loads(qa_file.read_text()); m=q[qkey]['tetrahedral']
            photo=[{'id':c['id'],'sample':sid,**metric} for sid,metric in q[pkey].items()]
            photos.extend(photo)
            rows.append({'id':c['id'],'randomP99':m['p99'],'randomMax':m['max'],
                'worstPhotoP99':max(photo,key=lambda x:x['p99']),
                'qaSha256':c['files']['qa']['sha256']})
        flagged=[r for r in rows if r['randomP99']>.02]
        photo_flagged=[r for r in rows if r['worstPhotoP99']['p99']>.02]
        summary['variants'][variant]={
            'randomP99AboveThresholdCount':len(flagged),
            'randomP99AboveThresholdIds':[r['id'] for r in flagged],
            'photoP99AboveThresholdCombinationCount':len(photo_flagged),
            'photoP99AboveThresholdIds':[r['id'] for r in photo_flagged],
            'worstRandomP99':max(rows,key=lambda r:r['randomP99']),
            'worstRandomMax':max(rows,key=lambda r:r['randomMax']),
            'worstPhotoP99':max(photos,key=lambda r:r['p99']),
            'worstPhotoMax':max(photos,key=lambda r:r['max']),
            'warningRows':sorted([r for r in rows if r['randomP99']>.02 or r['worstPhotoP99']['p99']>.02],key=lambda r:r['randomP99'],reverse=True),
            'allCombinationRows':rows}
    return summary


def integrated_checks():
    return {'source':'Root integrated verification results; not rerun by this audit script',
            'verificationRun':'2026-11-03 STD precurve A/B release; historical code-test and file-integrity results',
            'pythonTestsPassed':219,'javascriptTestsPassed':43,
            'publicCubeFilesVerified':722,'visibleCubeFilesVerified':714,
            'archivedReferenceCombinationsIncludedInPublic':4,
            'meaning':'File integrity and code tests pass; this does not mean every 33^3 interpolation p99 is below 0.02'}


def image_save(path, rgb):
    im=Image.fromarray(np.rint(np.clip(rgb,0,1)*255).astype('uint8'))
    icc=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    im.save(path,lossless=True,icc_profile=icc)


def fmt(x):
    if x is None: return '—'
    if isinstance(x, (float,np.floating)): return f'{x:.6f}'
    return html.escape(str(x))


def table(headers, rows):
    return '<div class="scroll"><table><thead><tr>'+''.join(f'<th>{html.escape(h)}</th>' for h in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join(f'<td>{fmt(x)}</td>' for x in row)+'</tr>' for row in rows)+'</tbody></table></div>'


def report_html(report, out):
    parts=['''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>STD A/B 독립 검증</title><style>@font-face{font-family:SUIT;src:url(/fonts/SUIT-Variable.woff2) format("woff2");font-weight:100 900;font-display:swap}@font-face{font-family:Manrope;src:url(/fonts/Manrope-Variable-latin.woff2) format("woff2");font-weight:200 800;font-display:swap}html{scroll-behavior:smooth;scroll-padding-top:24px}nav{display:flex;flex-wrap:wrap;gap:10px;margin:28px 0}nav a{padding:9px 14px;border:1px solid #555;border-radius:8px;text-decoration:none}body{margin:auto;max-width:1500px;padding:24px;background:#161616;color:#ddd;font:15px/1.65 Manrope,SUIT,system-ui,sans-serif}h1,h2,h3{color:#fff;line-height:1.3}h2{margin-top:56px}a{color:#afd1e8}code{color:#eee}table{border-collapse:collapse;font:13px/1.5 ui-monospace,monospace}td,th{padding:8px 12px;border-bottom:1px solid #444;white-space:nowrap;text-align:right}th{color:#b7c7d4}.scroll{overflow:auto}.photos{display:grid;grid-template-columns:repeat(5,minmax(180px,1fr));gap:8px;min-width:940px}.photos img{width:100%;display:block}.photos figure{margin:0}.photos figcaption{font-size:12px}.note{color:#aaa}details{margin:24px 0}summary{cursor:pointer}p{max-width:1000px}</style><h1>STD A/B · 독립 검증</h1><p>공개 VLOG CUBE를 고정한 후 동일한 1D 전처리를 RGB 각 채널에 적용했습니다. 출력에 채도 증폭·중성색 제거·명도 제한은 추가하지 않았습니다. 이 검증은 구현과 파일의 일치를 확인하며, 실물 필름 또는 Panasonic Standard의 실측 정확도를 증명하지 않습니다.</p><p><code>R(x)=L_VLOG(F(x)), N=E(Y(D(R(gray)))), STD=R(P(T(x)))</code></p><p>A는 원래 출력의 black/white 범위 안에서 선형광의 상대 명도를 유지합니다. B는 18% 회색 이하를 유지하고 하이라이트만 C1 곡선으로 압축합니다. 단, 원래 black 이하에서는 P가 포화되어 디테일이 회복되지 않습니다. 검정과 흰색은 이 입력 범위의 모델 출력 끝점이며 측정된 인화지 Dmin/Dmax가 아닙니다.</p><p><a href="report.json">수치·SHA256 전체 JSON</a> · 동일 원본, LUT 100%, 사진별 자동 보정 없음</p>''']
    if report.get('allCatalogQaSummary'):
        overview=report['allCatalogQaSummary']
        parts.append('<h2>전체 238조합 · 보간 오차</h2><p>아래 전체 집계는 생성된 QA 파일의 SHA를 확인해 모은 값이며, 이어지는 4조합 독립 재계산과 구분됩니다. 33³ 호환성을 유지한 결과 일부 조합은 기준 0.02를 넘습니다. 파일·테스트 통과가 모든 색 영역의 보간 오차 통과를 뜻하지 않습니다.</p>')
        parts.append(table(['variant','random p99 >0.02','worst random p99','worst random max','photo p99 >0.02 combos','worst photo p99'],[[v,d['randomP99AboveThresholdCount'],d['worstRandomP99']['randomP99'],d['worstRandomMax']['randomMax'],d['photoP99AboveThresholdCombinationCount'],d['worstPhotoP99']['p99']] for v,d in overview['variants'].items()]))
        for v,d in overview['variants'].items():
            parts.append(f'<details><summary>{v} · 기준을 넘은 조합과 사진</summary>')
            parts.append(table(['combination ID','random p99','random max','worst photo','photo p99'],[[r['id'],r['randomP99'],r['randomMax'],r['worstPhotoP99']['sample'],r['worstPhotoP99']['p99']] for r in d['warningRows']]))
            parts.append('</details>')
        parts.append('<p class="note">전체 집계: 조합당 4,350개 합성 RGB · 사진당 고정 1,024픽셀. 아래 4조합 독립 감사는 4,225개 합성 RGB 및 사진 전체 영역의 4픽셀 간격 샘플을 사용합니다. 표본이 달라 p99도 다를 수 있습니다.</p>')
    parts.append('<nav aria-label="조합 바로가기">'+''.join(f'<a href="#{html.escape(r["id"])}">{html.escape(r["label"])}</a>' for r in report['combinations'])+'</nav>')
    for r in report['combinations']:
        parts.append(f'<h2 id="{html.escape(r["id"])}">{html.escape(r["label"])}</h2>')
        for photo in r['photos']:
            opened=' open' if photo['id']=='std_playground' else ''
            parts.append(f'<details{opened}><summary>{html.escape(photo["name"])}</summary><div class="scroll"><div class="photos">')
            for name,path in photo['images'].items():
                parts.append(f'<figure><img loading="lazy" src="{html.escape(path)}" alt="{html.escape(photo["name"]+" / "+name)}"><figcaption>{html.escape(name)}</figcaption></figure>')
            parts.append('</div></div></details>')
        parts.append('<details><summary>회색 · 색 변화 · 보간 오차 측정표</summary>')
        parts.append(table(['b linear Y','w linear Y','B k','monotonic correction','plateaus'],[[r['blackLinearY'],r['whiteLinearY'],r['rolloffK'],r['maxMonotonicCorrection'],r['plateaus']]]))
        parts.append('<h3>회색 입력 → 출력 휘도 (sRGB 코드, 0–255)</h3>')
        cols=r['grayTables'].keys()
        parts.append(table(['input']+list(cols),[[v]+[r['grayTables'][key][i] for key in cols] for i,v in enumerate(CODES)]))
        parts.append('<p class="note">Unprotected VLOG는 R(x), Legacy v3는 이전 JPG 보호 LUT입니다. A/B는 새 다운로드 CUBE를 독립 colour-science로 보간한 결과입니다. 서로 다른 목표 T를 생략한 비교는 구현 오류 검증에 사용할 수 없습니다.</p>')
        parts.append('<h3>중성 입력의 R−B · 동일 prewarp 위치에서 비교</h3>')
        castrows=[]
        for v in ['A','B']:
            for item in r['variants'][v]['neutralCastTable']:
                castrows.append([v,item['inputCode'],item['prewarpCode'],item['sourceMatchedRminusBCode'],item['referenceRminusBCode'],item['bakedRminusBCode'],item['sourceAtOriginalRminusBCode']])
        parts.append(table(['variant','input','P(T(g)) ×255','R(q) R−B ×255','reference R−B ×255','CUBE R−B ×255','R(g) R−B ×255'],castrows))
        parts.append('<h3>파일 vs 동일 목표를 포함한 독립 계산 R(P(T(x)))</h3>')
        parts.append(table(['variant','random p99 RGB','random max RGB','implementation max RGB','neutral cast R−B error max'],[[v,r['variants'][v]['offGridError']['p99'],r['variants'][v]['offGridError']['max'],r['variants'][v]['productionClassError']['max'],r['variants'][v]['matchedNeutralRedBlueErrorMax']] for v in ['A','B']]))
        parts.append('<h3>중간톤 색 변화 · 원본 OKLab L 0.35–0.85</h3><p class="note">동일 원본 픽셀 마스크를 사용합니다. iso-L Δ는 L 차이를 제외한 OKLab a,b 거리×100이며 CIE ΔE00가 아닙니다. 채도비는 원본 C&gt;0.02인 픽셀만 계산합니다. 표시용 사진의 L을 실제로 수정하지 않습니다.</p>')
        rows=[]
        for name, cm in r['aggregateMidtones'].items():
            rows.append([name,cm['deltaL']['mean'],cm['fullDeltaEOKx100']['mean'],cm['isoLChromaDeltaOKx100']['mean'],cm['chromaRatioSourceCAbove002']['p50'],cm['chromaRatioSourceCAbove002']['p95'],cm['chromaHigherPercent'],cm['chromaLowerPercent']])
        parts.append(table(['output','mean ΔL','mean full Δ','mean iso-L Δ','median C ratio','p95 C ratio','C↑ %','C↓ %'],rows))
        if 'opposedIsoLDirection' in r:
            parts.append('<h3>원본 대비 색 변화 방향이 반대인 비율</h3><p class="note">원본에서 v3 및 새 결과로 향하는 a,b 변화 벡터의 내적이 음수인 비율입니다. 양쪽 변화 크기가 모두 OKLab 0.005 이상인 픽셀만 포함합니다. 색상각 자체의 부호나 모든 픽셀의 방향을 뜻하지 않습니다.</p>')
            parts.append(table(['new variant','eligible / total','eligible %','opposed direction %'],[[v,f"{d['eligible']} / {d['totalMidtones']}",d['eligiblePercent'],d['opposedDirectionPercent']] for v,d in r['opposedIsoLDirection'].items()]))
        parts.append('</details>')
    if report.get('validation4BrowserPixelAgreement'):
        proof=report['validation4BrowserPixelAgreement']
        parts.append('<h2>웹 화면과 다운로드 LUT 일치</h2><p>Classic Chrome + Crystal Archive Type II, 업로드 std_figures.webp 1024×683 사진을 실제 브라우저에서 A/B로 처리했습니다. 화면 blob PNG와 실제 다운로드 CUBE를 colour-science로 적용한 RGB 바이트를 비교했습니다. 이 검증은 해당 조합과 업로드 한 장에 대한 결과입니다.</p>')
        parts.append(table(['variant','pixels','max byte error','exact RGB pixel %','download SHA matches catalog'],[[v,d['pixels'],d['maxByteError'],d['exactRGBPixelPercent'],d['downloadShaMatchesCatalog']] for v,d in proof['results'].items()]))
    parts.append('<h2>해석의 범위</h2><p>색이 있는 픽셀은 동일한 비선형 곡선을 R/G/B에 따로 적용하므로 채널 비율·색상·채도가 달라질 수 있습니다. 회색의 휘도 역함수가 3차원 색 변환이나 제조사 Standard 역함수를 뜻하지는 않습니다. 실카메라 검증에는 같은 장면의 V-Log + VLOG LUT와 Standard + STD LUT 촬영 쌍이 필요합니다.</p><p>부동소수점 단조성, 8비트 양자화, 33³ CUBE의 보간 오차를 따로 기록했습니다. B의 black floor는 의도한 한계이며 A의 끝부분 디테일 조건과 혼동하면 안 됩니다.</p></html>')
    (out/'index.html').write_text('\n'.join(parts))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=PUBLIC/'audit/std-precurve')
    parser.add_argument('--baseline',type=Path,default=ROOT/'artifacts/std-precurve-baseline')
    parser.add_argument('--only',action='append')
    parser.add_argument('--skip-native',action='store_true')
    args=parser.parse_args(); out=args.output; out.mkdir(parents=True,exist_ok=True)
    before=json.loads((args.baseline/'catalog.json').read_text())
    catalog=json.loads((PUBLIC/'catalog.json').read_text())
    old={c['id']:c for c in before['combinations']}
    films={f['id']:f['name'] for f in catalog['films']}
    papers={p['id']:p['name'] for p in catalog['papers']}
    samples=[s for s in catalog['samples'] if s.get('inputKind')=='camera-std']
    images={}
    for s in samples:
        path=PUBLIC/s['path'].lstrip('/')
        im=Image.open(path).convert('RGB'); im.thumbnail((420,280),Image.Resampling.LANCZOS)
        images[s['id']]=np.asarray(im)/255.
    gray=np.repeat((np.arange(256)/255)[:,None],3,axis=1)
    dense=np.repeat(np.linspace(0,1,4097)[:,None],3,axis=1)
    rng=np.random.default_rng(20261103)
    random=np.vstack([rng.random((4096,3)),dense[::32]])
    report={'generatedAt':datetime.now(timezone.utc).isoformat(),'reader':'colour-science '+colour.__version__,
            'grayInputCodes':CODES,'requestedGrayInputCodes':REQUESTED_CODES,'neutralCastInputCodes':CAST_CODES,
            'auditScriptSha256':digest(Path(__file__)),'precurveImplementationSha256':digest(ROOT/'pipeline/precurve.py'),
            'reference':'Independent colour LUT reader/tetrahedral; independently implemented F,N,P,T; R(P(T(x)))',
            'baselineCatalogSha256':digest(args.baseline/'catalog.json'),'catalogSha256':digest(PUBLIC/'catalog.json'),
            'pixelMask':'Original OKLab L 0.35..0.85; source chroma >0.02 for ratios; deterministic full-image stride',
            'sourceFiles':{s['id']:digest(PUBLIC/s['path'].lstrip('/')) for s in samples},'combinations':[],
            'allCatalogQaSummary':catalog_qa_summary(catalog),'integratedValidation':integrated_checks()}
    browser_evidence=ROOT/'artifacts/std-precurve-browser/independent-pixel-check.json'
    if browser_evidence.exists():
        report['validation4BrowserPixelAgreement']={
            'scope':'gfx_classic_chrome__fujifilm_crystal_archive_typeii; uploaded std_figures.webp; 1024x683; actual browser blob PNG versus independently applied downloaded CUBE',
            'method':'Separate browser capture by root; colour-science CUBE reader and tetrahedral; byte RGB comparison; this audit does not rerun browser interaction',
            'evidenceSha256':digest(browser_evidence),'results':json.loads(browser_evidence.read_text())}
    from pipeline.precurve import SingleTonePrecurve
    for cid in args.only or IDS:
        # Metadata can be audited once this combination is regenerated, even
        # while another worker has not yet finalized the aggregate catalog.
        combo=json.loads((PUBLIC/'luts'/cid/'metadata.json').read_text())
        if 'stdB' not in combo['files']:
            raise ValueError(f'A/B generation incomplete: {cid}')
        prev=old[cid]
        lutpaths={k:PUBLIC/combo['files'][k]['path'].lstrip('/') for k in ['vlog','std','stdB']}
        new={k:read_lut(p,combo['files'][k]['sha256']) for k,p in lutpaths.items()}
        oldpath=args.baseline/cid/prev['files']['std']['name']
        legacy=read_lut(oldpath,prev['files']['std']['sha256'])
        if combo['files']['vlog']['sha256']!=prev['files']['vlog']['sha256']:
            raise ValueError(f'Native VLOG changed: {cid}')
        ref=IndependentReference(new['vlog']); production=SingleTonePrecurve(ref.raw)
        label=films.get(combo['film'],combo['film'])+' + '+papers.get(combo.get('paper'),'Direct scan')
        r={'id':cid,'label':label,'metadataSha256':digest(PUBLIC/'luts'/cid/'metadata.json'),'sha256':{**{k:digest(v) for k,v in lutpaths.items()},'legacyStd':digest(oldpath)},
           'blackLinearY':float(ref.b),'whiteLinearY':float(ref.w),'rolloffK':float(ref.k),
           'decreasingSteps':int(np.count_nonzero(np.diff(ref.measured)<0)),
           'plateaus':int(np.count_nonzero(np.diff(ref.monotone)==0)),
           'maxMonotonicCorrection':float(np.max(ref.monotone-ref.measured)),
           'grayTables':{},'variants':{},'photos':[]}
        gray_outputs={'Unprotected VLOG':ref.raw(gray),'Legacy v3':apply(legacy,gray),
                      'A':apply(new['std'],gray),'B':apply(new['stdB'],gray)}
        if not args.skip_native:
            native=native_reference(combo,gray)
            if native is not None:
                gray_outputs={'Continuous native':native,**gray_outputs}
                r['sourceCubeVsContinuousNativeGray']=error(ref.raw(gray),native)
        r['grayTables']={key:(ey(value)[CODES]*255).tolist() for key,value in gray_outputs.items()}
        r['grayFloatAndQuantization']={key:gray_stats(value) for key,value in gray_outputs.items()}
        for v,key in [('A','std'),('B','stdB')]:
            truth=ref.render(random,v); actual=apply(new[key],random)
            prod=production.apply(random,v)
            matched=ref.raw(ref.warp(dense,v)); rendered=ref.render(dense,v)
            native_cast=matched[:,0]-matched[:,2]
            baked=apply(new[key],dense)
            tablegrid=new[key].linear_table(new[key].size).reshape(-1,3)
            node_error=error(apply(new[key],tablegrid),ref.render(tablegrid,v))
            r['variants'][v]={'offGridError':error(actual,truth),'gridNodeError':node_error,
                'productionClassError':error(prod,truth),
                'independentGrayDense':gray_stats(rendered),'bakedGrayDense':gray_stats(baked),
                'matchedNeutralRedBlueErrorMax':float(np.max(np.abs((rendered[:,0]-rendered[:,2])-native_cast))),
                'bakedMatchedNeutralRedBlueErrorMax':float(np.max(np.abs((baked[:,0]-baked[:,2])-native_cast))),
                'neutralCastTable':[],
                'inverseRoundtripEncodedYMax':float(np.max(np.abs(ey(rendered)-np.maximum(ref.target(dense,v)[:,0],ref.measured[0])))),
                'wrongReferenceWithoutTError':error(truth,ref.raw(ref.inverse(random))),
                'photoFidelity':{}}
            cg=np.repeat((np.asarray(CAST_CODES)/255)[:,None],3,axis=1)
            q=ref.warp(cg,v); matched_cast=ref.raw(q); cast_result=ref.render(cg,v); baked_cast=apply(new[key],cg); original_cast=ref.raw(cg)
            for i,code in enumerate(CAST_CODES):
                r['variants'][v]['neutralCastTable'].append({'inputCode':code,'prewarpCode':float(q[i,0]*255),
                    'sourceMatchedRminusBCode':float((matched_cast[i,0]-matched_cast[i,2])*255),
                    'referenceRminusBCode':float((cast_result[i,0]-cast_result[i,2])*255),
                    'bakedRminusBCode':float((baked_cast[i,0]-baked_cast[i,2])*255),
                    'sourceAtOriginalRminusBCode':float((original_cast[i,0]-original_cast[i,2])*255)})
            if node_error['max']>5.1e-7 or r['variants'][v]['productionClassError']['max']>1e-10:
                raise ValueError(f'Implementation mismatch {cid}/{v}: {r["variants"][v]}')
        aggregate_inputs=[]; aggregates={k:[] for k in ['Unprotected VLOG','Legacy v3','A','B']}
        folder=out/cid; folder.mkdir(exist_ok=True)
        for s in samples:
            full=np.asarray(Image.open(PUBLIC/s['path'].lstrip('/')).convert('RGB'))/255.
            # Cover the complete image at regular stride; no selection by output.
            pixels=full[::4,::4].reshape(-1,3)
            mask=(lab(pixels)[:,0]>=.35)&(lab(pixels)[:,0]<=.85)
            outputs={'Unprotected VLOG':ref.raw(pixels),'Legacy v3':apply(legacy,pixels),
                     'A':apply(new['std'],pixels),'B':apply(new['stdB'],pixels)}
            aggregate_inputs.append(pixels[mask])
            for key,value in outputs.items(): aggregates[key].append(value[mask])
            for v,key in [('A','std'),('B','stdB')]:
                r['variants'][v]['photoFidelity'][s['id']]=error(outputs[v],ref.render(pixels,v))
            rgb=images[s['id']]; shape=rgb.shape; flat=rgb.reshape(-1,3)
            rendered={'Original':rgb,'Unprotected VLOG':ref.raw(flat).reshape(shape),
                      'Legacy v3':apply(legacy,flat).reshape(shape),'A':apply(new['std'],flat).reshape(shape),
                      'B':apply(new['stdB'],flat).reshape(shape)}
            entry={'id':s['id'],'name':s['name'],'images':{},'midtones':{key:color_metrics(value[mask],pixels[mask]) for key,value in outputs.items()}}
            for key,value in rendered.items():
                filename=s['id']+'-'+key.lower().replace(' ','-')+'.webp'
                image_save(folder/filename,value)
                entry['images'][key]=cid+'/'+filename
            r['photos'].append(entry)
        inputs=np.concatenate(aggregate_inputs)
        r['aggregateMidtones']={key:color_metrics(np.concatenate(value),inputs) for key,value in aggregates.items()}
        r['newVsLegacyAtIsoL']={v:color_metrics(np.concatenate(aggregates[v]),np.concatenate(aggregates['Legacy v3'])) for v in ['A','B']}
        r['opposedIsoLDirection']={v:direction_metrics(np.concatenate(aggregates['Legacy v3']),np.concatenate(aggregates[v]),inputs) for v in ['A','B']}
        report['combinations'].append(r)
        print(json.dumps({'id':cid,'A':r['variants']['A']['offGridError'],'B':r['variants']['B']['offGridError']}),flush=True)
    (out/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
    (out/'all-combinations-summary.json').write_text(json.dumps(report['allCatalogQaSummary'],indent=2,ensure_ascii=False,allow_nan=False)+'\n')
    report_html(report,out)
    print(json.dumps({'report':str(out/'index.html'),'combinations':len(report['combinations'])}))


if __name__=='__main__':
    main()
