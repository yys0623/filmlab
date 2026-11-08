"""Read-only defect-oriented review of preserved v3 LUTs on current samples.

Writes only artifacts/legacy-v3-review. Never changes LUTs or the catalog.
Chroma increase is descriptive, not a defect criterion. Boundary clipping and
large local derivatives are review candidates, not automatic quality failures.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

import colour
import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
PUBLIC=ROOT/'public'
BASELINE=ROOT/'artifacts/std-precurve-baseline'
OUT=ROOT/'artifacts/legacy-v3-review'
W=np.array([.2126,.7152,.0722])


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def decode(x): return colour.models.eotf_sRGB(x)
def encode(x): return colour.models.eotf_inverse_sRGB(x)
def ey(x): return encode(decode(x)@W)
def lab(x): return colour.XYZ_to_Oklab(colour.sRGB_to_XYZ(x))
def apply(lut,x):
    return lut.apply(x,interpolator=colour.algebra.table_interpolation_tetrahedral)
def percent(mask): return float(np.mean(mask)*100) if np.size(mask) else None
def conditional_percent(mask,eligible):
    return percent(np.asarray(mask)[eligible]) if np.any(eligible) else None

def longest_run(values):
    values=np.asarray(values)
    if len(values)==0:return 0
    edges=np.r_[0,np.flatnonzero(np.diff(values)!=0)+1,len(values)]
    return int(np.max(np.diff(edges)))


def load_samples(catalog):
    samples=[x for x in catalog['samples'] if x.get('inputKind')=='camera-std']
    external=json.loads((PUBLIC/'samples/external/manifest.json').read_text())
    samples+=external['samples']
    arrays=[]; details=[]
    for sample in samples:
        path=PUBLIC/sample['path'].lstrip('/')
        expected=sample.get('preparedSha256')
        if expected and sha(path)!=expected:raise ValueError(f'Input SHA mismatch: {sample["id"]}')
        rgb=np.asarray(Image.open(path).convert('RGB'))/255.
        rows=np.rint(np.linspace(0,rgb.shape[0]-1,64)).astype(int)
        cols=np.rint(np.linspace(0,rgb.shape[1]-1,64)).astype(int)
        arrays.append(rgb[rows[:,None],cols[None,:]].reshape(-1,3))
        details.append({'id':sample['id'],'path':sample['path'],'sha256':sha(path),
            'width':rgb.shape[1],'height':rgb.shape[0],'rows':rows.tolist(),'cols':cols.tolist(),
            'kind':sample['inputKind']})
    return np.asarray(arrays),details


def gray_metrics(lut):
    axis=np.linspace(0,1,4097); gray=np.repeat(axis[:,None],3,axis=1)
    rgb=apply(lut,gray); y=ey(rgb); steps=np.diff(y)*255
    gray8=np.repeat((np.arange(256)/255.)[:,None],3,axis=1)
    rgb8=apply(lut,gray8); y8=ey(rgb8)*255; codes=np.floor(y8+.5).astype(int)
    return {'denseSamples':4097,'minimumEncodedYStep255':float(steps.min()),
        'decreasesAbove001Code':int(np.count_nonzero(steps<-.01)),
        'anyNegativeStepsAbove1e6Code':int(np.count_nonzero(steps<-1e-6)),
        'worstStepInputCode255':float(axis[np.argmin(steps)]*255),
        'gray8MinimumEncodedYStep255':float(np.diff(y8).min()),
        'gray8DistinctOutputYCodes':int(len(np.unique(codes))),
        'longestShadowPlateauInputCodes':longest_run(codes[:65]),
        'longestHighlightPlateauInputCodes':longest_run(codes[192:]),
        'gray8InputCodes':list(range(256)),'gray8OutputEncodedY255':y8.tolist(),
        'blackRGB':rgb[0].tolist(),'whiteRGB':rgb[-1].tolist(),
        'neutralMaxChannelSpread':float(np.ptp(rgb,axis=1).max())}


def local_metrics(lut,probes,probe_sources):
    before=apply(lut,probes); before_lab=lab(before); source_lab=lab(probes)
    records=[]; flagged=[]; photo_flags=[]
    for channel in range(3):
        moved=probes.copy()
        step=np.where(moved[:,channel]<=254/255,1/255,-1/255)
        moved[:,channel]+=step
        after=apply(lut,moved); after_lab=lab(after)
        distance=100*np.linalg.norm(after_lab-before_lab,axis=1)
        source_distance=100*np.linalg.norm(lab(moved)-source_lab,axis=1)
        gain=np.divide(distance,source_distance,out=np.zeros_like(distance),where=source_distance>1e-8)
        delta_ab=100*np.linalg.norm(after_lab[:,1:]-before_lab[:,1:],axis=1)
        chroma0=np.linalg.norm(before_lab[:,1:],axis=1);chroma1=np.linalg.norm(after_lab[:,1:],axis=1)
        angle0=np.arctan2(before_lab[:,2],before_lab[:,1]);angle1=np.arctan2(after_lab[:,2],after_lab[:,1])
        angle=np.abs(np.angle(np.exp(1j*(angle1-angle0))))*180/np.pi
        hue_flag=(chroma0>.02)&(chroma1>.02)&(angle>10)&(delta_ab>1)
        flag=(distance>2)&(gain>4)
        for ix in np.flatnonzero(flag|hue_flag):
            item={'probe':probe_sources[int(ix)],'channel':channel,'sourceRGB':probes[ix].tolist(),
                'inputStep255':float(step[ix]*255),'outputRGB':before[ix].tolist(),'perturbedOutputRGB':after[ix].tolist(),
                'deltaEOKx100':float(distance[ix]),'sourceDeltaEOKx100':float(source_distance[ix]),
                'localGain':float(gain[ix]),'deltaAbOKx100':float(delta_ab[ix]),'hueChangeDegrees':float(angle[ix]),
                'largeStepFlag':bool(flag[ix]),'hueStepFlag':bool(hue_flag[ix])}
            flagged.append(item)
            if item['probe']['type']=='photo':photo_flags.append(item)
        ix=int(np.argmax(distance))
        records.append({'channel':channel,'maximumDeltaEOKx100':float(distance[ix]),
            'maximumRGBByteChange':float(np.max(np.abs(after-before))*255),
            'p99DeltaEOKx100':float(np.quantile(distance,.99)),
            'largeStepCount':int(flag.sum()),'hueStepCount':int(hue_flag.sum()),
            'maxProbe':probe_sources[ix],'maxSourceRGB':probes[ix].tolist()})
    return {'perturbation':'One encoded source RGB channel by +/-1/255; same pixel, no spatial image-edge comparison',
        'probes':len(probes),'perChannel':records,
        'largeOrHueStepCount':len(flagged),'photoLargeOrHueStepCount':len(photo_flags),
        'topCandidates':sorted(flagged,key=lambda x:x['deltaEOKx100'],reverse=True)[:12],
        'topPhotoCandidates':sorted(photo_flags,key=lambda x:x['deltaEOKx100'],reverse=True)[:8]}


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    base=json.loads((BASELINE/'catalog.json').read_text()); current=json.loads((PUBLIC/'catalog.json').read_text())
    combinations=[c for c in base['combinations'] if (BASELINE/c['id']/c['files']['std']['name']).exists()]
    assert len(combinations)==238
    source,samples=load_samples(current); assert len(samples)==35
    source_y=ey(source); source_lab=lab(source)
    source_black=source<.5/255; source_white=source>=254.5/255
    source_interior=(source>=8/255)&(source<=247/255)
    dark_eligible=(source_y>=16/255)&(source_y<=64/255)
    highlight_eligible=(source_y>=192/255)&(source_y<=235/255)
    # Fixed actual-photo probe subset plus neutral and random RGB coordinates.
    indices=np.rint(np.linspace(0,4095,64)).astype(int)
    photo_probes=source[:,indices].reshape(-1,3)
    locations=[]
    for s in samples:
        for ix in indices:
            locations.append({'type':'photo','sample':s['id'],'gridIndex':int(ix),
                'x':s['cols'][ix%64],'y':s['rows'][ix//64]})
    rng=np.random.default_rng(20261104); random=rng.random((512,3))
    gray=np.repeat((np.arange(256)/255)[:,None],3,axis=1)
    probes=np.vstack([photo_probes,random,gray])
    locations += [{'type':'synthetic','index':i} for i in range(512)]
    locations += [{'type':'gray','inputCode':i} for i in range(256)]
    report={'createdAt':datetime.now(timezone.utc).isoformat(),
        'baselineCatalogSha256':sha(BASELINE/'catalog.json'),'currentCatalogSha256':sha(PUBLIC/'catalog.json'),
        'reader':'colour-science '+colour.__version__,'lookCount':len(combinations),'sampleCount':len(samples),
        'samplesPerPhoto':4096,'sampling':'64x64 grid of actual existing image pixels, no additional image resize',
        'definitions':{
            'shadowLoss':'Input encoded linear-Y 16..64/255; output encoded linear-Y below 4/255',
            'highlightLoss':'Input encoded linear-Y 192..235/255; output encoded linear-Y at least 250/255',
            'newBlackChannel':'Output channel <0.5/255 while same input channel >=0.5/255',
            'newWhiteChannel':'Output channel >=254.5/255 while same input channel <254.5/255',
            'interiorClipping':'New boundary channel where input channel was 8..247/255; distinguishes near-boundary rounding',
            'localStepReview':'One-channel input step 1/255 yielding DeltaEOK*100 >2 and local gain >4, OR hue angle change >10 degrees with both C>0.02 and delta-ab*100>1',
            'judgement':'Clipping and local step flags are review candidates. Chroma increase alone is not a defect. No physical film or camera accuracy is asserted.'},
        'samples':samples,'combinations':[]}
    for n,c in enumerate(combinations,1):
        path=BASELINE/c['id']/c['files']['std']['name']
        if sha(path)!=c['files']['std']['sha256']:raise ValueError('Baseline LUT hash changed: '+c['id'])
        lut=colour.read_LUT(str(path)); output=apply(lut,source)
        if not np.isfinite(output).all() or output.min()<-1e-9 or output.max()>1+1e-9:
            raise ValueError('Nonfinite/out-of-range output: '+c['id'])
        out_y=ey(output); out_lab=lab(output)
        black=output<.5/255;white=output>=254.5/255
        new_black=black&~source_black;new_white=white&~source_white
        strong_black=new_black&source_interior; strong_white=new_white&source_interior
        shadow_loss=out_y<4/255; highlight_loss=out_y>=250/255
        color0=np.linalg.norm(source_lab[...,1:],axis=-1);color1=np.linalg.norm(out_lab[...,1:],axis=-1)
        cromamask=(source_lab[...,0]>=.35)&(source_lab[...,0]<=.85)&(color0>.02)
        ratios=color1[cromamask]/color0[cromamask]
        entry={'id':c['id'],'mode':c['processMode'],'stdSha256':sha(path),
            'allFiniteAndInRange':True,'gray':gray_metrics(lut),'photos':[],
            'chromaDescriptionOnly':{'eligiblePixels':int(cromamask.sum()),'medianRatio':float(np.median(ratios)),
                'p95Ratio':float(np.quantile(ratios,.95)),'higherPercent':percent(ratios>1)}}
        for i,s in enumerate(samples):
            entry['photos'].append({'id':s['id'],
                'sourceClippedChannelPercent':percent(source_black[i]|source_white[i]),
                'outputClippedChannelPercent':percent(black[i]|white[i]),
                'newBlackChannelPercent':percent(new_black[i]),'newWhiteChannelPercent':percent(new_white[i]),
                'newInteriorBlackChannelPercent':percent(strong_black[i]),'newInteriorWhiteChannelPercent':percent(strong_white[i]),
                'newInteriorClippedPixelPercent':percent(np.any(strong_black[i]|strong_white[i],axis=-1)),
                'shadowEligiblePixels':int(dark_eligible[i].sum()),
                'shadowLossPixels':int(np.count_nonzero(shadow_loss[i]&dark_eligible[i])),
                'shadowLossEligiblePercent':conditional_percent(shadow_loss[i],dark_eligible[i]),
                'highlightEligiblePixels':int(highlight_eligible[i].sum()),
                'highlightLossPixels':int(np.count_nonzero(highlight_loss[i]&highlight_eligible[i])),
                'highlightLossEligiblePercent':conditional_percent(highlight_loss[i],highlight_eligible[i]),
                'sourceYCodesP01P50P99':(np.quantile(source_y[i],[.01,.5,.99])*255).tolist(),
                'outputYCodesP01P50P99':(np.quantile(out_y[i],[.01,.5,.99])*255).tolist(),
                'maximumDarkeningCode255':float(np.max((source_y[i]-out_y[i])*255)),
                'maximumBrighteningCode255':float(np.max((out_y[i]-source_y[i])*255))})
        entry['totals']={'newInteriorBlackChannels':int(strong_black.sum()),'newInteriorWhiteChannels':int(strong_white.sum()),
            'newInteriorClippedPixelPercent':percent(np.any(strong_black|strong_white,axis=-1)),
            'shadowLossPixels':int(np.count_nonzero(shadow_loss&dark_eligible)),
            'highlightLossPixels':int(np.count_nonzero(highlight_loss&highlight_eligible))}
        # Save a few precise examples for later exact-engine diagnosis.
        candidates=np.flatnonzero(np.any(strong_black|strong_white,axis=-1).reshape(-1))
        severity=np.max(np.maximum(source-output,output-source),axis=-1).reshape(-1)
        candidates=candidates[np.argsort(severity[candidates])[-8:][::-1]] if len(candidates) else []
        entry['clippingExamples']=[]
        for ix in candidates:
            si,pi=divmod(int(ix),4096); sm=samples[si]
            entry['clippingExamples'].append({'sample':sm['id'],'x':sm['cols'][pi%64],'y':sm['rows'][pi//64],
                'sourceRGB':source[si,pi].tolist(),'outputRGB':output[si,pi].tolist(),
                'newInteriorBlackChannels':np.flatnonzero(strong_black[si,pi]).tolist(),
                'newInteriorWhiteChannels':np.flatnonzero(strong_white[si,pi]).tolist()})
        entry['localResponse']=local_metrics(lut,probes,locations)
        report['combinations'].append(entry)
        if n%10==0 or n==len(combinations):print(f'Audited {n}/{len(combinations)}',flush=True)
    combos=report['combinations']
    summary={'finiteAndInRangeCombinations':sum(x['allFiniteAndInRange'] for x in combos),
        'grayReversalCombinations':[{'id':x['id'],'minimumStep255':x['gray']['minimumEncodedYStep255'],'count':x['gray']['decreasesAbove001Code']} for x in combos if x['gray']['decreasesAbove001Code']],
        'shadowLossCombinations':[{'id':x['id'],'pixels':x['totals']['shadowLossPixels']} for x in combos if x['totals']['shadowLossPixels']],
        'highlightLossCombinations':[{'id':x['id'],'pixels':x['totals']['highlightLossPixels']} for x in combos if x['totals']['highlightLossPixels']],
        'newInteriorClippingCombinationCount':sum(x['totals']['newInteriorBlackChannels']+x['totals']['newInteriorWhiteChannels']>0 for x in combos),
        'largestInteriorClipping':[{'id':x['id'],**x['totals']} for x in sorted(combos,key=lambda z:z['totals']['newInteriorClippedPixelPercent'],reverse=True)[:15]],
        'largeLocalStepCombinationCount':sum(any(p['largeStepCount']>0 for p in x['localResponse']['perChannel']) for x in combos),
        'largeLocalStepProbeCount':sum(sum(p['largeStepCount'] for p in x['localResponse']['perChannel']) for x in combos),
        'hueAngleReviewCombinationCount':sum(any(p['hueStepCount']>0 for p in x['localResponse']['perChannel']) for x in combos),
        'hueAngleReviewProbeCount':sum(sum(p['hueStepCount'] for p in x['localResponse']['perChannel']) for x in combos),
        'largeOrHueReviewCombinationCount':sum(x['localResponse']['largeOrHueStepCount']>0 for x in combos),
        'photoLargeOrHueReviewCombinationCount':sum(x['localResponse']['photoLargeOrHueStepCount']>0 for x in combos),
        'largestLocalSteps':[{'id':x['id'],'candidates':x['localResponse']['topCandidates'][:3]} for x in sorted(combos,key=lambda z:max(a['maximumDeltaEOKx100'] for a in z['localResponse']['perChannel']),reverse=True)[:15]]}
    report['summary']=summary
    (OUT/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ['largestInteriorClipping','largestLocalSteps']},ensure_ascii=False))


if __name__=='__main__':main()
