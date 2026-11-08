"""Camera-specific Standard input composed with unchanged serialized V-Log LUTs.

Production replacement for Film Lab's former camera-agnostic STD tone models.
This module never evaluates or modifies the creative renderer's colour engine.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

import numpy as np
from pipeline.common import CONFIG, PUBLIC, ROOT, UPSTREAM, metrics, read_cube, save_json, sha256
from spektrafilm_lut_creator.grid import cube_grid
from spektrafilm_lut_creator.qa.evaluators import apply_tetrahedral, apply_trilinear

METHOD = 'camera-vlog-alchemy-v1'
DEFAULT_CAMERA = 'S1II'
SOURCE_URL = 'https://github.com/shenmintao/V-Log-Alchemy'
COMMIT = 'e51ba9a23458ff5c316f630b860eb0201139d126'
SOURCE_DIR = 'Luts/Panasonic-Standard'
ADAPTERS = PUBLIC / 'camera-adapters'
BASELINE = ROOT / 'artifacts/std-b-before-camera-alchemy'
REFERENCE_DESCRIPTION = (
    'Serialized camera-specific Standard-to-V-Log adapter (trilinear) followed '
    'by the unchanged serialized creative VLOG cube (tetrahedral). '
    'stdVsDirectEngine is a compatibility key for this sequential transform; '
    'it measures 33-grid rebaking error, not a continuous engine or camera accuracy.'
)
LIMITATIONS = [
    'Standard clipping and gamut compression cannot be inverted exactly; clipped highlights and colours cannot be restored.',
    'Use the exact camera model and unadjusted Standard Photo Style. No automatic exposure or image statistics are applied.',
    'Camera cube interpolation is undocumented; tetrahedral and trilinear rebake error are both reported.',
    'Native V-Log acquisition gain, noise and highlight headroom cannot be recreated by an output LUT.',
]


def describe(path: Path):
    return {'path': '/' + path.relative_to(PUBLIC).as_posix(), 'name': path.name,
            'bytes': path.stat().st_size, 'sha256': sha256(path)}


def prepare_sources(checkout: Path):
    """Copy only hash-locked, attributed distribution inputs from pinned source."""
    head = subprocess.check_output(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], text=True).strip()
    if head != COMMIT:
        raise ValueError('V-Log Alchemy checkout must match pinned commit')
    if subprocess.run(['git', '-C', str(checkout), 'diff', '--quiet', 'HEAD', '--', SOURCE_DIR, 'LICENSE']).returncode:
        raise ValueError('Pinned V-Log Alchemy source files have local modifications')
    source = checkout / SOURCE_DIR
    manifest = json.loads((source / 'manifest.json').read_text())
    ADAPTERS.mkdir(parents=True, exist_ok=True)
    for item in manifest['luts']:
        path = source / item['path']
        if sha256(path) != item['sha256']:
            raise ValueError(f'Upstream adapter hash mismatch: {item["path"]}')
        shutil.copyfile(path, ADAPTERS / path.name)
    for name in ['README.md', 'manifest.json', 'SHA256SUMS.txt']:
        shutil.copyfile(source / name, ADAPTERS / name)
    shutil.copyfile(checkout / 'LICENSE', ADAPTERS / 'V-Log-Alchemy-LICENSE.txt')
    # Keep the complete validation disclosures with their source-relative paths.
    for group in ['Reports', 'Calibration']:
        (ADAPTERS / group).mkdir(exist_ok=True)
        for path in (source / group).glob('*.json'):
            shutil.copyfile(path, ADAPTERS / group / path.name)
    save_json(ADAPTERS / 'source.json', {'repository': SOURCE_URL, 'commit': COMMIT,
              'packageVersion': manifest['package_version'], 'sourcePath': SOURCE_DIR,
              'license': 'Apache-2.0', 'filesUnmodified': True,
              'note': 'Conversion cubes are copied without changes; Film Lab merged creative LUTs are separately identified derivatives.'})
    models.cache_clear(); adapter_table.cache_clear()
    return camera_catalog()


@lru_cache(maxsize=1)
def models():
    manifest = json.loads((ADAPTERS / 'manifest.json').read_text())
    result = []
    for item in manifest['luts']:
        camera_id = item['models'][0]
        # The upstream L10 alias denotes DC-L10. It must never mean DMC-L10.
        if camera_id == 'L10': camera_id = 'DC-L10'
        path = ADAPTERS / Path(item['path']).name
        if sha256(path) != item['sha256']:
            raise ValueError(f'Adapter hash mismatch: {camera_id}')
        status = item['validation']['status']
        result.append({'id': camera_id, 'name': 'LUMIX ' + camera_id,
                       'aliases': item['models'], 'asset': describe(path),
                       'validation': 'controlled' if status == 'controlled_quantitative' else 'field' if status == 'qualitative_field_report' else 'pending',
                       'cameraUse': 'in-camera' if item['camera_recording'] else 'post-only',
                       'sourceValidation': item['validation'],
                       'sourcePath': SOURCE_DIR + '/' + item['path'],
                       'dualLutMinFirmware': item['dual_lut_min_firmware']})
    return tuple(sorted(result, key=lambda m: (m['id'] != DEFAULT_CAMERA, m['id'])))


def camera_catalog():
    return {'method': METHOD, 'defaultCamera': DEFAULT_CAMERA, 'sourceUrl': SOURCE_URL,
            'commit': COMMIT, 'models': list(models()), 'limitations': LIMITATIONS,
            'unsupportedModels': ['DMC-L10'],
            'qualitativeObservation': {'camera': 'S1II', 'date': '2026-11-04',
                'combination': 'fujifilm_c200__fujifilm_crystal_archive_typeii',
                'scope': 'User reported the merged STD test looked close to their V-Log result in one indoor scene; not controlled quantitative camera validation.'}}


def normalize_camera(value: str):
    value = value.strip().upper()
    if value in {'DMC-L10', 'LUMIX DMC-L10'}:
        raise ValueError('DMC-L10 has no supported adapter; DC-L10 is a different camera')
    for model in models():
        if value == model['id'] or value in model['aliases']:
            return model['id']
    raise ValueError(f'Unsupported Standard camera: {value}')


@lru_cache(maxsize=10)
def adapter_table(camera_id: str):
    model = next(m for m in models() if m['id'] == normalize_camera(camera_id))
    return read_cube(PUBLIC / model['asset']['path'].lstrip('/'))


def alchemy_trilinear(table, samples):
    """Vectorized arithmetic order of the pinned Alchemy reference merger."""
    position = np.clip(np.asarray(samples, dtype=np.float64), 0., 1.) * (len(table) - 1)
    base = np.minimum(np.floor(position).astype(int), len(table) - 2)
    frac = position - base
    out = np.zeros_like(position)
    for db in range(2):
        wb = frac[:, 2] if db else 1. - frac[:, 2]
        for dg in range(2):
            wg = frac[:, 1] if dg else 1. - frac[:, 1]
            for dr in range(2):
                wr = frac[:, 0] if dr else 1. - frac[:, 0]
                weight = wr * wg * wb
                out += weight[:, None] * table[base[:, 2] + db, base[:, 1] + dg, base[:, 0] + dr]
    return out


def alchemy_tetrahedral(table, samples):
    """Same stable RGB-axis ordering and edge sums as upstream sample_tetrahedral."""
    position = np.clip(np.asarray(samples, dtype=np.float64), 0., 1.) * (len(table) - 1)
    coords = np.minimum(np.floor(position).astype(int), len(table) - 2)
    frac = position - coords
    order = np.argsort(-frac, axis=1, kind='stable')
    row = np.arange(len(coords))
    previous = table[coords[:, 2], coords[:, 1], coords[:, 0]]
    out = previous.copy()
    for rank in range(3):
        axis = order[:, rank]
        coords[row, axis] += 1
        following = table[coords[:, 2], coords[:, 1], coords[:, 0]]
        out += frac[row, axis, None] * (following - previous)
        previous = following
    return out


def compose(vlog, camera_id, points):
    return np.clip(alchemy_tetrahedral(vlog, alchemy_trilinear(adapter_table(camera_id), points)), 0., 1.)


def serialize_std(table, camera_id, vlog_name):
    stream = io.StringIO()
    stream.write(f'TITLE "{camera_id} Standard - {Path(vlog_name).stem}"\n#LUMIXPHOTOSTYLE STD\n')
    stream.write('LUT_3D_SIZE 33\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n')
    stream.write('# Modified by Film Lab: camera V-Log Alchemy adapter composed with the attributed creative VLOG renderer.\n')
    np.savetxt(stream, np.clip(table, 0., 1.).reshape(-1, 3), fmt='%.9f')
    return stream.getvalue().encode('ascii')


def backup_record(record):
    """Archive replaced STD artifacts once, avoiding duplicate original VLOGs."""
    if record.get('stdMethod') == METHOD: return
    source = PUBLIC / 'luts' / record['id']
    target = BASELINE / record['id']
    marker = target / 'baseline-manifest.json'
    if marker.exists():
        for name, digest in json.loads(marker.read_text())['sha256'].items():
            if sha256(target / name) != digest: raise ValueError(f'Changed baseline: {record["id"]}')
        return
    target.mkdir(parents=True, exist_ok=True)
    vlog_name = record['files']['vlog']['name']
    names = set(['metadata.json', 'qa.json', 'provenance.json', 'README.txt', 'CHANGELOG.txt'])
    names.update(a['name'] for k, a in record.get('files', {}).items() if k != 'vlog')
    names.update(a['name'] for a in record.get('previews', {}).values())
    copied = {}
    for name in sorted(names - {vlog_name}):
        if (source / name).is_file():
            shutil.copy2(source / name, target / name)
            copied[name] = sha256(target / name)
    save_json(marker, {'id': record['id'], 'sha256': copied,
              'unchangedVlogSha256': record['files']['vlog']['sha256'], 'sourceMethod': record.get('stdVariant', 'legacy')})


def clean_old_fields(value):
    result = deepcopy(value)
    for key in list(result):
        if key.startswith('std') or key in {'singleTonePrecurve', 'jpgToneProtection', 'photoPixelFidelity',
                'photoPixelFidelityB', 'grayResponse', 'grayBlackToWhiteDelta', 'metricReference',
                'distribution', 'cameraAdapter', 'composition'}:
            result.pop(key, None)
    return result


def camera_warnings(model):
    warnings = list(LIMITATIONS)
    if model['validation'] == 'pending': warnings.append('Matched controlled capture validation is pending for this camera model.')
    if model['validation'] == 'field': warnings.append('Upstream support is qualitative field feedback, not controlled quantitative camera validation.')
    if model['cameraUse'] == 'post-only': warnings.append('GH6: post-processing only; Standard capture cannot bake this LUT in camera.')
    if model['id'] == 'DC-L10': warnings.append('For DC-L10 only. This adapter is not compatible with the older DMC-L10.')
    return warnings


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode()


def _zip_bytes(entries):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, data in entries.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 11, 4, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data, compresslevel=6)
    return stream.getvalue()


def rebuild_standard(record, samples=None, *, backup=True):
    """Bake all model-specific STD outputs from one immutable serialized VLOG."""
    record = deepcopy(record)
    directory = PUBLIC / 'luts' / record['id']
    if backup: backup_record(record)
    vlog_path = PUBLIC / record['files']['vlog']['path'].lstrip('/')
    source_hash = sha256(vlog_path)
    if source_hash != record['files']['vlog']['sha256']:
        raise ValueError(f'Changed VLOG source: {record["id"]}')
    vlog_bytes = vlog_path.read_bytes()
    vlog = read_cube(vlog_path, 'VLOG')
    base_qa = clean_old_fields(record.get('qa') or json.loads((directory / 'qa.json').read_text()))
    base_provenance = clean_old_fields(json.loads((directory / 'provenance.json').read_text()))
    base_provenance['sourceRenderingMethod'] = base_provenance.get('sourceRenderingMethod', base_provenance.get('methodId', base_qa.get('referenceModel')))
    base_provenance['methodId'] = METHOD
    if 'config' in base_provenance: base_provenance['config']['adapter'] = METHOD
    base_provenance.pop('adapter', None)
    if 'inputAdapter' in base_provenance:
        base_provenance['inputAdapter'].pop('stdCalibration', None)
        base_provenance['inputAdapter']['std'] = 'Selected camera Standard -> pinned V-Log Alchemy adapter -> unchanged exported VLOG renderer.'
        base_provenance['inputAdapter']['output'] = 'Source VLOG output RGB unchanged; no additional tone or colour edits.'
    base_provenance.update(stdMethod=METHOD, stdGeneration=METHOD,
        stdReferenceDescription=REFERENCE_DESCRIPTION,
        gamutPolicy='Unchanged source VLOG output gamut mapping and clipping; no added output correction.',
        preview='Selected camera Standard pixels -> selected merged STD cube once, tetrahedral interpolation.',
        sourceVlog={'name': vlog_path.name, 'sha256': source_hash})
    licenses = {'SPEKTRAFILM_LICENSE.txt': (UPSTREAM / 'SPEKTRAFILM_LICENSE.txt').read_bytes(),
                'spektrafilm-LICENSE.txt': (UPSTREAM / 'LICENSE').read_bytes(),
                'V-Log-Alchemy-LICENSE.txt': (ADAPTERS / 'V-Log-Alchemy-LICENSE.txt').read_bytes()}
    if (directory / 'FUJIFILM_NOTICE.txt').exists(): licenses['FUJIFILM_NOTICE.txt'] = (directory / 'FUJIFILM_NOTICE.txt').read_bytes()
    grid = cube_grid(33)
    gray = np.repeat(np.linspace(0., 1., 257)[:, None], 3, axis=1)
    points = np.concatenate([np.random.default_rng(CONFIG['seed']).random((CONFIG['qa_random_samples'], 3)), gray, cube_grid(5)])
    by_camera = {}
    old_files = deepcopy(record.get('files', {}))
    for model in models():
        camera = model['id']
        raw = compose(vlog, camera, grid).reshape(33, 33, 33, 3)
        std_name = f'{record["number"]:04d}STD.cube'
        std_bytes = serialize_std(raw, camera, vlog_path.name)
        # Re-read serialized rows; QA measures the actual downloadable cube.
        table = np.loadtxt(io.BytesIO(std_bytes), skiprows=6, comments='#').reshape(33, 33, 33, 3)
        serialization = float(np.max(np.abs(table - raw)))
        if serialization > 5.0001e-10: raise ValueError('STD serialization exceeded nine decimal bound')
        reference = compose(vlog, camera, points)
        fidelity = {name: metrics(fn(table, points), reference) for name, fn in [('tetrahedral', apply_tetrahedral), ('trilinear', apply_trilinear)]}
        warnings = camera_warnings(model)
        std_hash = hashlib.sha256(std_bytes).hexdigest()
        qa = {**base_qa, 'stdMethod': METHOD, 'stdGeneration': METHOD, 'camera': camera,
              'fileChecks': 'passed', 'rowsPerCube': 33**3, 'cameraVerified': False,
              'stdReferenceDescription': REFERENCE_DESCRIPTION, 'metricReference': REFERENCE_DESCRIPTION,
              'stdVsDirectEngine': fidelity, 'stdSerializationMaxError': serialization,
              'sourceVlogSha256': source_hash, 'sourceAdapterSha256': model['asset']['sha256'],
              'vlogUnchanged': True, 'warnings': warnings,
              'cameraInterpolation': 'Undocumented. Both tetrahedral and trilinear output evaluation are measured.',
              'sampling': {'randomRgb': CONFIG['qa_random_samples'], 'neutralRamp': 257, 'grid': 5**3, 'seed': CONFIG['seed']}}
        adapter = {'id': camera, 'sourceUrl': SOURCE_URL, 'commit': COMMIT,
                   'sourcePath': model['sourcePath'], 'sha256': model['asset']['sha256'],
                   'validation': model['validation'], 'cameraUse': model['cameraUse'], 'aliases': model['aliases'],
                   'sourceValidation': model['sourceValidation']}
        provenance = {**base_provenance, 'cameraAdapter': adapter,
                      'composition': {'method': METHOD, 'formula': 'L_STD(x) = L_VLOG(A_camera(x))',
                          'interpolation': {'adapter': 'trilinear', 'creative': 'tetrahedral'},
                          'outputResolution': 33, 'serializationDecimals': 9,
                          'extraToneCurve': False, 'outputColourCorrection': False, 'imageStatistics': False},
                      'distribution': {'stdMethod': METHOD, 'camera': camera, 'stdSha256': std_hash, 'vlogSha256': source_hash},
                      'cameraVerified': False, 'limitations': warnings}
        if camera == 'S1II' and record['id'] == 'fujifilm_c200__fujifilm_crystal_archive_typeii':
            provenance['qualitativeObservation'] = camera_catalog()['qualitativeObservation']
        readme = f'''Film Lab / {record['film']} / {record.get('paper') or record['processMode']}
Camera: {model['name']} ({', '.join(model['aliases'])})

{std_name}: {camera} Standard -> V-Log Alchemy adapter -> original creative VLOG.
{vlog_path.name}: unchanged Panasonic V-Log / V-Gamut -> sRGB renderer.
Both are 33 x 33 x 33, full range 0..1. Apply only one creative cube.
STD: select this exact camera model, unadjusted Standard base, LUT opacity 100%.
VLOG: supply real Panasonic V-Log/V-Gamut. Do not add a second display conversion.
GH6 Standard output is post-processing only. DC-L10 does not mean DMC-L10.

The merged STD uses adapter trilinear -> serialized creative tetrahedral, then
nine-decimal 33-grid export. It contains no Film Lab B precurve, chroma gain,
automatic exposure or added colour correction. Browser previews use the same
merged cube. QA compares the serialized cube against the sequential transform;
it does not establish physical film accuracy or a camera-specific match.

Source adapter: {SOURCE_URL}/blob/{COMMIT}/{model['sourcePath']}
Adapter SHA256: {model['asset']['sha256']}
Creative VLOG SHA256: {source_hash}
Upstream camera calibration status: {model['validation']}.

Modified by Film Lab: merged camera Standard adapter and creative VLOG renderer.
V-Log Alchemy by shenmintao, Apache-2.0; license included.
spektrafilm by Andrea Volpato, https://github.com/andreavolpato/spektrafilm
SPEKTRAFILM_LICENSE.txt and spektrafilm-LICENSE.txt preserve upstream terms.
FUJIFILM source rights remain separate where FUJIFILM_NOTICE.txt is included.

''' + '\n'.join('- ' + warning for warning in warnings) + '\n'
        changelog = '2026-11-04 Film Lab: replaced camera-agnostic STD with pinned camera-specific V-Log Alchemy composition. Original creative VLOG bytes unchanged.\n'
        qa_bytes = json_bytes(qa); provenance_bytes = json_bytes(provenance)
        entries = {std_name: std_bytes, vlog_path.name: vlog_bytes, 'qa.json': qa_bytes,
                   'provenance.json': provenance_bytes, 'README.txt': readme.encode(),
                   'CHANGELOG.txt': changelog.encode(), **licenses}
        zip_name = f'{record["number"]:04d}LUTS.zip' if camera == DEFAULT_CAMERA else f'{record["number"]:04d}{camera}.zip'
        zip_path = directory / zip_name
        zip_path.write_bytes(_zip_bytes(entries))
        zip_asset = describe(zip_path)
        if camera == DEFAULT_CAMERA:
            std_path = directory / std_name; std_path.write_bytes(std_bytes)
            std_asset = describe(std_path)
            for name in ['qa.json', 'provenance.json', 'README.txt', 'CHANGELOG.txt', *licenses]:
                (directory / name).write_bytes(entries[name])
            record['qa'] = qa
            record['files'] = {'std': std_asset, 'vlog': describe(vlog_path), 'zip': zip_asset,
                               'qa': describe(directory / 'qa.json'), 'provenance': describe(directory / 'provenance.json')}
        else:
            std_asset = {'path': zip_asset['path'], 'name': std_name, 'bytes': len(std_bytes), 'sha256': std_hash,
                         'encoding': 'zip-entry', 'transferBytes': zip_asset['bytes'], 'transferSha256': zip_asset['sha256']}
        by_camera[camera] = {'std': std_asset, 'zip': zip_asset, 'qa': fidelity, 'warnings': warnings}
    for key, asset in old_files.items():
        if key in {'std', 'stdB', 'stdLegacy', 'stdRefined'} and asset['name'] != record['files']['std']['name']:
            path = directory / asset['name']
            if path.is_file(): path.unlink()
    for asset in record.get('previews', {}).values():
        path = directory / asset['name']
        if path.is_file(): path.unlink()
    for key in ['stdVariant', 'stdVariants', 'stdCacheKey', 'stdGenerationSeconds']:
        record.pop(key, None)
    record.update(stdMethod=METHOD, stdByCamera=by_camera, previews={}, previewMode='runtime-std',
                  generatedAt=datetime.now(timezone.utc).isoformat())
    if sha256(vlog_path) != source_hash: raise ValueError('VLOG changed during migration')
    save_json(directory / 'metadata.json', record)
    return record
