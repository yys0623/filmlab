"""Verify exported-source semantics, A/B bundles and immutable audit backups."""
import json
from pathlib import Path
import shutil
import zipfile

import colour
import numpy as np
import pytest

from pipeline import generate_precurve as generator
from pipeline import std
from pipeline.common import PUBLIC, read_cube, sha256, std_to_vlog
from pipeline.precurve import GENERATION, METHOD_ID
from spektrafilm_lut_creator.grid import cube_grid


COMBO_ID = 'kodak_portra_400__kodak_portra_endura'


def original_record():
    baseline = generator.BASELINE / 'catalog.json'
    catalog = json.loads((baseline if baseline.exists() else PUBLIC / 'catalog.json').read_text())
    return next(c for c in catalog['combinations'] if c['id'] == COMBO_ID), json.loads((PUBLIC / 'samples/manifest.json').read_text())


def test_precurve_source_is_the_serialized_vlog_not_native_engine():
    record, _ = original_record()
    path = PUBLIC / record['files']['vlog']['path'].lstrip('/')
    source = colour.read_LUT(str(path))
    precurve = std.precurve_from_exported_vlog(path)
    points = np.r_[np.random.default_rng(81).random((1024, 3)), [[0., 0., 0.], [1., 1., 1.]]]
    for variant in ['A', 'B']:
        warped = precurve.inverse(precurve.target(points, variant))
        independent = source.apply(std_to_vlog(warped), interpolator=colour.algebra.table_interpolation_tetrahedral)
        np.testing.assert_allclose(precurve.apply(points, variant), independent, atol=2e-14, rtol=0)
    assert precurve.metadata()['source']['sha256'] == sha256(path)
    assert precurve.metadata()['source']['kind'] == 'exported-vlog-cube'
    assert precurve.metadata()['outputColourEdits'] is False


def test_rebuild_preserves_vlog_backs_up_once_and_exports_exact_ab_bundle(tmp_path, monkeypatch):
    record, samples = original_record()
    source_directory = generator.BASELINE / COMBO_ID
    if not source_directory.exists(): source_directory = PUBLIC / 'luts' / COMBO_ID
    local_public = tmp_path / 'public'
    directory = local_public / 'luts' / COMBO_ID
    shutil.copytree(source_directory, directory)
    # One real source image exercises the full preview encoding path.
    sample = next(s for s in samples if s['inputKind'] == 'camera-std')
    sample_path = local_public / sample['path'].lstrip('/')
    sample_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PUBLIC / sample['path'].lstrip('/'), sample_path)
    monkeypatch.setattr(generator, 'PUBLIC', local_public)
    monkeypatch.setattr(std, 'PUBLIC', local_public)
    baseline = tmp_path / 'baseline'
    generator.backup_record(record, baseline=baseline)
    original_std = sha256(baseline / COMBO_ID / record['files']['std']['name'])
    vlog_path = local_public / record['files']['vlog']['path'].lstrip('/')
    vlog_before = vlog_path.read_bytes()
    result = generator.rebuild_standard(record, [sample], backup=False)
    assert vlog_path.read_bytes() == vlog_before
    assert result['qa']['stdGeneration'] == GENERATION
    assert result['qa']['singleTonePrecurve']['method'] == METHOD_ID
    assert 'jpgToneProtection' not in result['qa']
    assert result['stdVariants']['A']['fileKey'] == 'std'
    assert result['stdVariants']['B']['fileKey'] == 'stdB'
    precurve = std.precurve_from_exported_vlog(vlog_path)
    for variant, key in [('A', 'std'), ('B', 'stdB')]:
        path = local_public / result['files'][key]['path'].lstrip('/')
        table = read_cube(path, 'STD')
        np.testing.assert_allclose(table.reshape(-1, 3), precurve.apply(cube_grid(33), variant), atol=5.01e-7, rtol=0)
    with zipfile.ZipFile(local_public / result['files']['zip']['path'].lstrip('/')) as archive:
        for key in ['vlog', 'std', 'stdB', 'qa', 'provenance']:
            asset = result['files'][key]
            assert archive.read(asset['name']) == (local_public / asset['path'].lstrip('/')).read_bytes()
    # Passing a new output to the snapshotter must preserve the first old copy.
    generator.backup_record(result, baseline=baseline)
    assert sha256(baseline / COMBO_ID / record['files']['std']['name']) == original_std
    before_hashes = {key: value['sha256'] for key, value in result['files'].items() if key in ['std', 'stdB', 'vlog']}
    second = generator.rebuild_standard(result, [sample], backup=False)
    assert {key: second['files'][key]['sha256'] for key in before_hashes} == before_hashes


