"""Append experimental "film cast" print LUTs, preserving every base asset.

Each negative print gets one variant whose enlarger filters are a
blend between the film's own neutral filters and a fixed reference pack (see
pipeline.print_blend). Base looks, their VLOG/STD files and numbers are not
touched; variants live in their own directories with number = base + 1000.

Run: .venv/bin/python -m pipeline.generate_film_cast --jobs 3
     .venv/bin/python -m pipeline.generate_film_cast --only kodak_gold_200__fujifilm_crystal_archive_typeii
An --only build prepares one look without publishing the catalog.
"""
from __future__ import annotations

from pipeline.common import CONFIG, PUBLIC, ROOT, UPSTREAM, read_cube, save_json, sha256, metrics, vlog_encode
from pipeline.camera_std import rebuild_standard
from pipeline.generate import describe
from pipeline.print_blend import (FilmCastBundleBuilder, run_blend_reference, blend_settings, solve_amount,
                                  solve_hue_shift, target_chroma, target_hue, TARGET_HUE, AMOUNT_POLICY, TARGET_CHROMA, TARGET_CHROMA_DEFAULT, MIN_AMOUNT,
                                  METHOD, SUFFIX, NUMBER_OFFSET, REFERENCE_FILM, LIMITATIONS)
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
import argparse
import json
import platform
import shutil
import subprocess
import time
import traceback

import numpy as np
from spektrafilm_lut_creator.bundles import BundleSpec
from spektrafilm_lut_creator.formats import Lut
from spektrafilm_lut_creator.formats.lumix import LumixCubeFormat
from spektrafilm_lut_creator.grid import cube_grid
from spektrafilm_lut_creator.qa.evaluators import apply_tetrahedral, apply_trilinear

AUDIT = ROOT / 'artifacts/film-cast'
GRAY_LINEAR = [0.184, 0.184, 0.184]


def make_spec(base):
    return BundleSpec(film_profile=base['film'], print_profiles=(base['paper'],),
                      input_color_space=CONFIG['input'], output_color_space=CONFIG['output'],
                      topology=CONFIG['topology'], resolution=CONFIG['resolution'], target=CONFIG['target'],
                      stops_above_midgray=CONFIG['stops_above_midgray'],
                      output_gamut_compress=CONFIG['output_gamut_compress'])


def candidates(catalog):
    return [c for c in catalog['combinations'] if c.get('processMode') == 'negative_print'
            and c.get('status') == 'ready' and SUFFIX not in c['id']]


def plan(base):
    """Solve every negative print's recipe for the chroma target; no pair is excluded.

    Returns (amount, chroma, hue, shift). Films with an editorial hue keep their
    own filters (amount 1) plus a solved M/Y shift; all others blend towards
    the reference pack with no shift.
    """
    spec = make_spec(base)
    if target_hue(base['film']) is not None:
        shift, chroma, hue = solve_hue_shift(spec)
        return 1., chroma, hue, shift
    amount, chroma, hue = solve_amount(spec)
    return amount, chroma, hue, (0., 0.)


