"""Legacy transport must preserve historical colour bytes and current A/B."""
from copy import deepcopy
import json
import zipfile

import pytest

from pipeline.prepare_legacy_v3 import digest, json_bytes, prepare_legacy_v3

IDS = ['kodak_portra_400__kodak_portra_endura', 'gfx_classic_chrome__official_direct']


@pytest.fixture
def sources(tmp_path):
    """Small self-contained archives exercise the immutable transport contract.

    Do not depend on ignored historical audit folders being in a fresh clone.
    Actual 238-output verification is also run by the preparation command.
    """
    public_root, baseline_root = tmp_path / 'public', tmp_path / 'baseline'
    public_root.mkdir(); baseline_root.mkdir()
    old_rows, current_rows = [], []
    for number, cid in enumerate(IDS, 1):
        official = cid.startswith('gfx_')
        directory = baseline_root / cid
        directory.mkdir()
        qa = {'jpgToneProtection': {'method': 'film-lab-jpg-tone-v3'},
              'stdVsDirectEngine': {'tetrahedral': {'max': 0.01}}, 'warnings': []}
        if not official:
            qa.update(stdGeneration='historical-v3', stdVsContinuousComposition={'max': 0.02})
        names = {'std': f'{number:04d}STD.cube', 'vlog': f'{number:04d}VLOG.cube',
                 'qa': 'qa.json', 'provenance': 'provenance.json', 'zip': f'{number:04d}LUTS.zip'}
        entries = {
            names['std']: b'#LUMIXPHOTOSTYLE STD\nLUT_3D_SIZE 2\n0 0 0\n',
            names['vlog']: b'#LUMIXPHOTOSTYLE VLOG\nLUT_3D_SIZE 2\n0 0 0\n',
            names['qa']: json_bytes(qa),
            names['provenance']: json_bytes({'generation': 'historical-v3'}),
            'README.txt': b'Original v3 instructions', 'CHANGELOG.txt': b'Original v3 history',
            'SPEKTRAFILM_LICENSE.txt': b'Original licence notice',
        }
        if official: entries['FUJIFILM_NOTICE.txt'] = b'Original official-source notice'
        for name, raw in entries.items(): (directory / name).write_bytes(raw)
        with zipfile.ZipFile(directory / names['zip'], 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, raw in entries.items(): archive.writestr(name, raw)
        def asset(folder, name):
            raw = (folder / name).read_bytes()
            return {'path': f'/luts/{cid}/{name}', 'name': name,
                    'bytes': len(raw), 'sha256': digest(raw)}
        old = {'id': cid, 'number': number, 'status': 'ready',
               'processMode': 'official_direct' if official else 'negative_print',
               'files': {key: asset(directory, name) for key, name in names.items()}, 'qa': qa}
        hashes = {name: digest(raw) for name, raw in entries.items()}
        hashes[names['zip']] = digest((directory / names['zip']).read_bytes())
        (directory / 'baseline-manifest.json').write_bytes(json_bytes({'sha256': hashes}))
        old_rows.append(old)
        current_dir = public_root / 'luts' / cid
        current_dir.mkdir(parents=True)
        current_entries = {**entries, names['std']: entries[names['std']] + b'# A variant\n',
                           f'{number:04d}STB.cube': entries[names['std']] + b'# B variant\n'}
        for name, raw in current_entries.items(): (current_dir / name).write_bytes(raw)
        with zipfile.ZipFile(current_dir / names['zip'], 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, raw in current_entries.items(): archive.writestr(name, raw)
        current = deepcopy(old)
        current['files'] = {key: asset(current_dir, name) for key, name in names.items()}
        current['files']['stdB'] = asset(current_dir, f'{number:04d}STB.cube')
        current_rows.append(current)
    # References stay in both catalogs but their assets are deliberately absent.
    reference = {'id': 'film__reference', 'status': 'ready', 'processMode': 'reference_interpretation'}
    (public_root / 'catalog.json').write_bytes(json_bytes({'combinations': current_rows + [reference]}))
    (baseline_root / 'catalog.json').write_bytes(json_bytes({'combinations': old_rows + [reference]}))
    return public_root, baseline_root


def test_sidecar_keeps_original_archives_entries_and_all_current_bytes(sources):
    public_root, baseline_root = sources
    before = {p.relative_to(public_root): digest(p.read_bytes()) for p in public_root.rglob('*') if p.is_file()}
    report = prepare_legacy_v3(public_root=public_root, baseline_root=baseline_root, expected_count=2)
    manifest = json.loads((public_root / 'legacy-v3/manifest.json').read_text())
    assert manifest['schemaVersion'] == 1
    assert manifest['method'] == 'legacy-v3-baseline'
    assert manifest['baselineCatalogSha256'] == digest((baseline_root / 'catalog.json').read_bytes())
    assert {r['id'] for r in manifest['combinations']} == set(IDS)
    assert report['zipEntryCounts'] == {7: 1, 8: 1}
    assert report['sourceVlogAllIdentical'] is True
    for record in manifest['combinations']:
        std, bundle = record['files']['stdLegacy'], record['files']['zipLegacy']
        path = public_root / bundle['path'].lstrip('/')
        assert path.read_bytes() == (baseline_root / record['id'] / bundle['name']).read_bytes()
        assert digest(path.read_bytes()) == bundle['sha256'] == std['transferSha256']
        assert len(path.read_bytes()) == bundle['bytes'] == std['transferBytes']
        assert std['encoding'] == 'zip-entry'
        assert std['downloadName'].endswith('STL.cube')
        assert bundle['downloadName'].endswith('V3.zip')
        with zipfile.ZipFile(path) as archive:
            assert digest(archive.read(std['name'])) == std['sha256']
            assert len(archive.read(std['name'])) == std['bytes']
            assert 'provenance.json' in archive.namelist()
            assert not any(name.endswith('STB.cube') for name in archive.namelist())
        if record['id'].startswith('gfx_'):
            assert record['qa']['stdGeneration'] is None
            assert record['qa']['stdVsContinuousComposition'] is None
    assert {p: digest((public_root / p).read_bytes()) for p in before} == before


def test_repeat_and_verify_only_leave_sidecar_bytes_and_mtimes_unchanged(sources):
    public_root, baseline_root = sources
    args = dict(public_root=public_root, baseline_root=baseline_root, expected_count=2)
    prepare_legacy_v3(**args)
    paths = [p for p in (public_root / 'legacy-v3').rglob('*') if p.is_file()]
    before = {p: (digest(p.read_bytes()), p.stat().st_mtime_ns) for p in paths}
    prepare_legacy_v3(**args)
    report = prepare_legacy_v3(**args, verify_only=True)
    assert report['verifyOnly'] is True
    assert {p: (digest(p.read_bytes()), p.stat().st_mtime_ns) for p in paths} == before


def test_corrupted_original_is_rejected_before_sidecar_publication(sources):
    public_root, baseline_root = sources
    path = next((baseline_root / IDS[0]).glob('*LUTS.zip'))
    path.write_bytes(path.read_bytes() + b'corrupt')
    with pytest.raises(ValueError, match='hash/size mismatch'):
        prepare_legacy_v3(public_root=public_root, baseline_root=baseline_root, expected_count=2)
    assert not (public_root / 'legacy-v3').exists()


def test_different_current_vlog_is_rejected_even_if_its_catalog_hash_matches(sources):
    public_root, baseline_root = sources
    path = public_root / 'catalog.json'
    catalog = json.loads(path.read_text())
    record = next(c for c in catalog['combinations'] if c['id'] == IDS[0])
    asset = record['files']['vlog']
    vlog = public_root / asset['path'].lstrip('/')
    changed = vlog.read_bytes() + b'\n'
    vlog.write_bytes(changed)
    asset.update(bytes=len(changed), sha256=digest(changed))
    path.write_bytes(json_bytes(catalog))
    with pytest.raises(ValueError, match='Current VLOG differs'):
        prepare_legacy_v3(public_root=public_root, baseline_root=baseline_root, expected_count=2)
    assert not (public_root / 'legacy-v3').exists()


def test_existing_sidecar_is_never_silently_overwritten(sources):
    public_root, baseline_root = sources
    args = dict(public_root=public_root, baseline_root=baseline_root, expected_count=2)
    prepare_legacy_v3(**args)
    path = next((public_root / 'legacy-v3' / IDS[0]).glob('*.zip'))
    changed = path.read_bytes() + b'changed'
    path.write_bytes(changed)
    with pytest.raises(ValueError, match='existing legacy'):
        prepare_legacy_v3(**args)
    assert path.read_bytes() == changed
