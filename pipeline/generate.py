"""Generate actual spektrafilm LUTs, independent checks, previews and catalog.

Run from the project root: .venv/bin/python -m pipeline.generate --jobs 3
"""
from __future__ import annotations

from pipeline.common import CONFIG, ROOT, PUBLIC, UPSTREAM, PROFILES, profiles, sha256, save_json, std_to_vlog, read_cube, metrics
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import platform
import resource
import shutil
import subprocess
import time
import traceback
import zipfile

import numpy as np
from PIL import Image
from spektrafilm_lut_creator.bundles import BundleSpec
from spektrafilm_lut_creator.builders import BundleBuilder
from spektrafilm_lut_creator.formats import Lut
from spektrafilm_lut_creator.formats.lumix import LumixCubeFormat
from spektrafilm_lut_creator.grid import cube_grid
from spektrafilm_lut_creator.qa.evaluators import apply_tetrahedral, apply_trilinear
from spektrafilm_lut_creator.qa.reference import run_pipeline_at
from pipeline.samples import prepare, save_image
from pipeline.slide import INIT_PRINT_PROFILE, SlideBundleBuilder, run_slide_reference
from pipeline.digital import DigitalScanBundleBuilder, run_digital_reference, DIGITAL_METHOD_ID, DIGITAL_CONTRACT
from pipeline.camera_std import backup_record, rebuild_standard, camera_catalog, METHOD as STD_GENERATION


def combination_choices(stocks):
    films = [s for s in stocks if s['stage'] == 'filming']
    papers = [s for s in stocks if s['stage'] == 'printing']
    for i, film in enumerate(films):
        # Preserve existing negative filenames; use the first unused number
        # in each formerly unsupported slide block for its single direct scan.
        for j, paper in enumerate([None] if film['type'] == 'positive' else papers):
            yield film, paper, i * len(papers) + j + 1
    # Append negative digital scans without renumbering any existing download.
    for i, film in enumerate(f for f in films if f['type'] != 'positive'):
        yield film, None, len(films) * len(papers) + i + 1


def combination_id(film, paper):
    suffix = paper['id'] if paper else ('direct_scan' if film['type'] == 'positive' else 'digital_scan')
    return f"{film['id']}__{suffix}"


def process_mode(film, paper):
    return 'negative_print' if paper else ('positive_direct' if film['type'] == 'positive' else 'negative_digital')


def cache_key(film, paper):
    dependencies = {p.name: sha256(p) for p in sorted((ROOT / 'pipeline').glob('*.py'))}
    lock = ROOT / 'pipeline/requirements.lock'
    if lock.exists():
        dependencies['requirements.lock'] = sha256(lock)
    dependencies['sampleManifest'] = sha256(PUBLIC / 'samples/manifest.json')
    for sample in json.loads((PUBLIC / 'samples/manifest.json').read_text()):
        dependencies[f"sample:{sample['id']}"] = sha256(PUBLIC / sample['path'].lstrip('/'))
    payload = {"config": CONFIG, "film": film['sha256'], "paper": paper['sha256'] if paper else None,
               "processMode": process_mode(film, paper), "code": dependencies}
    if paper is None:
        payload['runtimeInitPrintProfileSha256'] = sha256(PROFILES / f'{INIT_PRINT_PROFILE}.json')
    return hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()


def describe(path):
    return {"path": '/' + path.relative_to(PUBLIC).as_posix(), "name": path.name,
            "bytes": path.stat().st_size, "sha256": sha256(path)}


def valid_cache(record, key):
    if record.get('status') != 'ready' or record.get('cacheKey') != key:
        return False
    return valid_assets(record)


def valid_assets(record):
    if record.get('status') != 'ready':
        return False
    for asset in [*record['files'].values(), *record['previews'].values()]:
        p = PUBLIC / asset['path'].lstrip('/')
        if not p.is_file() or sha256(p) != asset['sha256']:
            return False
    return True


