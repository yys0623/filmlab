"""Prepare the previously collected review JPEGs for local Film Lab use.

Run from film-lab: .venv/bin/python -m pipeline.import_external_samples
Only originals are read; old sample-study film renders are never used.
No LUT, main catalog, or colour-engine generation is performed.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import subprocess
from urllib.parse import urlparse

import numpy as np
from PIL import Image, ImageCms, ImageOps, __version__ as PILLOW_VERSION

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT.parent / 'sample-study'
DEST = ROOT / 'public/samples/external'
CAMERA_MODELS = {'s5m2':'DC-S5M2','s1m2':'DC-S1M2','s1r2':'DC-S1RM2','l10':'DMC-L10','s9':'DC-S9'}
SCENE_EN = {'sunny':'Outdoors · sunshine','cloudy':'Outdoors · overcast',
    'indoor-bright':'Indoors · bright light','indoor-dim':'Indoors · dim light',
    'portrait-sunny':'Portrait · sunshine','portrait-cloudy':'Portrait · overcast / soft light',
    'portrait-indoor':'Indoor portrait'}
# Deliberate translations preserve uncertainty, mixed lighting and early samples.
EN = {
 'dpr-s5m2-23':('Sunlit Tokyo street','Deep building shadows and bright pavement. Backlighting already makes the source shadows dark.'),
 's5m2-84':('Overcast square','Classified as overcast from the cloud-covered sky and soft shadows; weather was not independently verified.'),
 's5m2-57':('Bright exhibition hall','An indoor exhibition space with ceiling lights on.'),
 's5m2-71':('Dim exhibition hall','An exhibition space with a dark background and localized lighting.'),
 'dpr-s5m2-24':('Backlit street portrait','A street portrait in strong backlight. The face is in shadow, rather than directly sunlit.'),
 's5m2-45':('Street portrait in soft light','No clear direct-sun shadows. The sky is not visible, so overcast weather cannot be confirmed.'),
 's5m2-01':('Indoor portrait in warm light','An indoor portrait at a table with flowers.'),
 'dpr-s1m2pre-12':('City and rail infrastructure in sunshine','A DPReview pre-production sample with bright sky, sunlit city and industrial structures, and deep ground shadows. No extra exposure adjustment is applied.'),
 's1m2-04':('Lake in an overcast park','A lake with gray clouds and diffuse light. The weather classification is an inference from the image.'),
 'dpr-s1m2pre-07':('Dog in a dim room','A dog beneath an indoor table. The original was shot at ISO 12800; no extra noise reduction or brightness adjustment is applied.'),
 'dpr-s1m2-13':('Portrait with sunlight and blue bounce','The source describes sunlight on one side of the face and blue reflected light on the other. No additional exposure adjustment is applied.'),
 'dpr-s1m2pre-08':('Portrait by a doorway in soft light','Soft outdoor light. The image does not establish whether the light comes from an overcast sky or building shade.'),
 'dpr-s1m2-03':('Indoor portrait with a cat','An indoor portrait on a sofa. Noise from the ISO 6400 source is retained.'),
 'dpr-s1r2-14':('Garden in sunshine','A garden with clear sky and distinct shadows. A single-capture JPEG.'),
 'dpr-s1r2-35':('Snow under an overcast sky','Snow-covered buildings beneath clouds. A single-capture JPEG; weather is classified from the image.'),
 'dpr-s1r2-29':('Indoor portrait by a window','An indoor portrait apparently lit by a window. The same frame represents both bright indoor light and an indoor portrait.'),
 'cl-s1r2-16':('Café in warm indoor light','Cups and glasses in a café, with indoor lamps and a dark background. EXIF reports early firmware Ver.0.5; production-camera status is not confirmed.'),
 'dpr-s1r2-37':('Outdoor portrait in direct sun','An outdoor portrait under a clear sky, with strong light on skin and clothing.'),
 'dpr-s1r2-10':('Portrait in falling snow','A portrait in falling snow and diffuse light; this is not a dry overcast scene.'),
 'l10-11':('White architecture in sunshine','A blue sky and distinct light and shadow on a white building.'),
 'dpr-l10-05':('Interior beneath a glass roof','An interior lit by natural light through a glass roof.'),
 'dpr-l10-07':('Indoor portrait in soft window light','A window-lit indoor portrait. ISO 320, f/5.6 and 1/30 s support its low-light classification. The same frame represents dim interiors and indoor portraits.'),
 'dpr-l10-03':('Person resting in sunshine','An outdoor environmental portrait by a river. It is more useful for overall colour and tone than close-up skin comparison.'),
 's9-12':('Colourful playground in sunshine','Playground equipment and flooring in bright sunshine.'),
 's9-13':('Shopping street in diffuse light','A street with soft shadows. Only a small part of the sky is visible, so the weather classification is tentative.'),
 's9-08':('Brightly lit bar interior','A bar interior with ceiling lights and light from windows.'),
 's9-01':('Food in a dim restaurant','Warm indoor lighting. White balance already present in the JPEG is retained.'),
 's9-37':('Street portrait outside a shop','A street portrait with strong light and a distinct shadow on the wall.'),
 's9-16':('Street portrait in shade','A street portrait in soft light. Building shade is possible, so overcast weather is not confirmed.'),
 's9-26':('Environmental portrait inside a shop','A scene with staff and customers inside a shop. An approximate indoor-portrait example, not a frontal skin close-up.'),
}


# Newly selected from an already downloaded original; kept separate from the
# historical study manifest, with a pinned SHA and explicit source evidence.
SUPPLEMENTS = [{'id': 'dpr-s1m2pre-12',
  'camera': 's1m2',
  'cameraName': 'LUMIX S1 II',
  'scenes': ['sunny'],
  'title': '햇살 아래 도시·철도 시설',
  'note': 'DPReview 사전 양산 샘플. 밝은 하늘과 도시·산업 시설, 지면의 깊은 그늘이 함께 있는 장면. 완성된 JPEG의 노출을 추가로 바꾸지 않음.',
  'conditionEvidence': '원본 장면 확인: 파란 하늘, 건물 직사광과 깊은 지면 그림자',
  'source': 'https://www.dpreview.com/sample-galleries/6093167269/panasonic-s1ii-pre-production-sample-gallery/',
  'credit': 'DPReview',
  'sourceSha256': '1878e0bf04fbd4f838a2b3da1f6a5c143dedbc40ddf1dbd875b432ac0f91698d',
  'metadata': {'Model': 'DC-S1M2',
               'PhotoStyle': 'Standard or Custom',
               'LUT1Name': '',
               'LUT1Opacity': 0,
               'LUT2Name': '',
               'LUT2Opacity': 0,
               'ContrastMode': 1,
               'Contrast': 'Normal',
               'Saturation': 'Normal',
               'Sharpness': 'Normal',
               'ColorSpace': 'sRGB',
               'Software': 'Ver.1.0',
               'ExposureTime': '1/1000',
               'FNumber': 4.0,
               'ISO': 100,
               'Orientation': 'Horizontal (normal)',
               'Artist': '',
               'ImageWidth': 6000,
               'ImageHeight': 4000,
               'FilterEffect': 'Off'},
  'stdEvidence': 'PhotoStyle: Standard or Custom · LUT 1/2: 0%',
  'preproduction': True,
  'originalUrl': 'https://www.dpreview.com/wp-content/uploads/sample_galleries/L-6093167269/8349803513.jpg?original'}]

def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_metadata(paths):
    fields=['-Model','-PhotoStyle','-FilmMode','-LUT*','-Contrast*','-Saturation','-Sharpness',
        '-ColorSpace','-Software','-ExposureTime','-FNumber','-ISO','-Orientation','-Artist',
        '-ImageWidth','-ImageHeight','-Filter*']
    rows=json.loads(subprocess.check_output(['exiftool','-json',*fields,*map(str,paths)]))
    return {Path(row.pop('SourceFile')).stem:row for row in rows}


def validate_metadata(entry, metadata):
    sid=entry['id']; camera=entry['camera']
    if metadata.get('Model') != CAMERA_MODELS[camera]:
        raise ValueError(f'Unexpected camera model: {sid}')
    if not (metadata.get('PhotoStyle')=='Standard or Custom' or metadata.get('FilmMode')=='Standard (color)'):
        raise ValueError(f'No expected Standard tag: {sid}')
    if metadata.get('LUT1Name') or metadata.get('LUT2Name'):
        raise ValueError(f'LUT name is not empty: {sid}')
    if camera in ('s1m2','s1r2','s9') and not (metadata.get('LUT1Opacity')==0 and metadata.get('LUT2Opacity')==0):
        raise ValueError(f'Both LUT opacity tags must be zero: {sid}')
    if metadata.get('ColorSpace') != 'sRGB':
        raise ValueError(f'Unexpected input colour-space tag: {sid}')
    if metadata != entry['metadata']:
        raise ValueError(f'EXIF differs from the preserved study manifest: {sid}')


def save_lossless(image, path, icc):
    image.save(path,format='WEBP',lossless=True,method=6,icc_profile=icc)
    with Image.open(path) as decoded:
        if decoded.size != image.size or not decoded.info.get('icc_profile'):
            raise ValueError(f'Bad dimensions or missing ICC: {path.name}')
        if not np.array_equal(np.asarray(decoded.convert('RGB')),np.asarray(image)):
            raise ValueError(f'Lossless pixel verification failed: {path.name}')


def main():
    manifest=json.loads((STUDY/'manifest.json').read_text())
    selected=[x for x in manifest['samples'] if x.get('source')]+SUPPLEMENTS
    if len(selected)!=30 or set(EN)!={x['id'] for x in selected}:
        raise ValueError('Expected 29 preserved external samples plus one documented supplement; update translations deliberately for new inputs')
    paths=[STUDY/'originals'/f"{x['id']}.jpg" for x in selected]
    metadata=read_metadata(paths)
    # Validate every input before creating any output.
    for entry,path in zip(selected,paths):
        if sha256(path)!=entry['sourceSha256']:
            raise ValueError(f'Original SHA256 mismatch: {entry["id"]}')
        validate_metadata(entry,metadata[entry['id']])
    DEST.mkdir(parents=True,exist_ok=True)
    profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB'))
    icc=profile.tobytes()
    output=[]
    for entry,path in zip(selected,paths):
        with Image.open(path) as raw:
            embedded=raw.info.get('icc_profile')
            prepared=ImageOps.exif_transpose(raw).convert('RGB')
            if embedded:
                prepared=ImageCms.profileToProfile(prepared,ImageCms.ImageCmsProfile(io.BytesIO(embedded)),profile,outputMode='RGB')
            prepared.thumbnail((1600,1600),Image.Resampling.LANCZOS)
        sid=entry['id']; full=DEST/f'{sid}.webp'; thumbnail=DEST/f'{sid}-thumb.webp'
        save_lossless(prepared,full,icc)
        thumb=prepared.copy();thumb.thumbnail((320,240),Image.Resampling.LANCZOS)
        save_lossless(thumb,thumbnail,icc)
        english_name,english_note=EN[sid]
        note=entry['note']
        if sid=='cl-s1r2-16':
            note+=' EXIF는 초기 펌웨어 Ver.0.5이며 양산 카메라 여부는 확인하지 못했습니다.'
        if entry['camera']=='l10':
            evidence_en='FilmMode: Standard (color)'
        elif entry['camera']=='s5m2':
            evidence_en='PhotoStyle: Standard or Custom · LUT name empty (opacity tags unavailable)'
        else:
            evidence_en='PhotoStyle: Standard or Custom · LUT 1/2 opacity: 0%'
        output.append({'id':'external-'+sid,'name':entry['title'],'nameEn':english_name,
            'category':' / '.join(manifest['scenes'][x] for x in entry['scenes']),
            'categoryEn':' / '.join(SCENE_EN[x] for x in entry['scenes']),
            'credit':entry['credit'],'source':entry['source'],'originalUrl':entry['originalUrl'],
            'path':'/samples/external/'+full.name,'thumbnailPath':'/samples/external/'+thumbnail.name,
            'width':prepared.width,'height':prepared.height,'inputKind':'review-jpeg','previewLut':'std',
            'cameraId':entry['camera'],'cameraName':entry['cameraName'],'scenes':entry['scenes'],
            'notes':note,'notesEn':english_note,'stdEvidence':entry['stdEvidence'],'stdEvidenceEn':evidence_en,
            'preproduction':entry['preproduction'],
            'sourceFilename':Path(urlparse(entry['originalUrl']).path).name,
            'sourceSha256':entry['sourceSha256'],'preparedSha256':sha256(full),
            'cameraMetadata':metadata[sid]})
        print(f'Prepared {sid}: {prepared.width}x{prepared.height}',flush=True)
    missing=[
        {'camera':'s1m2','scene':'indoor-bright','reason':'이전 자료의 이 조건에는 사용자 실내 피규어 사진을 사용했습니다. 외부 촬영 원본은 이번 목록에 없습니다.','reasonEn':'The previous study used the user’s indoor figures photo for this condition. No external source is included here.'},
        {'camera':'l10','scene':'cloudy','reason':'확인한 원본에서 흐린 야외와 Standard 조건을 충족하는 사진을 확보하지 못했습니다.','reasonEn':'No verified source combining an overcast outdoor scene and Standard capture was available.'},
        {'camera':'l10','scene':'portrait-cloudy','reason':'흐린 날 야외 인물과 Standard 조건을 충족하는 촬영 원본을 확보하지 못했습니다.','reasonEn':'No verified Standard original of an outdoor portrait in overcast weather was available.'},
    ]
    result={'schemaVersion':1,'localOnly':True,
        'models':[{'id':k,'name':v} for k,v in manifest['models'].items()],
        'scenes':[{'id':k,'name':v,'nameEn':SCENE_EN[k]} for k,v in manifest['scenes'].items()],
        'missing':missing,'samples':output,
        'preparation':{'source':'Previously collected review JPEG originals, SHA256 and EXIF reverified',
            'steps':['EXIF orientation','Embedded ICC to sRGB when present; otherwise verified EXIF sRGB','Lanczos resize, longest side at most 1600','Lossless WebP with sRGB ICC','Separate aspect-preserving thumbnail within 320x240'],
            'lutApplied':False,'extraColourEdits':False,'originalsVerified':len(output),
            'losslessDecodedPixelsVerified':len(output)*2,'pillowVersion':PILLOW_VERSION,
            'studyManifestSha256':sha256(STUDY/'manifest.json')},
        'rights':'localOnly is a distribution scope flag, not a redistribution licence. Copyright remains with each source; attribution is not permission.'}
    target=DEST/'manifest.json'; temp=DEST/'manifest.json.tmp'
    temp.write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+'\n');temp.replace(target)
    print(json.dumps({'samples':len(output),'byCamera':dict(Counter(x['cameraId'] for x in output)),
        'coveredCameraSceneSlots':sum(len(x['scenes']) for x in output),'missingSlots':len(missing),
        'manifest':str(target)},ensure_ascii=False))


if __name__=='__main__':
    main()
