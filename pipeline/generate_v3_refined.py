"""Export a separate v3 refinement from the verified historical continuous model.

Only public/refined-v3 is written. Original v3, A/B, VLOG and catalog bytes stay
unchanged. Every look must reproduce all historical 33-grid STD nodes before
the final gamut operation may be changed. No VLOG LUT is used as a surrogate
for the continuous source renderer.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import lru_cache
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import zipfile

import numpy as np

from pipeline.common import CONFIG, PUBLIC, ROOT, metrics, read_cube, sha256
from pipeline.jpg import JpgToneProtection
from pipeline.prepare_legacy_v3 import (BASELINE, _protect_snapshot,
    _verify_baseline_record, digest, json_bytes, read_public_asset, safe_name)
from pipeline.std import run_std_native
from pipeline.slide import INIT_PRINT_PROFILE
from spektrafilm_lut_creator.bundles import BundleSpec
from spektrafilm_lut_creator.formats import Lut
from spektrafilm_lut_creator.formats.lumix import LumixCubeFormat
from spektrafilm_lut_creator.grid import cube_grid
from spektrafilm_lut_creator.qa.evaluators import apply_tetrahedral, apply_trilinear

METHOD = 'legacy-v3-soft-gamut-v1'
EXPECTED_COMBINATIONS = 238
GRID_TOLERANCE = 1e-6
SERIALIZATION_TOLERANCE = 5.01e-7
SOURCE_DESCRIPTION = (
    'Historical continuous v3 renderer with the same Standard input adapter, '
    'neutral calibration, lightness protection and chroma gain; only its final '
    'radial gamut boundary is replaced by the documented soft knee. '
    'The unchanged VLOG is included for continuity, not used to approximate '
    'the continuous Standard renderer. No image-dependent adaptation.'
)


@lru_cache(maxsize=8)
def _paper_bridge(paper_id):
    from pipeline.fuji_paper import PaperBridge
    return PaperBridge(paper_id)


def make_renderer(record, original_provenance):
    """Reconstruct the exact old model for each of the five active modes."""
    mode = record['processMode']
    if mode.startswith('official_'):
        from pipeline.fuji import apply_official_native
        paper = _paper_bridge(record['paper']) if mode == 'official_print' else None
        return lambda samples: apply_official_native(samples, record['film'], 'std', paper)
    if mode not in ('negative_print', 'positive_direct', 'negative_digital'):
        raise ValueError(f'Unsupported historical renderer: {mode}')
    historical = original_provenance['config']
    spec = BundleSpec(
        film_profile=record['film'], print_profiles=(record.get('paper') or INIT_PRINT_PROFILE,),
        input_color_space=historical['input'], output_color_space=historical['output'],
        topology=historical['topology'], resolution=33, target=historical['target'],
        stops_above_midgray=historical['stops_above_midgray'],
        output_gamut_compress=historical['output_gamut_compress'],
    )
    stock_reference = SimpleNamespace(meta=SimpleNamespace(stocks=None))
    return lambda samples: run_std_native(spec, stock_reference, samples,
        is_slide=mode == 'positive_direct', is_digital=mode == 'negative_digital')


class CachedRenderer:
    """Reuse expensive neutral/grid responses between old and refined methods."""
    def __init__(self, render):
        self.render, self.cache, self.evaluations = render, {}, 0

    def __call__(self, values):
        values = np.ascontiguousarray(values, dtype=np.float64)
        key = (values.shape, digest(values.tobytes()))
        if key not in self.cache:
            output = np.asarray(self.render(values), dtype=float)
            if output.shape != values.shape or not np.isfinite(output).all():
                raise ValueError('Invalid historical model response')
            output.setflags(write=False)
            self.cache[key] = output
            self.evaluations += 1
        return self.cache[key]


def generation_key(record, *, knee):
    dependencies = ['generate_v3_refined.py', 'jpg_refined.py', 'jpg.py', 'std.py',
                    'common.py', 'research.py', 'slide.py', 'digital.py', 'fuji.py', 'fuji_paper.py']
    return digest(json_bytes({
        'method': METHOD, 'knee': knee,
        'sourceLegacySha256': record['files']['std']['sha256'],
        'sourceZipSha256': record['files']['zip']['sha256'],
        'sourceVlogSha256': record['files']['vlog']['sha256'],
        'code': {name: sha256(ROOT / 'pipeline' / name) for name in dependencies},
        'engineCommit': CONFIG['engine_commit'],
    }))


def deterministic_zip(entries):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, raw in entries.items():
            info = zipfile.ZipInfo(safe_name(name), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, raw, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return stream.getvalue()


def _readme(record, metadata):
    number = record['number']
    official = record['processMode'].startswith('official_')
    origin = ('Derived from official FUJIFILM source data using Film Lab adaptation; '
              'not an unmodified official FUJIFILM product. Original FUJIFILM rights '
              'remain; see FUJIFILM_NOTICE.txt.\n' if official else
              'Derived from spektrafilm by Andrea Volpato, CC BY-SA 4.0.\n')
    return f'''Film Lab / v3 refined / {record['film']} / {record.get('paper') or record['processMode']}

{number:04d}STR.cube: refined Standard/sRGB LUT; #LUMIXPHOTOSTYLE STD.
{number:04d}VLOG.cube: unchanged historical V-Log / V-Gamut -> sRGB LUT.
33 x 33 x 33, full range 0..1, output sRGB, NOT Rec.709.

The Standard LUT retains the v3 input adaptation, neutral response, lightness
protection and chroma gain. Only the final gamut boundary uses a smooth knee
(knee={metadata.get('knee', 'see qa.json')}) to reduce abrupt saturation at the boundary.
It does not change exposure or use image statistics. Already clipped source
detail cannot be restored. No measured camera inverse or physical film/print
matching is claimed. Historical v3 and single-tone A/B remain separate options.

Before export, all 35,937 reconstructed historical STD nodes were checked
against the immutable original v3 file with a maximum error below 0.000001.
qa.json compares this actual exported refined LUT against its own continuous
refined composition. This is numerical interpolation accuracy, not physical
film accuracy. provenance.json records source hashes and method settings.

{origin}spektrafilm: Andrea Volpato, https://github.com/andreavolpato/spektrafilm
Original SPEKTRAFILM_LICENSE.txt and any FUJIFILM_NOTICE.txt are retained.
'''


def build_one(old, current, *, public_root=PUBLIC, baseline_root=BASELINE, knee=.9):
    """Validate original bytes and nodes, then atomically write one new ZIP."""
    from pipeline.jpg_refined import RefinedJpgToneProtection
    public_root, baseline_root = Path(public_root), Path(baseline_root)
    cid = safe_name(old['id'])
    _, original_zip, _ = _verify_baseline_record(old, current, baseline_root, public_root)
    with zipfile.ZipFile(original_zip) as archive:
        original_entries = {name: archive.read(name) for name in archive.namelist()}
    old_provenance = json.loads(original_entries[old['files']['provenance']['name']])
    raw = CachedRenderer(make_renderer(old, old_provenance))
    digital = old['processMode'] == 'negative_digital'
    legacy = JpgToneProtection(raw, digital=digital)
    grid = cube_grid(33)
    raw_grid = raw(grid)
    reconstructed = legacy.apply(grid, rendered=raw_grid)
    baseline_table = read_cube(baseline_root / cid / old['files']['std']['name'], 'STD')
    node_error = float(np.max(np.abs(reconstructed.reshape(33, 33, 33, 3) - baseline_table)))
    if node_error >= GRID_TOLERANCE:
        raise ValueError(f'Historical 33-grid reconstruction differs: {cid}: {node_error}')
    refined = RefinedJpgToneProtection(raw, digital=digital, knee=knee)
    if not np.array_equal(legacy.axis, refined.axis) or not np.array_equal(legacy.neutral_lab, refined.neutral_lab):
        raise ValueError('Refinement changed historical neutral calibration')
    table = refined.apply(grid, rendered=raw_grid).reshape(33, 33, 33, 3)
    if not np.isfinite(table).all() or table.min() < 0 or table.max() > 1:
        raise ValueError('Invalid refined table')
    number = old['number']
    std_name, zip_name = f'{number:04d}STR.cube', f'{number:04d}V3R.zip'
    with tempfile.TemporaryDirectory(prefix='film-lab-refined-') as temporary:
        std_path = Path(temporary) / std_name
        LumixCubeFormat().write(Lut(table, title=f'{number:04d}_STR'), std_path, photo_style_tag='STD')
        exported = read_cube(std_path, 'STD')
        std_bytes = std_path.read_bytes()
    serialization_error = float(np.max(np.abs(table - exported)))
    if serialization_error > SERIALIZATION_TOLERANCE:
        raise ValueError('Refined cube serialization exceeded writer precision')
    gray = np.repeat(np.linspace(0, 1, 129)[:, None], 3, axis=1)
    points = np.concatenate([np.random.default_rng(CONFIG['seed']).random((4096, 3)), gray, cube_grid(5)])
    exact = refined.apply(points)
    fidelity = {name: metrics(fn(exported, points), exact)
                for name, fn in [('tetrahedral', apply_tetrahedral), ('trilinear', apply_trilinear)]}
    warnings = []
    if fidelity['tetrahedral']['p99'] > .02:
        warnings.append('STD 상위 1% 보간 오차가 0.02를 넘습니다. 색 경계를 검토하세요.')
    settings = refined.metadata()
    qa = {
        'method': METHOD, 'knee': knee, 'fileChecks': 'passed', 'rowsPerCube': 33**3,
        'stdVsDirectEngine': fidelity, 'warnings': warnings,
        'metricReference': 'Exported refined 33-grid LUT versus the continuous refined v3 composition; not camera or physical film accuracy.',
        'sampling': '4096 uniform random RGB + 129 gray + 125 RGB grid; fixed seed 20261102',
        'historicalReproduction': {'nodes': 33**3, 'maxError': node_error,
            'strictTolerance': GRID_TOLERANCE, 'sourceLegacySha256': old['files']['std']['sha256']},
        'serializationMaxError': serialization_error,
        'jpgToneProtection': settings, 'vlogUnchanged': True,
        'sourceVlogSha256': old['files']['vlog']['sha256'],
        'generationKey': generation_key(old, knee=knee),
        'cameraVerified': False, 'physicalFilmOrPrintMatch': False,
    }
    provenance = {
        'methodId': METHOD, 'knee': knee, 'film': old['film'], 'paper': old.get('paper'),
        'processMode': old['processMode'], 'sourceDescription': SOURCE_DESCRIPTION,
        'sourceLegacySha256': old['files']['std']['sha256'],
        'sourceVlogSha256': old['files']['vlog']['sha256'],
        'sourceLegacyBundleSha256': old['files']['zip']['sha256'],
        'sourceHistoricalProvenance': old_provenance,
        'jpgToneProtection': settings, 'cameraInverseCalibrated': False,
        'physicalFilmOrPrintMatch': False, 'officialUnmodifiedProduct': False,
        'perImageAdaptation': False, 'generationKey': qa['generationKey'],
    }
    entries = {
        std_name: std_bytes,
        old['files']['vlog']['name']: original_entries[old['files']['vlog']['name']],
        'README.txt': _readme(old, {**settings, 'knee': knee}).encode(),
        'CHANGELOG.txt': ('v3 refined: preserve v3 tone/neutral/gain; smooth only the final gamut boundary.\n\n'.encode()
                          + original_entries['CHANGELOG.txt']),
        'qa.json': json_bytes(qa), 'provenance.json': json_bytes(provenance),
        'SPEKTRAFILM_LICENSE.txt': original_entries['SPEKTRAFILM_LICENSE.txt'],
    }
    if 'FUJIFILM_NOTICE.txt' in original_entries:
        entries['FUJIFILM_NOTICE.txt'] = original_entries['FUJIFILM_NOTICE.txt']
    zip_bytes = deterministic_zip(entries)
    path = f'/refined-v3/{cid}/{zip_name}'
    record = {
        'id': cid, 'sourceVlogSha256': old['files']['vlog']['sha256'],
        'sourceLegacySha256': old['files']['std']['sha256'],
        'files': {
            'stdRefined': {'path': path, 'name': std_name, 'downloadName': std_name,
                'bytes': len(std_bytes), 'sha256': digest(std_bytes), 'encoding': 'zip-entry',
                'transferBytes': len(zip_bytes), 'transferSha256': digest(zip_bytes)},
            'zipRefined': {'path': path, 'name': zip_name, 'downloadName': zip_name,
                'bytes': len(zip_bytes), 'sha256': digest(zip_bytes)},
        }, 'qa': qa,
    }
    target = public_root / path.lstrip('/')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix='.refined-', dir=target.parent, delete=False) as temporary:
        temporary.write(zip_bytes)
        temporary_path = Path(temporary.name)
    try:
        temporary_path.replace(target)
    finally:
        temporary_path.unlink(missing_ok=True)
    return record


def _build_job(job):
    old, current, public_root, baseline_root, knee = job
    return build_one(old, current, public_root=public_root, baseline_root=baseline_root, knee=knee)


def generate(*, public_root=PUBLIC, baseline_root=BASELINE, knee=.9, only=None, jobs=3):
    public_root, baseline_root = Path(public_root).resolve(), Path(baseline_root).resolve()
    catalog_path = public_root / 'catalog.json'
    catalog_bytes = catalog_path.read_bytes()
    baseline_bytes = (baseline_root / 'catalog.json').read_bytes()
    catalog, baseline = json.loads(catalog_bytes), json.loads(baseline_bytes)
    active = [r for r in catalog['combinations'] if r['status'] == 'ready'
              and r['processMode'] != 'reference_interpretation' and not r['id'].endswith('__reference')]
    if len(active) != EXPECTED_COMBINATIONS:
        raise ValueError(f'Expected {EXPECTED_COMBINATIONS} active combinations')
    before = _protect_snapshot(public_root, catalog_path, active)
    # Protect the completed immutable-v3 sidecar as well as source A/B files.
    legacy_root = public_root / 'legacy-v3'
    before.update({p: sha256(p) for p in legacy_root.rglob('*') if p.is_file()})
    old_records = {r['id']: r for r in baseline['combinations']}
    selected = [r for r in active if only is None or r['id'] in only]
    if not selected or (only is not None and {r['id'] for r in selected} != set(only)):
        raise ValueError('Unknown or empty selection')
    manifest_path = public_root / 'refined-v3/manifest.json'
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    reusable = previous.get('method') == METHOD and previous.get('knee') == knee and previous.get('baselineCatalogSha256') == digest(baseline_bytes)
    records = {r['id']: r for r in previous.get('combinations', [])} if reusable else {}
    pending = []
    for current in selected:
        old = old_records[current['id']]
        cached = records.get(current['id'])
        if cached and cached['qa'].get('generationKey') == generation_key(old, knee=knee):
            # Reusing an output still requires unchanged historical/source bytes.
            _verify_baseline_record(old, current, baseline_root, public_root)
            read_public_asset(public_root, cached['files']['stdRefined'])
        else:
            pending.append((old, current, public_root, baseline_root, knee))
    if jobs == 1:
        completed = map(_build_job, pending)
        for result in completed:
            records[result['id']] = result
            print(f"ready {result['id']} / node error {result['qa']['historicalReproduction']['maxError']:.3g}", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=max(1, jobs)) as pool:
            futures = [pool.submit(_build_job, job) for job in pending]
            for future in as_completed(futures):
                result = future.result(); records[result['id']] = result
                print(f"ready {result['id']} / node error {result['qa']['historicalReproduction']['maxError']:.3g}", flush=True)
    for path, original_hash in before.items():
        if sha256(path) != original_hash:
            raise ValueError(f'Protected source artifact changed: {path.name}')
    if sha256(baseline_root / 'catalog.json') != digest(baseline_bytes):
        raise ValueError('Immutable baseline catalog changed')
    manifest = {'schemaVersion': 1, 'method': METHOD, 'knee': knee,
                'baselineCatalogSha256': digest(baseline_bytes),
                'combinations': sorted(records.values(), key=lambda r: r['id'])}
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = manifest_path.with_suffix('.tmp')
    temporary.write_bytes(json_bytes(manifest)); temporary.replace(manifest_path)
    return {'method': METHOD, 'knee': knee, 'combinations': len(records),
            'generated': len(pending), 'protectedFilesUnchanged': len(before),
            'sourceVlogAllIdentical': True, 'currentCatalogSha256': digest(catalog_bytes),
            'baselineCatalogSha256': digest(baseline_bytes), 'manifestSha256': sha256(manifest_path),
            'reconstructionNodeMaxError': max(r['qa']['historicalReproduction']['maxError'] for r in records.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--knee', type=float, default=.9)
    parser.add_argument('--only', action='append', help='Exact id; repeated pilot selection. Full output requires all 238.')
    parser.add_argument('--jobs', type=int, default=3)
    args = parser.parse_args()
    report = generate(knee=args.knee, only=args.only, jobs=args.jobs)
    output = ROOT / 'artifacts/v3-refined-generation-report.json'
    output.parent.mkdir(parents=True, exist_ok=True); output.write_bytes(json_bytes(report))
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__': main()
