#!/usr/bin/env python3
"""Migrate all existing looks without regenerating their V-Log colour renderer."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import time
from pipeline.camera_std import (METHOD, BASELINE, prepare_sources, camera_catalog, rebuild_standard)
from pipeline.common import PUBLIC, ROOT, save_json, sha256


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, help='Pinned V-Log Alchemy checkout; omitted once public/camera-adapters is prepared')
    parser.add_argument('--jobs', type=int, default=3)
    parser.add_argument('--only', help='Regenerate one combination; use only for development after full migration')
    args = parser.parse_args()
    if args.source: prepare_sources(args.source)
    cameras = camera_catalog()
    path = PUBLIC / 'catalog.json'
    catalog = json.loads(path.read_text())
    BASELINE.mkdir(parents=True, exist_ok=True)
    if not (BASELINE / 'catalog.json').exists(): save_json(BASELINE / 'catalog.json', catalog)
    records = {c['id']: c for c in catalog['combinations']}
    original_hashes = {c['id']: c['files']['vlog']['sha256'] for c in catalog['combinations'] if c['status'] == 'ready'}
    jobs = [c for c in catalog['combinations'] if c['status'] == 'ready' and (not args.only or c['id'] == args.only)]
    if not jobs: raise SystemExit('No selected combinations')
    start = time.perf_counter()
    with ProcessPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = {pool.submit(rebuild_standard, c): c['id'] for c in jobs}
        for index, future in enumerate(as_completed(futures), 1):
            record = future.result(); records[record['id']] = record
            print(f'[{index}/{len(jobs)}] 10 cameras ready: {record["id"]}', flush=True)
    catalog['combinations'] = [records[c['id']] for c in catalog['combinations']]
    for record in catalog['combinations']:
        if record['status'] != 'ready': continue
        asset = record['files']['vlog']
        if sha256(PUBLIC / asset['path'].lstrip('/')) != original_hashes[record['id']]:
            raise ValueError(f'Original VLOG modified: {record["id"]}')
    if not args.only or all(c.get('stdMethod') == METHOD for c in catalog['combinations'] if c['status'] == 'ready'):
        catalog.pop('stdVariant', None)
        catalog.update(stdMethod=METHOD, stdGeneration=METHOD, adapter=METHOD, cameraAdapters=cameras,
                       generatedAt=datetime.now(timezone.utc).isoformat())
    save_json(path, catalog)
    report = {'method': METHOD, 'combinations': len(jobs), 'cameras': len(cameras['models']),
              'mergedCubes': len(jobs) * len(cameras['models']), 'vlogUnchanged': True,
              'seconds': round(time.perf_counter() - start, 2)}
    save_json(ROOT / 'artifacts/camera-std-migration-report.json', report)
    print(json.dumps(report), flush=True)


if __name__ == '__main__': main()
