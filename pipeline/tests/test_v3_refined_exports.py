"""A refinement may change only its separate output, after reproducing v3."""
import io
import json
import zipfile

import colour
import numpy as np
import pytest

from pipeline import generate_v3_refined as generator
from pipeline.jpg import JpgToneProtection
from pipeline.jpg_refined import RefinedJpgToneProtection
from pipeline.prepare_legacy_v3 import digest, json_bytes
from pipeline.tests.test_legacy_v3 import sources
from spektrafilm_lut_creator.formats import Lut
from spektrafilm_lut_creator.formats.lumix import LumixCubeFormat
from spektrafilm_lut_creator.grid import cube_grid


def raw_model(values):
    return np.clip(np.asarray(values) * 1.2 - .07, 0., 1.)


@pytest.fixture
def render_sources(sources, monkeypatch):
    public_root, baseline_root = sources
    path = baseline_root / 'catalog.json'
    catalog = json.loads(path.read_text())
    for record in catalog['combinations']:
        if record['processMode'] == 'reference_interpretation': continue
        record['film'] = record['id'].split('__')[0]
        record['paper'] = 'kodak_portra_endura' if record['processMode'] == 'negative_print' else None
        directory = baseline_root / record['id']
        table = JpgToneProtection(raw_model).apply(cube_grid(33)).reshape(33, 33, 33, 3)
        std_path = directory / record['files']['std']['name']
        LumixCubeFormat().write(Lut(table, title='fixture_STD'), std_path, photo_style_tag='STD')
        record['files']['std'].update(bytes=std_path.stat().st_size, sha256=digest(std_path.read_bytes()))
        zip_path = directory / record['files']['zip']['name']
        with zipfile.ZipFile(zip_path) as archive:
            entries = {name: archive.read(name) for name in archive.namelist()}
        entries[std_path.name] = std_path.read_bytes()
        archive_bytes = generator.deterministic_zip(entries)
        zip_path.write_bytes(archive_bytes)
        record['files']['zip'].update(bytes=len(archive_bytes), sha256=digest(archive_bytes))
        hashes = {name: digest(raw) for name, raw in entries.items()}
        hashes[zip_path.name] = digest(archive_bytes)
        (directory / 'baseline-manifest.json').write_bytes(json_bytes({'sha256': hashes}))
    path.write_bytes(json_bytes(catalog))
    monkeypatch.setattr(generator, 'EXPECTED_COMBINATIONS', 2)
    monkeypatch.setattr(generator, 'make_renderer', lambda *_: raw_model)
    return public_root, baseline_root


def snapshot(directory):
    return {p.relative_to(directory): digest(p.read_bytes()) for p in directory.rglob('*') if p.is_file()}


