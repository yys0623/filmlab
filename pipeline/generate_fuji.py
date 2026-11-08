"""Append official Fuji simulations + optional virtual digital printing.

Run .venv/bin/python -m pipeline.generate_fuji --download --jobs 2
Existing 148 native looks are verified and preserved. Source package stays in .cache.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import shutil
import time
import zipfile
from functools import lru_cache

import numpy as np
from PIL import Image
from pipeline.common import ROOT, PUBLIC, UPSTREAM, CONFIG, save_json, sha256, read_cube, metrics, std_to_vlog
from pipeline.generate import describe, valid_assets
from pipeline.samples import save_image
from pipeline.fuji import METHOD_ID, load_study, official_archive, apply_official_native
from pipeline.camera_std import backup_record, rebuild_standard, camera_catalog, METHOD as GENERATION
from pipeline.fuji_paper import PaperBridge
from spektrafilm_lut_creator.formats import Lut
from spektrafilm_lut_creator.formats.lumix import LumixCubeFormat
from spektrafilm_lut_creator.grid import cube_grid
from spektrafilm_lut_creator.qa.evaluators import apply_tetrahedral

TRUTH = {'officialSource': True, 'officialUnmodifiedProduct': False,
         'physicalFilmCalibrated': False, 'cameraVerified': False,
         'outputIsRealFilm': False, 'outputOrigin': 'official_lut_with_film_lab_adapter'}

@lru_cache(maxsize=8)
def paper_bridge(paper_id):
    return PaperBridge(paper_id)

@lru_cache(maxsize=6)
def source_pixels(path):
    return np.asarray(Image.open(PUBLIC / path.lstrip('/')).convert('RGB')) / 255.


def generate_look(study, look, paper, number, samples, force=False):
    started = time.perf_counter()
    film_id = look['film']
    paper_id = paper['id'] if paper else None
    mode = 'official_print' if paper else 'official_direct'
    combo_id = f'{film_id}__{paper_id or "official_direct"}'
    directory = PUBLIC / 'luts' / combo_id
    metadata_path = directory / 'metadata.json'
    key = hashlib.sha256(json.dumps({'study': study, 'look': look, 'paper': paper,
          'config': CONFIG,
          'code': {n: sha256(ROOT / 'pipeline' / n) for n in ['fuji.py','fuji_paper.py','camera_std.py','generate_fuji.py','common.py','research.py','samples.py']},
          'samples': {s['id']: sha256(PUBLIC / s['path'].lstrip('/')) for s in samples}}, sort_keys=True).encode()).hexdigest()
    if metadata_path.exists():
        previous = json.loads(metadata_path.read_text())
        if not force and previous.get('cacheKey') == key and valid_assets(previous): return previous
        if previous.get('status') == 'ready' and previous.get('qa', {}).get('stdGeneration') != GENERATION:
            backup_record(previous)
    directory.mkdir(parents=True, exist_ok=True)
    bridge = paper_bridge(paper_id) if paper_id else None
    def transform(values): return apply_official_native(values, film_id, 'vlog', bridge)
    raw = transform(cube_grid(33)).reshape(33,33,33,3)
    if not np.isfinite(raw).all() or raw.min() < 0 or raw.max() > 1: raise ValueError('Invalid output')
    path = directory / f'{number:04d}VLOG.cube'
    LumixCubeFormat().write(Lut(raw, title=f'{number:04d}_VLOG'), path, photo_style_tag='VLOG')
    table = read_cube(path, 'VLOG')
    serialization_error = float(np.max(np.abs(raw-table)))
    if serialization_error > .000000501: raise ValueError('Serialization precision failed')
    gray = np.repeat(np.linspace(0,1,129)[:,None],3,axis=1)
    points = np.concatenate([np.random.default_rng(CONFIG['seed']).random((4096,3)),gray,cube_grid(5)])
    fidelity = {'tetrahedral':metrics(apply_tetrahedral(table,points),transform(points))}
    envelope = std_to_vlog(points)
    envelope_fidelity = metrics(apply_tetrahedral(table,envelope),transform(envelope))
    qa = {'fileChecks':'passed','cameraVerified':False,'warnings':[],'processMode':mode,
          'referenceModel':METHOD_ID,'rowsPerCube':35937,'serializationMaxError':serialization_error,
          'vlogVsDirectEngine':fidelity,'vlogWithinSrgbEnvelope':envelope_fidelity,
          'officialLutSha256':look['sourceSha256'],**TRUTH}
    save_json(directory/'qa.json',qa)
    provenance = {'methodId':METHOD_ID,'processMode':mode,'film':film_id,'paper':paper_id,
        'source':{key:study[key] for key in ['model','packageVersion','sourceLutVersion','sourceUrl','downloadUrl','sourceSha256','sourceInput','sourceOutput','rights']},
        'sourceLut':look,'inputAdapter':{
            'vlog':'V-Log decode -> V-Gamut to F-Gamut linear matrix -> official F-Log2 encoding, code clamp 0..1. This bounds negative/out-of-F-Gamut coordinates in code space: code0 corresponds to negative linear reflection, not linear0. No extra display shoulder. Not a measured sensor match.'},
        'paperBridge':bridge.metadata() if bridge else None,
        'upstream':{'repository':'https://github.com/andreavolpato/spektrafilm','commit':CONFIG['engine_commit'],'author':'Andrea Volpato','filmStagesApplied':False,'paperDevelopScanApplied':bool(bridge)},
        'officialSourceResolution':65,'exportResolution':33,'effects':{'grain':False,'halation':False,'autoExposure':False},**TRUTH}
    save_json(directory/'provenance.json',provenance)
    if not (directory/'CHANGELOG.txt').exists():
        (directory/'CHANGELOG.txt').write_text('Official65 source and optional virtual paper bridge exported as a 33-grid VLOG renderer. Source rights retained.\n')
    (directory/'FUJIFILM_NOTICE.txt').write_text(study['rights']+'\n'+study['sourceUrl']+'\n')
    shutil.copyfile(UPSTREAM/'SPEKTRAFILM_LICENSE.txt',directory/'SPEKTRAFILM_LICENSE.txt')
    record={'id':combo_id,'film':film_id,'paper':paper_id,'number':number,'processMode':mode,'status':'ready','cacheKey':key,
            'files':{'vlog':describe(path),'qa':describe(directory/'qa.json'),'provenance':describe(directory/'provenance.json')},
            'qa':qa,**TRUTH}
    record=rebuild_standard(record,samples,backup=False)
    record['seconds']=round(time.perf_counter()-started,3)
    save_json(metadata_path,record)
    return record


def generate_film(args):
    study,look,papers,samples,force=args
    result=[]
    for index,paper in enumerate([None,*papers]):
        record=generate_look(study,look,paper,look['numberStart']+index,samples,force)
        result.append(record)
        print(f"ready {record['id']} ({record['seconds']}s)",flush=True)
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--download',action='store_true');parser.add_argument('--force',action='store_true');parser.add_argument('--jobs',type=int,default=2);parser.add_argument('--only')
    args=parser.parse_args();study=load_study();official_archive(download=args.download)
    path=PUBLIC/'catalog.json';catalog=json.loads(path.read_text())
    preserved=[c for c in catalog['combinations'] if not c['processMode'].startswith('official_')]
    if len(preserved)!=148 or not all(valid_assets(c) for c in preserved): raise SystemExit('Expected148 intact native looks')
    old_films=[f for f in catalog['films'] if f['type']!='official']
    existing={c['id']:c for c in catalog['combinations'] if c['processMode'].startswith('official_')}
    jobs=[(study,l,catalog['papers'],catalog['samples'],args.force) for l in study['looks'] if not args.only or l['film']==args.only]
    if args.jobs==1: results=map(generate_film,jobs)
    else:
        executor=ProcessPoolExecutor(max_workers=args.jobs);results=executor.map(generate_film,jobs)
    for batch in results:
        for record in batch: existing[record['id']]=record
    if args.jobs!=1: executor.shutdown()
    catalog['films']=old_films+[{'id':l['film'],'name':'Fujifilm '+l['name'],'type':'official','stage':'official_lut','brand':'Fujifilm','use':'digital_simulation','recommendedPrint':None,'sha256':l['sourceSha256']} for l in study['looks']]
    catalog['combinations']=preserved+sorted(existing.values(),key=lambda c:c['number'])
    catalog['counts']={s:sum(c['status']==s for c in catalog['combinations']) for s in ['ready','failed','unsupported','not-generated']}
    catalog['fujiStudy']=study;catalog['generatedAt']=datetime.now(timezone.utc).isoformat()
    catalog.pop('stdVariant',None)
    catalog['stdGeneration']=GENERATION;catalog['stdMethod']=GENERATION;catalog['adapter']=CONFIG['adapter'];catalog['cameraAdapters']=camera_catalog()
    save_json(PUBLIC/'research/fujifilm-official.json',study);save_json(path,catalog)
    print(json.dumps(catalog['counts']),flush=True)

if __name__=='__main__':main()