def test_missing_old_backup_is_not_created_from_new_outputs(tmp_path, monkeypatch):
    record, _ = original_record()
    record['qa']['stdGeneration'] = GENERATION
    with pytest.raises(ValueError, match='Cannot create an old-output baseline'):
        generator.backup_record(record, baseline=tmp_path / 'baseline')


def test_production_official_std_requires_exported_source():
    from pipeline.fuji import apply_official
    with pytest.raises(ValueError, match='serialized source_vlog_path'):
        apply_official(np.full((1, 3), .5), 'gfx_provia')


@pytest.mark.parametrize('official', [False, True])
def test_fresh_generators_reproduce_camera_std_without_historical_baseline(tmp_path, monkeypatch, official):
    from pipeline import generate, generate_fuji, camera_std
    from pipeline.common import profiles, save_json
    from pipeline.fuji import load_study
    record, samples = original_record()
    sample = next(s for s in samples if s['inputKind'] == 'camera-std')
    local_public = tmp_path / 'public'
    path = local_public / sample['path'].lstrip('/')
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PUBLIC / sample['path'].lstrip('/'), path)
    save_json(local_public / 'samples/manifest.json', [sample])
    shutil.copytree(PUBLIC / 'camera-adapters', local_public / 'camera-adapters')
    for module in [generator, generate, generate_fuji, std, camera_std]:
        monkeypatch.setattr(module, 'PUBLIC', local_public)
    monkeypatch.setattr(camera_std, 'ADAPTERS', local_public / 'camera-adapters')
    camera_std.models.cache_clear(); camera_std.adapter_table.cache_clear()
    def reject_snapshot(*args, **kwargs):
        raise AssertionError('A fresh camera STD build must not require a historical baseline')
    monkeypatch.setattr(generate, 'backup_record', reject_snapshot)
    monkeypatch.setattr(generate_fuji, 'backup_record', reject_snapshot)
    stocks = profiles()
    if official:
        if not (PUBLIC / 'luts/gfx_classic_chrome__fujifilm_crystal_archive_typeii').exists():
            pytest.skip('FUJI official looks are retired from the public catalog')
        study = load_study()
        look = next(l for l in study['looks'] if l['film'] == 'gfx_classic_chrome')
        paper = next(s for s in stocks if s['id'] == 'fujifilm_crystal_archive_typeii')
        build = lambda: generate_fuji.generate_look(study, look, paper, 202, [sample], force=True)
        expected_id = 'gfx_classic_chrome__fujifilm_crystal_archive_typeii'
    else:
        film = next(s for s in stocks if s['id'] == 'kodak_portra_400')
        paper = next(s for s in stocks if s['id'] == 'kodak_portra_endura')
        build = lambda: generate.generate_one((film, paper, 86, True))
        expected_id = COMBO_ID
    first = build()
    assert first['status'] == 'ready', first.get('reason')
    assert first['qa']['stdGeneration'] == camera_std.METHOD
    second = build()
    assert second['status'] == 'ready', second.get('reason')
    assert len(first['stdByCamera']) == 10
    assert 'stdB' not in first['files']
    for key in ['vlog', 'std']:
        assert first['files'][key]['sha256'] == second['files'][key]['sha256']
        actual = local_public / second['files'][key]['path'].lstrip('/')
        exported = PUBLIC / 'luts' / expected_id / actual.name
        assert sha256(actual) == sha256(exported)