def test_exports_reproduce_baseline_and_preserve_all_sources(render_sources):
    public_root, baseline_root = render_sources
    before, baseline_before = snapshot(public_root), snapshot(baseline_root)
    args = dict(public_root=public_root, baseline_root=baseline_root, jobs=1)
    report = generator.generate(**args)
    assert report['combinations'] == report['generated'] == 2
    assert report['reconstructionNodeMaxError'] < 5.01e-7
    manifest = json.loads((public_root / 'refined-v3/manifest.json').read_text())
    assert manifest['method'] == generator.METHOD and manifest['knee'] == .9
    for record in manifest['combinations']:
        std, bundle = record['files']['stdRefined'], record['files']['zipRefined']
        archive_bytes = (public_root / bundle['path'].lstrip('/')).read_bytes()
        assert digest(archive_bytes) == std['transferSha256'] == bundle['sha256']
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            assert archive.testzip() is None
            assert len(archive.namelist()) == (8 if record['id'].startswith('gfx_') else 7)
            assert json.loads(archive.read('qa.json')) == record['qa']
            assert digest(archive.read(std['name'])) == std['sha256']
            assert '#LUMIXPHOTOSTYLE STD' in archive.read(std['name']).decode().splitlines()[:3]
            old_dir = baseline_root / record['id']
            for name in ['SPEKTRAFILM_LICENSE.txt', *(['FUJIFILM_NOTICE.txt'] if record['id'].startswith('gfx_') else [])]:
                assert archive.read(name) == (old_dir / name).read_bytes()
            vlog_name = next(name for name in archive.namelist() if name.endswith('VLOG.cube'))
            assert digest(archive.read(vlog_name)) == record['sourceVlogSha256']
            # Read the actual exported file with a separate parser/interpolator.
            extracted = public_root / std['name']
            extracted.write_bytes(archive.read(std['name']))
            independent = colour.read_LUT(str(extracted))
            independent_nodes = independent.apply(cube_grid(33), interpolator=colour.algebra.table_interpolation_tetrahedral)
            exact = RefinedJpgToneProtection(raw_model).apply(cube_grid(33))
            np.testing.assert_allclose(independent_nodes, exact, rtol=0, atol=5.01e-7)
            extracted.unlink()
    assert {p: digest((public_root / p).read_bytes()) for p in before} == before
    assert snapshot(baseline_root) == baseline_before
    output_before = snapshot(public_root / 'refined-v3')
    assert generator.generate(**args)['generated'] == 0
    assert snapshot(public_root / 'refined-v3') == output_before
    # A true rebuild is deterministic as well, not just a cache hit.
    old = json.loads((baseline_root / 'catalog.json').read_text())['combinations'][0]
    current = json.loads((public_root / 'catalog.json').read_text())['combinations'][0]
    generator.build_one(old, current, public_root=public_root, baseline_root=baseline_root)
    assert snapshot(public_root / 'refined-v3') == output_before


def test_reconstruction_mismatch_aborts_before_refined_publication(render_sources, monkeypatch):
    public_root, baseline_root = render_sources
    monkeypatch.setattr(generator, 'make_renderer', lambda *_: lambda values: np.asarray(values))
    with pytest.raises(ValueError, match='Historical 33-grid reconstruction differs'):
        generator.generate(public_root=public_root, baseline_root=baseline_root, jobs=1)
    assert not (public_root / 'refined-v3').exists()


def test_shared_renderer_calibrates_the_neutral_response_once():
    cached = generator.CachedRenderer(raw_model)
    old = JpgToneProtection(cached)
    refined = RefinedJpgToneProtection(cached)
    assert cached.evaluations == 1
    np.testing.assert_array_equal(old.neutral_lab, refined.neutral_lab)
    points = cube_grid(5)
    old.apply(points); refined.apply(points)
    assert cached.evaluations == 2


@pytest.mark.parametrize('mode,slide,digital', [
    ('negative_print', False, False), ('positive_direct', True, False), ('negative_digital', False, True),
])
def test_native_renderer_selects_original_process_path(monkeypatch, mode, slide, digital):
    called = []
    def evaluate(spec, bundle, values, **kwargs):
        called.append((spec, kwargs)); return values
    monkeypatch.setattr(generator, 'run_std_native', evaluate)
    record = {'film': 'kodak_portra_400', 'paper': 'kodak_portra_endura' if mode == 'negative_print' else None,
              'processMode': mode}
    render = generator.make_renderer(record, {'config': generator.CONFIG})
    render(np.zeros((1, 3)))
    assert called[0][1] == {'is_slide': slide, 'is_digital': digital}
    assert called[0][0].input_color_space == 'Panasonic V-Log'


@pytest.mark.parametrize('mode', ['official_direct', 'official_print'])
def test_official_renderer_uses_original_std_adapter_and_optional_paper(monkeypatch, mode):
    from pipeline import fuji
    called, paper = [], object()
    monkeypatch.setattr(generator, '_paper_bridge', lambda _: paper)
    monkeypatch.setattr(fuji, 'apply_official_native', lambda *args: called.append(args) or args[0])
    record = {'film': 'gfx_classic_chrome', 'paper': 'fujifilm_crystal_archive_typeii' if mode == 'official_print' else None,
              'processMode': mode}
    generator.make_renderer(record, {})(np.zeros((1, 3)))
    assert called[0][1:] == (record['film'], 'std', paper if mode == 'official_print' else None)
