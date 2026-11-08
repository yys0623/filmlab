"""Bake print filter timing packs for every negative print base look.

Run: .venv/bin/python -m pipeline.generate_print_timing --jobs 3
     .venv/bin/python -m pipeline.generate_print_timing --only fujifilm_c200__fujifilm_crystal_archive_typeii
An --only build writes the pack but does not publish the catalog.
"""
from __future__ import annotations

from pipeline.common import CONFIG, PUBLIC, ROOT, UPSTREAM, save_json, sha256, metrics
from pipeline.generate import describe
from pipeline.generate_film_cast import make_spec
from pipeline.print_timing import (METHOD, GRID_CC, RESOLUTION, QA_SHIFTS, build_tables, pack, unpack,
                                   evaluate, run_shift_reference)
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import argparse
import json
import subprocess
import time
import traceback

import numpy as np
from spektrafilm_lut_creator.qa.evaluators import apply_tetrahedral

DIRECTORY = PUBLIC / 'print-timing'
AUDIT = ROOT / 'artifacts/print-timing'


def candidates(catalog):
    return [c for c in catalog['combinations'] if c.get('processMode') == 'negative_print'
            and c.get('status') == 'ready' and not c.get('castBaseId')]


def generate_one(base):
    started = time.perf_counter()
    try:
        spec = make_spec(base)
        wire, a, b = build_tables(spec)
        rng = np.random.default_rng(CONFIG['seed'])
        points = np.concatenate([rng.random((2048, 3)), np.repeat(np.linspace(0, 1, 65)[:, None], 3, axis=1)])
        header = {'method': METHOD, 'id': base['id'], 'film': base['film'], 'paper': base['paper'],
                  'resolution': RESOLUTION, 'gridCC': list(GRID_CC), 'channels': ['M', 'Y'],
                  'wire': {'quantity': 'log10 paper exposure', **wire},
                  'layout': 'A[m][y] for gridCC x gridCC, then B; each table in .cube row order (red fastest), RGB',
                  'encoding': 'uint16 little-endian, value / 65535',
                  'interpolation': {'shift': 'biquadratic Lagrange', 'luts': 'tetrahedral', 'cameraAdapter': 'trilinear'},
                  'engine': {'commit': CONFIG['engine_commit'], 'version': CONFIG['engine_version']},
                  'input': CONFIG['input'], 'output': CONFIG['output'],
                  'baseVlogSha256': base['files']['vlog']['sha256']}
        data = pack(header, a, b)
        _, a_disk, b_disk = unpack(data)  # QA measures the shipped, quantized tables
        qa = {}
        for m, y in QA_SHIFTS:
            chain = evaluate(a_disk, b_disk, wire, points, m, y, apply_tetrahedral)
            qa[f'M{m:+g}Y{y:+g}'] = metrics(chain, run_shift_reference(spec, points, m, y))
        worst = max(v['p99'] for v in qa.values())
        if not np.isfinite(worst) or worst > 0.03: raise ValueError(f'Filter timing p99 error too large: {worst:.4f}')
        header['qa'] = {'vlogChainVsDirectEngine': qa, 'samples': {'randomRgb': 2048, 'neutralRamp': 65, 'seed': CONFIG['seed']}}
        DIRECTORY.mkdir(parents=True, exist_ok=True)
        path = DIRECTORY / f"{base['id']}.bin"
        path.write_bytes(pack(header, a, b))
        return {'id': base['id'], 'status': 'ready', 'asset': describe(path), 'wire': wire,
                'qa': {k: {s: v[s] for s in ('mean', 'p99', 'max')} for k, v in qa.items()},
                'seconds': round(time.perf_counter() - started, 2)}
    except Exception as exc:
        return {'id': base['id'], 'status': 'failed', 'reason': f'{type(exc).__name__}: {exc}', 'trace': traceback.format_exc()}


def publish(catalog, records):
    ready = {r['id']: {'asset': r['asset'], 'wire': r['wire'], 'qa': r['qa']} for r in records if r['status'] == 'ready'}
    for stale in DIRECTORY.glob('*.bin'):
        if stale.stem not in ready: stale.unlink()
    catalog['printTiming'] = {
        'method': METHOD, 'experimental': True, 'unit': 'Kodak CC', 'channels': ['M', 'Y'],
        'gridCC': list(GRID_CC), 'rangeCC': [GRID_CC[0], GRID_CC[2]], 'resolution': RESOLUTION,
        'interpolation': {'shift': 'biquadratic Lagrange', 'luts': 'tetrahedral', 'cameraAdapter': 'trilinear'},
        'limitations': [
            'Approximates the engine between baked filter positions; QA reports the error against direct engine runs.',
            'Shift is added to the database neutral filters, like the spektrafilm GUI Print Y/M filter shift.',
            'Grain, halation and other spatial effects are not included, as in every LUT.'],
        'packs': dict(sorted(ready.items()))}
    catalog['generatedAt'] = datetime.now(timezone.utc).isoformat()
    save_json(PUBLIC / 'catalog.json', catalog)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--jobs', type=int, default=3)
    parser.add_argument('--only')
    args = parser.parse_args()
    commit = subprocess.check_output(['git', '-C', str(UPSTREAM), 'rev-parse', 'HEAD'], text=True).strip()
    if commit != CONFIG['engine_commit']: raise SystemExit('Pinned engine commit differs')
    catalog = json.loads((PUBLIC / 'catalog.json').read_text())
    bases = candidates(catalog)
    if len(bases) != 128: raise SystemExit(f'Expected 128 negative print base looks, found {len(bases)}')
    if args.only:
        bases = [b for b in bases if b['id'] == args.only]
        if not bases: raise SystemExit('Unknown negative print combination')
    started = time.perf_counter(); records = []
    with ProcessPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        for done, future in enumerate(as_completed([pool.submit(generate_one, b) for b in bases]), 1):
            record = future.result(); records.append(record)
            print(f"[{done}/{len(bases)}] {record['status']} {record['id']} {record.get('reason', '')}", flush=True)
    failed = [r for r in records if r['status'] == 'failed']
    save_json(AUDIT / ('single-build-report.json' if args.only else 'build-report.json'),
              {'packs': len(records) - len(failed), 'failed': [{'id': r['id'], 'reason': r['reason']} for r in failed],
               'wallSeconds': round(time.perf_counter() - started, 2), 'catalogPublished': not args.only and not failed,
               'qa': {r['id']: r['qa'] for r in records if r['status'] == 'ready'}})
    if failed: raise SystemExit(f'Failed: {[r["id"] for r in failed]}')
    if not args.only: publish(catalog, records)


if __name__ == '__main__':
    main()