def generate_one(job):
    film,paper,number,force=job
    combo_id=combination_id(film,paper)
    is_slide=film['type']=='positive'
    is_digital=paper is None and not is_slide
    directory=PUBLIC / 'luts' / combo_id
    record_path=directory / 'metadata.json'
    key=cache_key(film,paper)
    if record_path.exists():
        cached=json.loads(record_path.read_text())
        if not force and valid_cache(cached,key): return cached
        if cached.get('status') == 'ready' and cached.get('qa', {}).get('stdGeneration') != STD_GENERATION:
            backup_record(cached)
    started=time.perf_counter()
    directory.mkdir(parents=True,exist_ok=True)
    record={"id":combo_id,"film":film['id'],"paper":paper['id'] if paper else None,"number":number,"cacheKey":key,
            "processMode":process_mode(film,paper)}
    try:
        if is_slide and paper is not None: raise ValueError('Positive films require no paper')
        spec=BundleSpec(film_profile=film['id'],print_profiles=(INIT_PRINT_PROFILE if paper is None else paper['id'],),
                        input_color_space=CONFIG['input'],output_color_space=CONFIG['output'],
                        topology=CONFIG['topology'],resolution=CONFIG['resolution'],target=CONFIG['target'],
                        stops_above_midgray=CONFIG['stops_above_midgray'],output_gamut_compress=CONFIG['output_gamut_compress'])
        builder=(DigitalScanBundleBuilder if is_digital else SlideBundleBuilder if is_slide else BundleBuilder)(spec)
        bundle=builder.build()
        vlog=bundle.luts[0][1].table
        if not np.isfinite(vlog).all(): raise ValueError('Engine produced non-finite values')
        vlog_path=directory / f'{number:04d}VLOG.cube'
        LumixCubeFormat().write(Lut(vlog,title=f'{number:04d}_VLOG'),vlog_path,photo_style_tag='VLOG')
        vlog_disk=read_cube(vlog_path,'VLOG')
        roundtrip=float(np.max(np.abs(vlog_disk-vlog)))
        if roundtrip>0.000000501: raise ValueError('Cube serialization changed the table')
        gray=np.repeat(np.linspace(0,1,129)[:,None],3,axis=1)
        points=np.concatenate([np.random.default_rng(CONFIG['seed']).random((CONFIG['qa_random_samples'],3)),gray,cube_grid(5)])
        direct=run_digital_reference(spec,points) if is_digital else run_slide_reference(spec,points) if is_slide else run_pipeline_at(spec,bundle,0,points)
        if not np.isfinite(direct).all(): raise ValueError('Non-finite native engine reference')
        fidelity={name:metrics(fn(vlog_disk,points),direct) for name,fn in [('tetrahedral',apply_tetrahedral),('trilinear',apply_trilinear)]}
        qa={"fileChecks":"passed","rowsPerCube":35937,"serializationMaxError":roundtrip,
            "processMode":record['processMode'],"scanFilm":paper is None,
            "referenceModel":DIGITAL_METHOD_ID if is_digital else 'spektrafilm-runtime',
            "vlogVsDirectEngine":fidelity,"cameraVerified":False}
        save_json(directory/'qa.json',qa)
        provenance={"engine":{"repository":"https://github.com/andreavolpato/spektrafilm","commit":CONFIG['engine_commit'],"version":CONFIG['engine_version']},
                    "profiles":{"film":film,"paper":paper},"config":CONFIG,"bundle":asdict(bundle.meta),
                    "processMode":record['processMode'],"scanFilm":paper is None,
                    "processingPath":('film exposure -> film development -> Film Lab virtual RGB scan -> common negative-to-positive conversion' if is_digital else 'film exposure -> film development -> direct film scan' if is_slide else 'film exposure -> film development -> print exposure -> print development -> print scan'),
                    "digitalConversion":({"id":DIGITAL_METHOD_ID,"contract":DIGITAL_CONTRACT,"experimental":True,
                        "limitation":"Film Lab extension, not upstream author output or a measured physical scanner profile."} if is_digital else None),
                    "runtimeInitPrintProfile":({"id":INIT_PRINT_PROFILE,"sha256":sha256(PROFILES / f'{INIT_PRINT_PROFILE}.json'),
                        "note":"Required only to initialize upstream runtime; printing stages are bypassed and paper is not applied."} if paper is None else None),
                    "effects":{"grain":False,"halation":False,"blur":False,"autoExposure":False},
                    "sampleManifestSha256":sha256(PUBLIC/'samples/manifest.json'),
                    "environment":{"python":platform.python_version(),"platform":platform.platform()},
                    "license":"CC BY-SA 4.0; derived from spektrafilm by Andrea Volpato"}
        save_json(directory/'provenance.json',provenance)
        shutil.copyfile(UPSTREAM/'SPEKTRAFILM_LICENSE.txt',directory/'SPEKTRAFILM_LICENSE.txt')
        if not (directory/'CHANGELOG.txt').exists():
            (directory/'CHANGELOG.txt').write_text('Original colour renderer from the pinned spektrafilm engine. Digital conversion, when selected, is a documented Film Lab extension.\n')
        record.update(status='ready',files={"vlog":describe(vlog_path),"qa":describe(directory/'qa.json'),
                                           "provenance":describe(directory/'provenance.json')},qa=qa)
        # STD never evaluates the continuous engine: the newly serialized VLOG
        # file is the colour source for every camera-specific Standard export.
        record=rebuild_standard(record,json.loads((PUBLIC/'samples/manifest.json').read_text()),backup=False)
        record.update(seconds=round(time.perf_counter()-started,3),
                      peakRssBytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if platform.system()=='Darwin' else 1024))
    except Exception as exc:
        record.update(status='failed',reason=f'{type(exc).__name__}: {exc}')
        (directory/'error.log').write_text(traceback.format_exc())
    save_json(record_path,record)
    return record


