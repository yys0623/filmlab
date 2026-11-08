"""Historical A/B audit exporter. Production uses pipeline.camera_std.

Reproduce old single-tone STD A/B without rebuilding VLOG.

This retired rebuild_standard function is used only by historical audits. Run --backup-only before an audit, then --jobs 3 to regenerate.
All historical artifacts are copied once before any public file is changed.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile
import time
import zipfile

import numpy as np
from PIL import Image

from pipeline.common import CONFIG, PUBLIC, ROOT, read_cube, save_json, sha256, metrics
from pipeline.precurve import METHOD_ID, GENERATION
from pipeline.samples import save_image
from pipeline.std import STD_CONTRACT, bake_std, precurve_from_exported_vlog
from spektrafilm_lut_creator.formats import Lut
from spektrafilm_lut_creator.formats.lumix import LumixCubeFormat
from spektrafilm_lut_creator.grid import cube_grid
from spektrafilm_lut_creator.qa.evaluators import apply_tetrahedral, apply_trilinear

BASELINE = ROOT / 'artifacts/std-precurve-baseline'
VARIANTS = {
    'A': {'fileKey': 'std', 'suffix': 'STD',
          'description': 'Single input tone; linear-light target spans reachable native black and white.'},
    'B': {'fileKey': 'stdB', 'suffix': 'STB',
          'description': 'Single input tone; identity through 18% linear gray, smooth highlight roll-off. Shadows below native black saturate.'},
}
REFERENCE_DESCRIPTION = (
    'Exact single-tone precurve followed by the serialized exported VLOG cube '
    'with tetrahedral interpolation; not a continuous engine evaluation. '
    'stdVsDirectEngine is a retained compatibility key for this reference. '
    'This measures STD regridding error, not camera or physical film accuracy.'
)


def describe(path, *, destination=None):
    destination = destination or path
    return {'path': '/' + destination.relative_to(PUBLIC).as_posix(),
            'name': destination.name, 'bytes': path.stat().st_size, 'sha256': sha256(path)}


def backup_record(record, *, baseline=BASELINE):
    """Create an immutable complete snapshot; an existing snapshot is verified."""
    source = PUBLIC / 'luts' / record['id']
    destination = baseline / record['id']
    marker = destination / 'baseline-manifest.json'
    if destination.exists():
        if not marker.is_file():
            raise ValueError(f'Incomplete baseline; will not overwrite {destination}')
        saved = json.loads(marker.read_text())
        for name, digest in saved['sha256'].items():
            if sha256(destination / name) != digest:
                raise ValueError(f'Baseline hash mismatch: {destination / name}')
        return
    if record.get('qa', {}).get('stdGeneration') == GENERATION:
        raise ValueError(f'Cannot create an old-output baseline from new STD: {record["id"]}')
    baseline.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f'.{record["id"]}-', dir=baseline))
    try:
        for item in source.iterdir():
            if item.is_file() and item.name != 'baseline-manifest.json':
                shutil.copy2(item, temporary / item.name)
        hashes = {p.name: sha256(p) for p in sorted(temporary.iterdir()) if p.is_file()}
        for asset in [*record.get('files', {}).values(), *record.get('previews', {}).values()]:
            if hashes.get(asset['name']) != asset['sha256']:
                raise ValueError(f'Cannot snapshot changed artifact: {record["id"]}/{asset["name"]}')
        save_json(temporary / 'baseline-manifest.json', {
            'id': record['id'], 'createdAt': datetime.now(timezone.utc).isoformat(),
            'sourceGeneration': record.get('qa', {}).get('stdGeneration'),
            'sha256': hashes, 'overwriteAllowed': False,
        })
        temporary.rename(destination)
    finally:
        if temporary.exists(): shutil.rmtree(temporary)


def backup_catalog(catalog, *, baseline=BASELINE):
    baseline.mkdir(parents=True, exist_ok=True)
    target = baseline / 'catalog.json'
    if not target.exists():
        # Exclusive creation prevents replacing the audit source on a rerun.
        with target.open('x') as stream:
            json.dump(catalog, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write('\n')
    for record in catalog['combinations']:
        if record['status'] == 'ready' and record['processMode'] != 'reference_interpretation':
            backup_record(record, baseline=baseline)


def _bundle_readme(record, provenance):
    number = record['number']
    official = record['processMode'].startswith('official_')
    origin = ('FUJIFILM official source LUT with Film Lab adaptation. These files are NOT '
              'unmodified official LUTs. FUJIFILM data retains its original rights.\n'
              f"Official source: {provenance.get('source', {}).get('sourceUrl', '')}\n"
              if official else
              'Derived from spektrafilm by Andrea Volpato; CC BY-SA 4.0.\n')
    return f'''Film Lab / {record['film']} / {record.get('paper') or record['processMode']}

{number:04d}VLOG.cube: unchanged Panasonic V-Log / V-Gamut -> sRGB source renderer.
{number:04d}STD.cube: Standard/sRGB, variant A (native reachable black/white range).
{number:04d}STB.cube: Standard/sRGB, variant B (18% linear-gray anchor + highlight roll-off).
Both Standard files use #LUMIXPHOTOSTYLE STD; the STB suffix identifies variant B.
33 x 33 x 33; full range 0..1; output sRGB, NOT Rec.709.

STD v4: one identical scalar input curve is applied to each RGB channel,
then the existing exported VLOG cube is evaluated tetrahedrally. Renderer RGB
is returned unchanged: no output tone edit, neutral subtraction, chroma gain,
OKLab bounds or added output gamut mapping. Native colour casts remain.
A maps linear-light input to the renderer's reachable neutral black/white.
B is identity through 18% linear gray (about code 117.65/255), then rolls off
to reachable white. B cannot retain detail below the native black floor.
Black/white are R(0)/R(1) endpoints, not measured photographic paper Dmin/Dmax.
No image statistics, automatic exposure or camera-specific measured inverse.
Existing source clipping cannot be recovered. Camera paired validation has
NOT been performed; compare same-scene V-Log + VLOG with Standard + STD.

Preview images use the actual exported A/STD file once on Standard pixels.
B is a separate selectable download. The old stdVsDirectEngine QA field now
compares STD regridding with exact precurve + exported-VLOG composition, NOT
the continuous engine. VLOG native-engine QA retains its original meaning.
Settings, exact source SHA256 and limitations: provenance.json and qa.json.

{origin}spektrafilm: Andrea Volpato, https://github.com/andreavolpato/spektrafilm
SPEKTRAFILM_LICENSE.txt applies to upstream code/profiles; original third-party
rights are preserved. See FUJIFILM_NOTICE.txt when included.
'''


def rebuild_standard(record, samples, *, backup=True):
    """Export A/B from existing VLOG bytes, refresh A previews and exact bundles."""
    started = time.perf_counter()
    record = deepcopy(record)
    if record['processMode'] == 'reference_interpretation':
        raise ValueError('Reference interpretations are outside the STD precurve migration')
    directory = PUBLIC / 'luts' / record['id']
    if backup: backup_record(record)
    vlog_path = PUBLIC / record['files']['vlog']['path'].lstrip('/')
    source_hash = sha256(vlog_path)
    if source_hash != record['files']['vlog']['sha256']:
        raise ValueError(f'Changed VLOG source: {record["id"]}')
    precurve = precurve_from_exported_vlog(vlog_path)
    qa = deepcopy(record.get('qa') or json.loads((directory / 'qa.json').read_text()))
    provenance = json.loads((directory / 'provenance.json').read_text())
    # Remove claims belonging to v3. Unchanged VLOG/source provenance survives.
    for key in ['jpgToneProtection', 'stdVsContinuousComposition', 'stdVsContinuousCompositionPurpose', 'grayResponse']:
        qa.pop(key, None)
    provenance.pop('jpgToneProtection', None)
    provenance.setdefault('sourceRenderingMethod', provenance.get('methodId', qa.get('referenceModel')))
    provenance['methodId'] = METHOD_ID
    variants = {variant: {**values, 'metadata': precurve.metadata(variant)}
                for variant, values in VARIANTS.items()}
    qa.update(stdGeneration=GENERATION, stdInputGain=1.0, singleTonePrecurve=precurve.metadata('A'),
              stdVariants=variants, stdReferenceDescription=REFERENCE_DESCRIPTION,
              metricReference=REFERENCE_DESCRIPTION, vlogUnchanged=True,
              sourceVlogSha256=source_hash, rowsPerCube=33**3, fileChecks='passed')
    provenance.update(stdGeneration=GENERATION, singleTonePrecurve=precurve.metadata('A'),
                      stdVariants=variants, sourceVlog=precurve.source_metadata,
                      stdReferenceDescription=REFERENCE_DESCRIPTION,
                      gamutPolicy='Source VLOG gamut mapping/clipping is retained unchanged; STD adds no output colour operation.',
                      preview='Standard/sRGB source pixels -> exported variant A STD LUT once, tetrahedral; no extra adapter or output edit.')
    provenance['adapter'] = {'id': CONFIG['adapter'], 'generation': GENERATION,
                             'inputGain': 1.0, 'contract': STD_CONTRACT,
                             'limitation': 'Fixed per-LUT virtual tone reconstruction, not a measured camera inverse.'}
    if 'inputAdapter' in provenance:
        provenance['inputAdapter'].pop('stdCalibration', None)
        provenance['inputAdapter']['std'] = STD_CONTRACT
        provenance['inputAdapter']['output'] = 'Source VLOG renderer output RGB unchanged; no STD output colour edits.'
    number = record['number']
    with tempfile.TemporaryDirectory(prefix='.precurve-', dir=directory) as temp:
        staging = Path(temp)
        writer = LumixCubeFormat()
        tables, outputs, serialization = {}, {}, 0.
        gray = np.repeat(np.linspace(0, 1, 129)[:, None], 3, axis=1)
        points = np.concatenate([np.random.default_rng(CONFIG['seed']).random((CONFIG['qa_random_samples'], 3)), gray, cube_grid(5)])
        for variant, values in VARIANTS.items():
            raw = bake_std(vlog_path, variant=variant, precurve=precurve)
            path = staging / f'{number:04d}{values["suffix"]}.cube'
            writer.write(Lut(raw, title=f'{number:04d}_{values["suffix"]}'), path, photo_style_tag='STD')
            table = read_cube(path, 'STD')
            tables[variant] = table; outputs[values['fileKey']] = path
            serialization = max(serialization, float(np.max(np.abs(raw - table))))
            exact = precurve.apply(points, variant=variant)
            fidelity = {name: metrics(fn(table, points), exact)
                        for name, fn in [('tetrahedral', apply_tetrahedral), ('trilinear', apply_trilinear)]}
            qa['stdVsDirectEngine' if variant == 'A' else 'stdBVsDirectEngine'] = fidelity
        if serialization > .000000501:
            raise ValueError('Cube serialization changed the table')
        qa['serializationMaxError'] = max(serialization, qa.get('serializationMaxError', 0.))
        qa['stdSerializationMaxError'] = serialization
        qa['grayBlackToWhiteDelta'] = float(np.mean(tables['A'][-1, -1, -1] - tables['A'][0, 0, 0]))
        qa['grayResponse'] = {'inputCodes': (gray[:, 0] * 255).tolist(),
                              'scale': 'encoded sRGB RGB triples, 0..255',
                              'A': (apply_tetrahedral(tables['A'], gray) * 255).tolist(),
                              'B': (apply_tetrahedral(tables['B'], gray) * 255).tolist(),
                              'purpose': 'Exported A/B diagnostic, not physical camera/print calibration'}
        qa['warnings'] = []
        for variant, key in [('A', 'stdVsDirectEngine'), ('B', 'stdBVsDirectEngine')]:
            if qa[key]['tetrahedral']['p99'] > .02:
                qa['warnings'].append(f'STD {variant} 상위 1% 보간 오차가 0.02를 넘습니다. 색 경계를 검토하세요.')
        if qa.get('vlogVsDirectEngine', {}).get('tetrahedral', {}).get('p99', 0) > .05:
            qa['warnings'].append('V-Log 전체 도메인의 상위 1% 보간 오차가 0.05를 넘습니다.')
        previews, photo_fidelity, photo_fidelity_b = {}, {}, {}
        for sample in samples:
            pixels = np.asarray(Image.open(PUBLIC / sample['path'].lstrip('/')).convert('RGB')) / 255.
            flat = pixels.reshape(-1, 3)
            output = apply_tetrahedral(tables['A'], flat).reshape(pixels.shape)
            path = staging / f'{sample["id"]}.webp'
            save_image(output, path)
            previews[sample['id']] = describe(path, destination=directory / path.name)
            if sample.get('inputKind') == 'camera-std':
                chosen = np.random.default_rng(20261103).choice(len(flat), min(1024, len(flat)), replace=False)
                picked = flat[chosen]
                photo_fidelity[sample['id']] = metrics(apply_tetrahedral(tables['A'], picked), precurve.apply(picked, 'A'))
                photo_fidelity_b[sample['id']] = metrics(apply_tetrahedral(tables['B'], picked), precurve.apply(picked, 'B'))
        qa.update(photoPixelFidelity=photo_fidelity, photoPixelFidelityB=photo_fidelity_b,
                  sampling='4096 uniform random RGB + 129 gray + 125 RGB grid, fixed seed; 1024 pixels per camera sample',
                  cameraInterpolation='unknown; exported A/B tetrahedral and trilinear measured')
        save_json(staging / 'qa.json', qa)
        save_json(staging / 'provenance.json', provenance)
        (staging / 'README.txt').write_text(_bundle_readme(record, provenance))
        previous_changelog = (directory / 'CHANGELOG.txt').read_text() if (directory / 'CHANGELOG.txt').exists() else ''
        update = ('v4: Replace STD output corrections with one identical scalar input tone per RGB channel. '
                  'A retains reachable black/white; B anchors 18% linear gray and rolls highlights to reachable white. '
                  'Both use the unchanged exported VLOG cube. No neutral subtraction, chroma gain or output gamut edit.\n')
        if not previous_changelog.startswith(update): previous_changelog = update + '\n' + previous_changelog
        (staging / 'CHANGELOG.txt').write_text(previous_changelog)
        zip_path = staging / f'{number:04d}LUTS.zip'
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in [vlog_path, *outputs.values(), *[staging / name for name in ['README.txt', 'CHANGELOG.txt', 'qa.json', 'provenance.json']]]:
                archive.write(path, path.name)
            for name in ['SPEKTRAFILM_LICENSE.txt', 'FUJIFILM_NOTICE.txt']:
                if (directory / name).exists(): archive.write(directory / name, name)
        outputs.update(zip=zip_path, qa=staging / 'qa.json', provenance=staging / 'provenance.json')
        files = {**record['files'], **{key: describe(path, destination=directory / path.name) for key, path in outputs.items()}}
        record.update(status='ready', files=files, previews=previews, qa=qa, stdVariants=variants,
                      generatedAt=datetime.now(timezone.utc).isoformat(),
                      stdGenerationSeconds=round(time.perf_counter() - started, 3))
        # Cache identity is also dependent on the v4 code, not only VLOG inputs.
        record['stdCacheKey'] = {'sourceVlogSha256': source_hash,
                                 'precurveCodeSha256': sha256(ROOT / 'pipeline/precurve.py'),
                                 'generatorCodeSha256': sha256(Path(__file__))}
        save_json(staging / 'metadata.json', record)
        if sha256(vlog_path) != source_hash:
            raise ValueError('VLOG changed during STD generation')
        # Commit metadata last; readers never see a ready record for partial assets.
        for path in sorted(staging.iterdir(), key=lambda p: p.name == 'metadata.json'):
            path.replace(directory / path.name)
    return record


def _run(job):
    record, samples = job
    return rebuild_standard(record, samples, backup=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--only', action='append', help='Exact combination id; repeat for multiple looks')
    parser.add_argument('--jobs', type=int, default=3)
    parser.add_argument('--backup-only', action='store_true')
    args = parser.parse_args()
    catalog_path = PUBLIC / 'catalog.json'
    catalog = json.loads(catalog_path.read_text())
    backup_catalog(catalog)
    print(f'Immutable baseline verified: {BASELINE}', flush=True)
    if args.backup_only: return
    selected = [r for r in catalog['combinations'] if r['status'] == 'ready'
                and r['processMode'] != 'reference_interpretation'
                and (not args.only or r['id'] in args.only)]
    if not selected: raise SystemExit('No matching migratable combinations')
    indices = {r['id']: i for i, r in enumerate(catalog['combinations'])}
    before = {r['id']: r['files']['vlog']['sha256'] for r in selected}
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = [pool.submit(_run, (r, catalog['samples'])) for r in selected]
        for completed, future in enumerate(as_completed(futures), 1):
            record = future.result()
            if record['files']['vlog']['sha256'] != before[record['id']]: raise ValueError('VLOG hash changed')
            catalog['combinations'][indices[record['id']]] = record
            catalog.update(adapter=CONFIG['adapter'], stdGeneration=GENERATION,
                           generatedAt=datetime.now(timezone.utc).isoformat())
            save_json(catalog_path, catalog)
            print(f'[{completed}/{len(selected)}] {record["id"]} ({record["stdGenerationSeconds"]}s)', flush=True)
    # Source-package identifiers remain pinned; its STD description is the
    # current precurve contract, separate from historical VLOG referenceModel.
    if 'fujiStudy' in catalog:
        study = json.loads((ROOT / 'pipeline/config/fujifilm-official.json').read_text())
        catalog['fujiStudy'] = study
        save_json(PUBLIC / 'research/fujifilm-official.json', study)
        save_json(catalog_path, catalog)
    save_json(ROOT / 'artifacts/std-precurve-build-report.json', {
        'method': METHOD_ID, 'generation': GENERATION, 'rebuilt': len(selected),
        'wallSeconds': round(time.perf_counter() - started, 2), 'vlogAllUnchanged': True,
        'baseline': str(BASELINE),
    })


if __name__ == '__main__': main()