def generate_one(base):
    started = time.perf_counter()
    variant_id = base['id'] + SUFFIX
    number = base['number'] + NUMBER_OFFSET
    directory = PUBLIC / 'luts' / variant_id
    record = {'id': variant_id, 'film': base['film'], 'paper': base['paper'], 'number': number,
              'processMode': 'negative_print', 'castBaseId': base['id']}
    try:
        amount, chroma, hue, shift = plan(base)
        if directory.exists(): shutil.rmtree(directory)
        directory.mkdir(parents=True)
        spec = make_spec(base)
        settings = blend_settings(base['film'], base['paper'], amount, shift)
        bundle = FilmCastBundleBuilder(spec, amount, shift).build()
        vlog = bundle.luts[0][1].table
        if not np.isfinite(vlog).all(): raise ValueError('Engine produced non-finite values')
        vlog_path = directory / f'{number:04d}VLOG.cube'
        LumixCubeFormat().write(Lut(vlog, title=f'{number:04d}_VLOG'), vlog_path, photo_style_tag='VLOG')
        vlog_disk = read_cube(vlog_path, 'VLOG')
        roundtrip = float(np.max(np.abs(vlog_disk - vlog)))
        if roundtrip > 0.000000501: raise ValueError('Cube serialization changed the table')
        gray = np.repeat(np.linspace(0, 1, 129)[:, None], 3, axis=1)
        points = np.concatenate([np.random.default_rng(CONFIG['seed']).random((CONFIG['qa_random_samples'], 3)),
                                 gray, cube_grid(5)])
        direct = run_blend_reference(spec, points, amount, shift)
        if not np.isfinite(direct).all(): raise ValueError('Non-finite independent reference output')
        fidelity = {name: metrics(fn(vlog_disk, points), direct)
                    for name, fn in [('tetrahedral', apply_tetrahedral), ('trilinear', apply_trilinear)]}
        mid = vlog_encode(np.array([GRAY_LINEAR]))
        base_gray = run_blend_reference(spec, mid, 1.)[0] * 255
        cast_gray = run_blend_reference(spec, mid, amount, shift)[0] * 255
        film_cast = {**settings, 'amountPolicy': AMOUNT_POLICY, 'targetChroma': target_chroma(base['film']),
                     'grayChroma': chroma, 'grayHue': hue,
                     'calibrationGray': {'input': 'linear V-Gamut RGB = [0.184, 0.184, 0.184], V-Log encoded',
                                         'outputSpace': 'sRGB, 8-bit scale (unrounded)',
                                         'base': base_gray.tolist(), 'filmCast': cast_gray.tolist()}}
        qa = {'fileChecks': 'passed', 'rowsPerCube': 35937, 'serializationMaxError': roundtrip,
              'processMode': 'negative_print', 'scanFilm': False, 'referenceModel': METHOD,
              'vlogVsDirectEngine': fidelity, 'cameraVerified': False, 'filmCast': film_cast}
        save_json(directory / 'qa.json', qa)
        provenance = {'engine': {'repository': 'https://github.com/andreavolpato/spektrafilm',
                                 'commit': CONFIG['engine_commit'], 'version': CONFIG['engine_version']},
                      'profiles': {'film': base['film'], 'paper': base['paper']}, 'config': CONFIG,
                      'bundle': asdict(bundle.meta), 'processMode': 'negative_print', 'scanFilm': False,
                      'processingPath': ('film exposure -> film development -> print exposure through the film\'s neutral filters '
                                         'plus an editorial M/Y shift -> print development -> print scan'
                                         if shift != (0., 0.) else
                                         'film exposure -> film development -> print exposure through a blended '
                                         'fixed-pack filter -> print development -> print scan'),
                      'sourceRenderingMethod': METHOD, 'filmCast': film_cast,
                      'castBase': {'id': base['id'], 'vlogSha256': base['files']['vlog']['sha256'], 'preserved': True},
                      'effects': {'grain': False, 'halation': False, 'blur': False, 'autoExposure': False},
                      'environment': {'python': platform.python_version(), 'platform': platform.platform()},
                      'limitations': LIMITATIONS,
                      'license': 'CC BY-SA 4.0; derived from spektrafilm by Andrea Volpato'}
        save_json(directory / 'provenance.json', provenance)
        shutil.copyfile(UPSTREAM / 'SPEKTRAFILM_LICENSE.txt', directory / 'SPEKTRAFILM_LICENSE.txt')
        (directory / 'CHANGELOG.txt').write_text(
            ('Film Lab experimental film-cast variant: the film\'s own print filters plus an M/Y shift solved for '
             f'an editorial cast hue of {target_hue(base["film"]):g} degrees (CIELAB). '
             if shift != (0., 0.) else
             'Film Lab experimental film-cast variant: print filters blended towards a fixed reference pack. ')
            + 'The base look is unchanged.\n')
        record.update(status='ready', filmCast=film_cast, qa=qa,
                      files={'vlog': describe(vlog_path), 'qa': describe(directory / 'qa.json'),
                             'provenance': describe(directory / 'provenance.json')})
        record = rebuild_standard(record, backup=False)
        record['seconds'] = round(time.perf_counter() - started, 3)
    except Exception as exc:
        record.update(status='failed', reason=f'{type(exc).__name__}: {exc}')
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'error.log').write_text(traceback.format_exc())
    if record['status'] == 'ready':
        save_json(directory / 'metadata.json', record)
    return record


