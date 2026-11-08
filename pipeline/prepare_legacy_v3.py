"""Publish an immutable v3 ZIP sidecar without changing current A/B assets.

This copies only verified original baseline ZIP bytes. It does not regenerate
LUTs, rewrite archive contents, or modify public/catalog.json. The manifest
describes the old STD as an entry inside its original ZIP for runtime loading.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import zipfile

from pipeline.common import ROOT, PUBLIC

BASELINE = ROOT / 'artifacts/std-precurve-baseline'
METHOD = 'legacy-v3-baseline'
EXPECTED_COMBINATIONS = 238
QA_FIELDS = ('stdGeneration', 'jpgToneProtection', 'stdVsDirectEngine',
             'stdVsContinuousComposition', 'warnings')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode()


def safe_name(value):
    if not isinstance(value, str) or not value or Path(value).name != value or value in ('.', '..'):
        raise ValueError(f'Unsafe asset name: {value!r}')
    return value


def public_path(public_root, value):
    if not isinstance(value, str) or not value.startswith('/') or value.startswith('//'):
        raise ValueError(f'Expected root-relative public asset path: {value!r}')
    path = (public_root / value.lstrip('/')).resolve()
    if not path.is_relative_to(public_root.resolve()):
        raise ValueError(f'Asset escapes public directory: {value}')
    return path


def verify_bytes(raw, asset, label):
    if len(raw) != asset['bytes'] or digest(raw) != asset['sha256']:
        raise ValueError(f'Asset hash/size mismatch: {label}')


def read_public_asset(public_root, asset):
    """Support the development raw files and already ZIP-packed catalogs."""
    path = public_path(public_root, asset['path'])
    if asset.get('encoding') == 'zip-entry':
        transport = path.read_bytes()
        if asset.get('transferBytes') != len(transport) or asset.get('transferSha256') != digest(transport):
            raise ValueError(f'Packed transport hash/size mismatch: {path}')
        with zipfile.ZipFile(path) as archive:
            raw = archive.read(safe_name(asset['name']))
    else:
        raw = path.read_bytes()
    verify_bytes(raw, asset, str(path))
    return raw


def _protect_snapshot(public_root, catalog_path, active):
    paths = {catalog_path}
    for record in active:
        for asset in record['files'].values():
            paths.add(public_path(public_root, asset['path']))
    return {path: digest(path.read_bytes()) for path in paths}


def _verify_baseline_record(old, current, baseline_root, public_root):
    cid = safe_name(old['id'])
    directory = baseline_root / cid
    files = old['files']
    zip_name = safe_name(files['zip']['name'])
    zip_path = directory / zip_name
    archive_bytes = zip_path.read_bytes()
    verify_bytes(archive_bytes, files['zip'], f'{cid}/{zip_name}')
    baseline_marker = json.loads((directory / 'baseline-manifest.json').read_text())
    if baseline_marker['sha256'].get(zip_name) != digest(archive_bytes):
        raise ValueError(f'Original baseline manifest mismatch: {cid}/{zip_name}')
    expected_names = {safe_name(files[key]['name']) for key in ('std', 'vlog', 'qa', 'provenance')}
    expected_names.update(['README.txt', 'CHANGELOG.txt', 'SPEKTRAFILM_LICENSE.txt'])
    if old['processMode'].startswith('official_'): expected_names.add('FUJIFILM_NOTICE.txt')
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != expected_names:
            raise ValueError(f'Unexpected ZIP entry set/count: {cid}')
        if archive.testzip() is not None: raise ValueError(f'ZIP CRC check failed: {cid}')
        entries = {name: archive.read(name) for name in names}
    # Check documents and licence notices as well as both LUTs against the
    # immutable per-folder snapshot. Never edit these historical bytes.
    for name, raw in entries.items():
        if digest(raw) != baseline_marker['sha256'].get(name):
            raise ValueError(f'ZIP entry differs from immutable baseline: {cid}/{name}')
        if raw != (directory / name).read_bytes():
            raise ValueError(f'Baseline file differs from original ZIP entry: {cid}/{name}')
    for key in ('std', 'vlog', 'qa', 'provenance'):
        verify_bytes(entries[files[key]['name']], files[key], f'{cid}/{key} ZIP entry')
    old_qa = json.loads(entries[files['qa']['name']])
    if old_qa != old['qa']: raise ValueError(f'Baseline catalog QA differs from archive: {cid}')
    if '#LUMIXPHOTOSTYLE STD' not in entries[files['std']['name']].decode().splitlines()[:3]:
        raise ValueError(f'Baseline STD header is invalid: {cid}')
    current_vlog = read_public_asset(public_root, current['files']['vlog'])
    if current_vlog != entries[files['vlog']['name']]:
        raise ValueError(f'Current VLOG differs from historical source: {cid}')
    number = old['number']
    zip_public_path = f'/legacy-v3/{cid}/{zip_name}'
    result = {
        'id': cid,
        'files': {
            'stdLegacy': {
                'path': zip_public_path, 'name': files['std']['name'],
                'downloadName': f'{number:04d}STL.cube',
                'bytes': files['std']['bytes'], 'sha256': files['std']['sha256'],
                'encoding': 'zip-entry', 'transferBytes': files['zip']['bytes'],
                'transferSha256': files['zip']['sha256'],
            },
            'zipLegacy': {
                'path': zip_public_path, 'name': zip_name,
                'downloadName': f'{number:04d}V3.zip',
                'bytes': files['zip']['bytes'], 'sha256': files['zip']['sha256'],
            },
        },
        # Fuji's old QA lacks stdGeneration and stdVsContinuousComposition.
        # Null records that absence rather than inventing historical metadata.
        'qa': {key: deepcopy(old_qa.get(key)) for key in QA_FIELDS},
        'sourceVlogSha256': files['vlog']['sha256'],
    }
    return result, zip_path, len(entries)


def prepare_legacy_v3(*, public_root=PUBLIC, baseline_root=BASELINE,
                      expected_count=EXPECTED_COMBINATIONS, verify_only=False):
    public_root, baseline_root = Path(public_root).resolve(), Path(baseline_root).resolve()
    catalog_path = public_root / 'catalog.json'
    catalog_raw = catalog_path.read_bytes()
    catalog = json.loads(catalog_raw)
    baseline_raw = (baseline_root / 'catalog.json').read_bytes()
    baseline = json.loads(baseline_raw)
    active = [c for c in catalog['combinations'] if c['status'] == 'ready'
              and c['processMode'] != 'reference_interpretation' and not c['id'].endswith('__reference')]
    if len(active) != expected_count or len({c['id'] for c in active}) != len(active):
        raise ValueError(f'Expected {expected_count} unique active looks, found {len(active)}')
    old_records = {c['id']: c for c in baseline['combinations']}
    before = _protect_snapshot(public_root, catalog_path, active)
    records, sources, counts = [], {}, Counter()
    for current in sorted(active, key=lambda record: record['id']):
        cid = safe_name(current['id'])
        old = old_records.get(cid)
        if old is None or old['status'] != 'ready' or old['processMode'] != current['processMode']:
            raise ValueError(f'Missing or incompatible historical source: {cid}')
        record, path, count = _verify_baseline_record(old, current, baseline_root, public_root)
        records.append(record); sources[cid] = path; counts[count] += 1
    manifest = {'schemaVersion': 1, 'method': METHOD,
                'baselineCatalogSha256': digest(baseline_raw), 'combinations': records}
    manifest_raw = json_bytes(manifest)
    target = public_root / 'legacy-v3'
    if target.exists():
        if not target.is_dir(): raise ValueError(f'Legacy output is not a directory: {target}')
        expected_files = {'manifest.json'} | {f"{r['id']}/{r['files']['zipLegacy']['name']}" for r in records}
        actual_files = {p.relative_to(target).as_posix() for p in target.rglob('*') if p.is_file()}
        if actual_files != expected_files:
            raise ValueError('Existing legacy output file set differs; refusing to overwrite')
        if (target / 'manifest.json').read_bytes() != manifest_raw:
            raise ValueError('Existing legacy manifest differs; refusing to overwrite')
        for record in records:
            asset = record['files']['zipLegacy']
            verify_bytes(public_path(public_root, asset['path']).read_bytes(), asset, f"existing legacy {record['id']}")
    elif verify_only:
        raise ValueError('Legacy sidecar is missing; run preparation first')
    else:
        # Validate all 238 sources before publishing any copy. The sidecar
        # becomes visible as one directory, never as a half-written manifest.
        staging = Path(tempfile.mkdtemp(prefix='.legacy-v3-', dir=public_root))
        try:
            for record in records:
                asset = record['files']['zipLegacy']
                destination = staging / record['id'] / asset['name']
                destination.parent.mkdir(parents=True)
                shutil.copyfile(sources[record['id']], destination)
                verify_bytes(destination.read_bytes(), asset, f"copied legacy {record['id']}")
            (staging / 'manifest.json').write_bytes(manifest_raw)
            staging.rename(target)
        finally:
            if staging.exists(): shutil.rmtree(staging)
    for path, old_hash in before.items():
        if digest(path.read_bytes()) != old_hash:
            raise ValueError(f'Protected current artifact changed during preparation: {path}')
    if digest((baseline_root / 'catalog.json').read_bytes()) != digest(baseline_raw):
        raise ValueError('Baseline catalog changed during preparation')
    return {
        'method': METHOD, 'combinations': len(records), 'zipFiles': len(records),
        'zipEntryCounts': dict(sorted(counts.items())),
        'sourceVlogAllIdentical': True, 'protectedCurrentFilesUnchanged': len(before),
        'currentCatalogSha256': digest(catalog_raw), 'baselineCatalogSha256': digest(baseline_raw),
        'manifestSha256': digest(manifest_raw),
        'transferBytes': sum(record['files']['zipLegacy']['bytes'] for record in records),
        'verifyOnly': verify_only,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-root', type=Path, default=PUBLIC)
    parser.add_argument('--baseline-root', type=Path, default=BASELINE)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--report', type=Path, default=ROOT / 'artifacts/legacy-v3-prepare-report.json')
    args = parser.parse_args()
    report = prepare_legacy_v3(public_root=args.public_root, baseline_root=args.baseline_root,
                               verify_only=args.verify_only)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes(json_bytes(report))
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__': main()
