"""Append four reference-inspired editorial looks without rebuilding models.

Run: .venv/bin/python -m pipeline.generate_research
Existing spektrafilm/print/slide/digital records and assets are preserved.
Run this after a full pipeline.generate build, which owns the model catalog.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import shutil
import time
import zipfile

import numpy as np
from PIL import Image
from pipeline.common import ROOT, PUBLIC, UPSTREAM, CONFIG, save_json, sha256, read_cube, metrics, std_to_vlog
from pipeline.generate import describe, valid_assets
from pipeline.samples import save_image
from pipeline.research import (REFERENCE_METHOD_ID, REFERENCE_CONTRACT, VLOG_CONTRACT,
                               VLOG_KNEE, NEUTRAL_CHROMA,
                               apply_reference_std, apply_reference_vlog, validate_parameters)
from spektrafilm_lut_creator.formats import Lut
from spektrafilm_lut_creator.formats.lumix import LumixCubeFormat
from spektrafilm_lut_creator.grid import cube_grid
from spektrafilm_lut_creator.qa.evaluators import apply_tetrahedral, apply_trilinear

CONFIG_PATH = ROOT / 'pipeline/config/reference-looks.json'
FILM_NUMBERS = {'kodak_portra_400': 177, 'kodak_gold_200': 178,
                'fujifilm_pro_400h': 179, 'fujifilm_c200': 180}
TRUTH = {'outputOrigin': 'generated_digital_interpretation',
         'referencesAreRealFilm': True, 'outputIsRealFilm': False,
         'physicalFilmCalibrated': False, 'upstreamFilmPaperPipelineApplied': False}


def load_study(path=CONFIG_PATH):
    study = json.loads(path.read_text())
    if study.get('methodId') != REFERENCE_METHOD_ID or study.get('schemaVersion') != 1:
        raise ValueError('Unsupported reference interpretation configuration')
    looks = study['looks']
    if len(looks) != 4 or {look['film'] for look in looks} != set(FILM_NUMBERS):
        raise ValueError('Expected the four explicitly researched film looks')
    for look in looks:
        if look['number'] != FILM_NUMBERS[look['film']]:
            raise ValueError('Reference look numbers must remain 177–180')
        validate_parameters(look['parameters'])
        if not look.get('references'):
            raise ValueError('Each editorial look must identify its real-film references')
    return study


def reference_cache_key(study, look, samples):
    payload = {'study': study, 'look': look, 'truth': TRUTH,
               'code': {name: sha256(ROOT / 'pipeline' / name)
                        for name in ['research.py', 'generate_research.py']},
               'samples': {s['id']: sha256(PUBLIC / s['path'].lstrip('/')) for s in samples}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def generate_look(study, look, film, samples, *, force=False):
    started = time.perf_counter()
    combo_id = f"{film['id']}__reference"
    directory = PUBLIC / 'luts' / combo_id
    metadata = directory / 'metadata.json'
    key = reference_cache_key(study, look, samples)
    if metadata.exists() and not force:
        previous = json.loads(metadata.read_text())
        if previous.get('cacheKey') == key and valid_assets(previous):
            return previous
    directory.mkdir(parents=True, exist_ok=True)
    parameters = look['parameters']
    number = look['number']
    grid = cube_grid(33)
    writer = LumixCubeFormat()
    tables, paths = {}, {}
    serialization_error = 0.
    for tag, transform in [('VLOG', apply_reference_vlog), ('STD', apply_reference_std)]:
        raw_table = transform(grid, parameters).reshape(33, 33, 33, 3)
        if not np.isfinite(raw_table).all() or raw_table.min() < 0 or raw_table.max() > 1:
            raise ValueError('Reference transform produced invalid LUT values')
        path = directory / f'{number:04d}{tag}.cube'
        writer.write(Lut(raw_table, title=f'{number:04d}_{tag}'), path, photo_style_tag=tag)
        tables[tag] = read_cube(path, tag)
        paths[tag] = path
        serialization_error = max(serialization_error, float(np.max(np.abs(raw_table - tables[tag]))))
    if serialization_error > .000000501:
        raise ValueError('LUT serialization exceeded six-decimal tolerance')
    rng = np.random.default_rng(CONFIG['seed'])
    gray = np.repeat(np.linspace(0, 1, 129)[:, None], 3, axis=1)
    points = np.concatenate([rng.random((4096, 3)), gray, cube_grid(5)])
    fidelity = {}
    for tag, transform in [('VLOG', apply_reference_vlog), ('STD', apply_reference_std)]:
        reference = transform(points, parameters)
        fidelity[tag] = {name: metrics(interpolate(tables[tag], points), reference)
                         for name, interpolate in [('tetrahedral', apply_tetrahedral), ('trilinear', apply_trilinear)]}
    envelope = std_to_vlog(points)
    envelope_reference = apply_reference_vlog(envelope, parameters)
    envelope_fidelity = {name: metrics(interpolate(tables['VLOG'], envelope), envelope_reference)
                         for name, interpolate in [('tetrahedral', apply_tetrahedral), ('trilinear', apply_trilinear)]}
    photo_fidelity = {}
    for sample in samples:
        if sample.get('inputKind') != 'camera-std':
            continue
        pixels = np.asarray(Image.open(PUBLIC / sample['path'].lstrip('/')).convert('RGB')).reshape(-1, 3) / 255.
        indices = np.random.default_rng(20261103).choice(len(pixels), min(4096, len(pixels)), replace=False)
        photo_points = pixels[indices]
        synthetic_vlog = std_to_vlog(photo_points)
        photo_fidelity[sample['id']] = {
            'std': metrics(apply_tetrahedral(tables['STD'], photo_points), apply_reference_std(photo_points, parameters)),
            'syntheticVlogFromStd': metrics(apply_tetrahedral(tables['VLOG'], synthetic_vlog), apply_reference_vlog(synthetic_vlog, parameters)),
        }
    warnings = []
    if fidelity['STD']['tetrahedral']['p99'] > .02:
        warnings.append('STD와 해석형 색변환의 상위 1% 보간 오차가 0.02를 넘습니다.')
    if fidelity['VLOG']['tetrahedral']['p99'] > .05:
        warnings.append('V-Log 전체 도메인과 해석형 색변환의 상위 1% 보간 오차가 0.05를 넘습니다.')
    qa = {'fileChecks': 'passed', 'cameraVerified': False, 'warnings': warnings,
          'rowsPerCube': 35937, 'serializationMaxError': serialization_error,
          'processMode': 'reference_interpretation', 'referenceModel': REFERENCE_METHOD_ID,
          'stdVsAnalyticTransform': fidelity['STD'], 'vlogVsAnalyticTransform': fidelity['VLOG'],
          'vlogWithinSrgbEnvelope': envelope_fidelity,
          'photoPixelFidelity': photo_fidelity,
          'photoPixelSampling': '4096 distinct pixels per user Standard photo; fixed seed 20261103; VLOG values are synthetic sRGB-to-VGamut/VLog coordinates, not captured V-Log footage',
          'vlogEnvelopeSampling': '4350 bounded sRGB points analytically mapped into V-Gamut/V-Log; synthetic display-gamut envelope, not camera validation',
          # Keep compatible metric keys, while identifying their actual reference.
          'stdVsDirectEngine': fidelity['STD'], 'vlogVsDirectEngine': fidelity['VLOG'],
          'metricReference': 'Continuous analytic evaluation of the editorial transform, not a film model or real-film measurement',
          'sampling': '4096 uniform random RGB + 129 gray ramp + 125 RGB grid; fixed seed',
          'stdGeneration': 'reference-interpretation-direct-grid', **TRUTH}
    save_json(directory / 'qa.json', qa)
    provenance = {
        'method': {'id': REFERENCE_METHOD_ID, 'stdContract': REFERENCE_CONTRACT, 'vlogContract': VLOG_CONTRACT},
        'sharedParameters': {'gamutMapping': 'linear-sRGB channel boundary clamp; no exact out-of-gamut OKLab hue/lightness guarantee',
                             'vlogLinearChannelKnee': VLOG_KNEE,
                             'neutralProtectionChroma': NEUTRAL_CHROMA,
                             'shadowTintCenterSigma': [.25, .22], 'highlightTintCenterSigma': [.80, .20]},
        'processMode': 'reference_interpretation', 'filmNameReference': film['id'], 'paper': None,
        'referenceStudy': study, 'look': look, 'parameters': parameters, **TRUTH,
        'attribution': 'Independent Film Lab colour interpretation; shared LUT writer/evaluator tooling from spektrafilm by Andrea Volpato',
        'upstreamTooling': {'repository': 'https://github.com/andreavolpato/spektrafilm',
                            'commit': CONFIG['engine_commit'], 'runtimeFilmPaperStagesUsed': False},
        'preview': 'User-owned Standard/sRGB digital photos -> exported STD LUT once; not photographs captured on the named film',
        'effects': {'grain': False, 'halation': False, 'autoExposure': False},
        'license': 'CC BY-SA 4.0 for distributed LUT assets; real-film reference photographs retain their original rights',
    }
    save_json(directory / 'provenance.json', provenance)
    previews = {}
    for sample in samples:
        image = np.asarray(Image.open(PUBLIC / sample['path'].lstrip('/')).convert('RGB')) / 255.
        output = apply_tetrahedral(tables['STD'], image.reshape(-1, 3)).reshape(image.shape)
        path = directory / f"{sample['id']}.webp"
        save_image(output, path)
        previews[sample['id']] = describe(path)
    readme = f'''Film Lab reference interpretation / {look.get('name', film['name'])}

These are generated digital interpretations informed by real-film photographs.
The output is NOT a real-film photograph, calibrated film reproduction, or a
spektrafilm film/paper simulation. No film or paper runtime stages are applied.
Source links and editorial coefficients: provenance.json.

{number:04d}STD.cube: encoded Standard/sRGB -> editorial OKLab look -> sRGB.
{number:04d}VLOG.cube: V-Log/V-Gamut -> shared approximate display base -> same look.
The V-Log base has a per-channel linear shoulder above 0.75 and preserves 18.4% gray.
Both files: 33 x 33 x 33; full range 0..1; output sRGB, not Rec.709.
No camera or physical film calibration has been performed.

Independent colour algorithm: Film Lab.
Shared LUT export/evaluator tooling: spektrafilm by Andrea Volpato.
https://github.com/andreavolpato/spektrafilm
Distributed LUT assets: CC BY-SA 4.0. Source-photo copyrights are unchanged.
Actual reference photographs are linked, not redistributed in this ZIP.
'''
    (directory / 'README.txt').write_text(readme)
    (directory / 'CHANGELOG.txt').write_text(
        'Added an independent editorial OKLab interpretation with declared real-film references. '
        'No upstream film or paper pipeline is applied. Existing 148 model looks are unchanged. '
        'Reference photographs are not generated outputs and are not bundled.\n')
    shutil.copyfile(UPSTREAM / 'SPEKTRAFILM_LICENSE.txt', directory / 'SPEKTRAFILM_LICENSE.txt')
    zip_path = directory / f'{number:04d}LUTS.zip'
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in [paths['VLOG'], paths['STD'], *[directory / name for name in
                     ['qa.json', 'provenance.json', 'README.txt', 'CHANGELOG.txt', 'SPEKTRAFILM_LICENSE.txt']]]:
            archive.write(path, path.name)
    record = {'id': combo_id, 'film': film['id'], 'paper': None, 'number': number,
              'processMode': 'reference_interpretation', 'status': 'ready', 'cacheKey': key,
              'files': {'vlog': describe(paths['VLOG']), 'std': describe(paths['STD']),
                        'zip': describe(zip_path), 'qa': describe(directory / 'qa.json'),
                        'provenance': describe(directory / 'provenance.json')},
              'previews': previews, 'qa': qa, **TRUTH,
              'seconds': round(time.perf_counter() - started, 3),
              'generatedAt': datetime.now(timezone.utc).isoformat()}
    save_json(metadata, record)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--only', choices=list(FILM_NUMBERS))
    args = parser.parse_args()
    study = load_study()
    path = PUBLIC / 'catalog.json'
    catalog = json.loads(path.read_text())
    preserved = [c for c in catalog['combinations'] if c['processMode'] != 'reference_interpretation']
    if len(preserved) != 148 or not all(valid_assets(c) for c in preserved):
        raise SystemExit('Expected 148 intact existing model looks; no changes made')
    before = json.dumps(preserved, sort_keys=True)
    references = {c['id']: c for c in catalog['combinations'] if c['processMode'] == 'reference_interpretation'}
    for look in study['looks']:
        if args.only and look['film'] != args.only:
            continue
        film = next(f for f in catalog['films'] if f['id'] == look['film'])
        record = generate_look(study, look, film, catalog['samples'], force=args.force)
        references[record['id']] = record
        print(f"ready {record['id']} ({record['seconds']}s)", flush=True)
    catalog['combinations'] = preserved + sorted(references.values(), key=lambda c: c['number'])
    catalog['counts'] = {status: sum(c['status'] == status for c in catalog['combinations'])
                         for status in ['ready', 'failed', 'unsupported', 'not-generated']}
    catalog['referenceStudy'] = study
    catalog['generatedAt'] = datetime.now(timezone.utc).isoformat()
    if json.dumps(catalog['combinations'][:148], sort_keys=True) != before:
        raise RuntimeError('Existing model records changed; refusing catalog update')
    save_json(PUBLIC / 'research/reference-looks.json', study)
    save_json(path, catalog)
    print(json.dumps(catalog['counts']), flush=True)


if __name__ == '__main__':
    main()