def publish(catalog, records):
    base = [c for c in catalog['combinations'] if SUFFIX not in c['id']]
    variants = sorted((r for r in records if r['status'] == 'ready'), key=lambda r: r['number'])
    for stale in PUBLIC.glob(f'luts/*{SUFFIX}'):
        if stale.name not in {r['id'] for r in variants}: shutil.rmtree(stale)
    catalog['combinations'] = base + variants
    catalog['counts'] = {s: sum(c['status'] == s for c in catalog['combinations'])
                         for s in ['ready', 'failed', 'unsupported', 'not-generated']}
    catalog['filmCast'] = {'method': METHOD, 'referenceFilm': REFERENCE_FILM, 'suffix': SUFFIX,
                           'numberOffset': NUMBER_OFFSET, 'experimental': True,
                           'amountPolicy': AMOUNT_POLICY, 'minAmount': MIN_AMOUNT,
                           'targetChroma': {'default': TARGET_CHROMA_DEFAULT, **TARGET_CHROMA},
                           'targetHue': dict(TARGET_HUE),
                           'variants': len(variants), 'limitations': LIMITATIONS,
                           'skipped': sorted(({'id': r['castBaseId'], 'reason': r['reason']}
                                              for r in records if r['status'] == 'skipped'), key=lambda v: v['id'])}
    catalog['generatedAt'] = datetime.now(timezone.utc).isoformat()
    save_json(PUBLIC / 'catalog.json', catalog)
    return catalog


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--jobs', type=int, default=3)
    parser.add_argument('--only', help='Base combination ID; prepare one variant without catalog publication')
    args = parser.parse_args()
    commit = subprocess.check_output(['git', '-C', str(UPSTREAM), 'rev-parse', 'HEAD'], text=True).strip()
    if commit != CONFIG['engine_commit']: raise SystemExit('Pinned engine commit differs')
    if subprocess.check_output(['git', '-C', str(UPSTREAM), 'diff', '--stat'], text=True).strip():
        raise SystemExit('Vendor checkout must be unchanged')
    catalog = json.loads((PUBLIC / 'catalog.json').read_text())
    bases = candidates(catalog)
    if len(bases) != 128: raise SystemExit(f'Expected 128 negative print base looks, found {len(bases)}')
    for base in bases:
        path = PUBLIC / base['files']['vlog']['path'].lstrip('/')
        if sha256(path) != base['files']['vlog']['sha256']: raise SystemExit(f'Changed base VLOG: {base["id"]}')
    if args.only:
        bases = [b for b in bases if b['id'] == args.only]
        if not bases: raise SystemExit('Unknown negative print combination')
    started = time.perf_counter()
    records = []
    with ProcessPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = [pool.submit(generate_one, b) for b in bases]
        for done, future in enumerate(as_completed(futures), 1):
            record = future.result(); records.append(record)
            print(f"[{done}/{len(bases)}] {record['status']} {record['id']} {record.get('reason', '')}", flush=True)
    report = {'variants': sum(r['status'] == 'ready' for r in records),
              'skipped': sum(r['status'] == 'skipped' for r in records),
              'failed': [r['id'] for r in records if r['status'] == 'failed'],
              'wallSeconds': round(time.perf_counter() - started, 2), 'catalogPublished': not args.only,
              'looks': {r['id']: {k: r.get(k) for k in ['status', 'reason']} |
                        ({'amount': r['filmCast']['amount'], 'grayChroma': r['filmCast']['grayChroma'],
                          'grayHue': r['filmCast']['grayHue'],
                          'vlogVsDirectEngine': r['qa']['vlogVsDirectEngine']['tetrahedral']['max']}
                         if r['status'] == 'ready' else {'amount': r.get('amount'), 'grayHue': r.get('grayHue')})
                        for r in sorted(records, key=lambda r: r['number'])}}
    save_json(AUDIT / ('single-build-report.json' if args.only else 'build-report.json'), report)
    if report['failed']: raise SystemExit(f"Failed: {report['failed']}")
    if not args.only: publish(catalog, records)
    print(json.dumps({k: report[k] for k in ['variants', 'skipped', 'wallSeconds']}), flush=True)


if __name__ == '__main__':
    main()