def catalog(records, stocks, previous=None):
    combos=[]
    films=[s for s in stocks if s['stage']=='filming']
    papers=[s for s in stocks if s['stage']=='printing']
    for film,paper,number in combination_choices(stocks):
        cid=combination_id(film,paper)
        base={"id":cid,"film":film['id'],"paper":paper['id'] if paper else None,"number":number,
            "processMode":process_mode(film,paper)}
        combos.append(records.get(cid,{**base,"status":"not-generated","reason":"이 룩의 LUT는 아직 생성되지 않았습니다."}))
    result={"schemaVersion":2,"generatedAt":datetime.now(timezone.utc).isoformat(),"engineCommit":CONFIG['engine_commit'],
            "engineVersion":CONFIG['engine_version'],"adapter":CONFIG['adapter'],"stdGeneration":STD_GENERATION,"stdMethod":STD_GENERATION,"cameraAdapters":camera_catalog(),"output":"sRGB","resolution":33,
            "films":films,"papers":papers,"samples":json.loads((PUBLIC/'samples/manifest.json').read_text()),
            "combinations":combos,"counts":{s:sum(c['status']==s for c in combos) for s in ['ready','failed','unsupported','not-generated']}}
    if previous:
        model_ids={c['id'] for c in combos}
        result['combinations'] += [c for c in previous['combinations'] if c['id'] not in model_ids
                                   and c.get('processMode') not in ('official_direct', 'official_print')]
        # Supplied Fuji cubes are already S1II Standard outputs. They stay in
        # their separate inventory and must never enter the engine or adapter.
        for key in ['referenceStudy','suppliedFuji']:
            if key in previous: result[key]=previous[key]
        result['counts']={s:sum(c['status']==s for c in result['combinations']) for s in ['ready','failed','unsupported','not-generated']}
    save_json(PUBLIC/'catalog.json',result)
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--only',help='film_id__paper_id, film_id__direct_scan or film_id__digital_scan')
    parser.add_argument('--digital-only',action='store_true',help='Append/rebuild digital scans and preserve verified existing print/slide artifacts byte-for-byte')
    parser.add_argument('--jobs',type=int,default=3)
    parser.add_argument('--force',action='store_true')
    args=parser.parse_args()
    commit=subprocess.check_output(['git','-C',str(UPSTREAM),'rev-parse','HEAD'],text=True).strip()
    if commit!=CONFIG['engine_commit']:
        raise SystemExit('Upstream commit does not match config')
    if subprocess.check_output(['git','-C',str(UPSTREAM),'diff','--stat'],text=True).strip():
        raise SystemExit('Upstream has modifications; pin and document them before generation')
    # Reuse the exact source samples in append-only digital builds. Recreating
    # the chart would rewrite its ICC creation timestamp despite equal pixels.
    previous=json.loads((PUBLIC/'catalog.json').read_text()) if (PUBLIC/'catalog.json').exists() else None
    if not previous:
        prepare()
    else:
        for sample in previous['samples']:
            path=PUBLIC/sample['path'].lstrip('/')
            if not path.is_file() or (sample.get('preparedSha256') and sha256(path)!=sample['preparedSha256']):
                raise SystemExit('Existing source sample changed; review it before regenerating looks')
    stocks=profiles()
    records={}
    if args.digital_only:
        if previous is None: raise SystemExit('Digital-only requires an existing catalog')
        if previous['engineCommit']!=CONFIG['engine_commit'] or previous['adapter']!=CONFIG['adapter']:
            raise SystemExit('Digital-only requires the same engine and STD adapter')
        for old in previous['combinations']:
            if old['processMode']=='negative_digital':
                continue
            if not valid_assets(old):
                raise SystemExit(f"Existing artifact verification failed: {old['id']}")
            records[old['id']]=old
    jobs=[]
    for f,p,number in combination_choices(stocks):
        cid=combination_id(f,p)
        path=PUBLIC/'luts'/cid/'metadata.json'
        if path.exists():
            old=json.loads(path.read_text())
            if valid_assets(old):
                records[cid]=old
        eligible=not args.digital_only or (p is None and f['type']!='positive')
        if eligible and (not args.only or cid==args.only):
            jobs.append((f,p,number,args.force))
    if args.only and not jobs:
        raise SystemExit('Unknown or unsupported combination')
    catalog(records,stocks,previous)
    started=time.perf_counter()
    with ProcessPoolExecutor(max_workers=max(1,args.jobs)) as pool:
        for completed,future in enumerate(as_completed([pool.submit(generate_one,j) for j in jobs]),1):
            record=future.result()
            records[record['id']]=record
            catalog(records,stocks,previous)
            print(f"[{completed}/{len(jobs)}] {record['status']} {record['id']} ({record.get('seconds',0)}s)",flush=True)
    result=catalog(records,stocks,previous)
    save_json(ROOT/'artifacts/build-report.json',{"counts":result['counts'],"wallSeconds":round(time.perf_counter()-started,2)})
    print(json.dumps(result['counts']),flush=True)
    if any(r['status']=='failed' for r in records.values()):
        raise SystemExit(1)


if __name__=='__main__':
    main()
