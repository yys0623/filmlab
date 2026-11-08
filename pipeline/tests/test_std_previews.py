"""Catch wrong-LUT, double-transform, stale-image, and sample provenance errors."""
import io
import json

import colour
import numpy as np
import pytest
from PIL import Image, ImageCms

from pipeline.common import PUBLIC, ROOT, sha256


def test_camera_samples_are_verified_lut_off_and_color_unchanged():
    manifest = json.loads((PUBLIC / 'samples/manifest.json').read_text())
    cameras = [sample for sample in manifest if sample['inputKind'] == 'camera-std']
    assert len(cameras) == 13
    for sample in cameras:
        meta = sample['cameraMetadata']
        assert meta['Model'] == 'DC-S1M2'
        assert meta['PhotoStyle'] == 'Standard or Custom'
        assert meta['LUT1Opacity'] == meta['LUT2Opacity'] == 0
        assert meta['ColorSpace'] == 'sRGB'
        source = PUBLIC / sample['path'].lstrip('/')
        assert sha256(source) == sample['preparedSha256']
        assert source.read_bytes() == (ROOT / 'assets/samples' / source.name).read_bytes()
        with Image.open(source) as image:
            assert image.info.get('icc_profile')
            assert not image.getexif()
        assert sample['previewLut'] == 'std'


@pytest.mark.parametrize('combo_id', [
    'kodak_portra_400__kodak_portra_endura',
    'fujifilm_c200__fujifilm_crystal_archive_typeii',
    'fujifilm_velvia_100__direct_scan',
    'kodak_portra_400__digital_scan',
    'fujifilm_c200__digital_scan',
    'fujifilm_c200__fujifilm_crystal_archive_typeii__filmcast',
    'kodak_gold_200__kodak_portra_endura__filmcast',
])
@pytest.mark.parametrize('sample_id', [sample['id'] for sample in json.loads((PUBLIC / 'samples/manifest.json').read_text()) if sample['inputKind'] == 'camera-std'])
def test_preview_matches_independently_read_exported_std_cube(combo_id, sample_id):
    catalog = json.loads((PUBLIC / 'catalog.json').read_text())
    combo = next(c for c in catalog['combinations'] if c['id'] == combo_id)
    sample = next(s for s in catalog['samples'] if s['id'] == sample_id)
    source = np.asarray(Image.open(PUBLIC / sample['path'].lstrip('/')), dtype=float).reshape(-1, 3) / 255
    source = source[np.random.default_rng(17).choice(len(source), 4096, replace=False)]
    assert combo['previewMode'] == 'runtime-std'
    assert combo['previews'] == {}
    assert combo['stdByCamera']['S1II']['std'] == combo['files']['std']
    # Independent colour-science cube parser and tetrahedral interpolation;
    # browser uses this same exported cube once, not a second input adapter.
    path = PUBLIC / combo['files']['std']['path'].lstrip('/')
    lut = colour.read_LUT(str(path))
    independent = lut.apply(source, interpolator=colour.algebra.table_interpolation_tetrahedral)
    from pipeline.common import read_cube
    from spektrafilm_lut_creator.qa.evaluators import apply_tetrahedral
    evaluated = apply_tetrahedral(read_cube(path, 'STD'), source)
    np.testing.assert_allclose(evaluated, independent, atol=3e-15, rtol=0)


def test_every_film_paper_choice_has_current_runtime_preview():
    catalog = json.loads((PUBLIC / 'catalog.json').read_text())
    ready = [combo for combo in catalog['combinations'] if combo['status'] == 'ready']
    # 148 engine looks plus one recommended-development variant per negative print.
    # The retired FUJI official looks are no longer in the catalog.
    base = [combo for combo in ready if not combo.get('castBaseId')]
    cast = [combo for combo in ready if combo.get('castBaseId')]
    assert len(base) == 148
    assert len(cast) == 128
    assert len(ready) == 276
    assert not any(combo['processMode'].startswith('official_') for combo in ready)
    assert not any(combo['processMode'] == 'reference_interpretation' for combo in ready)
    for combo in ready:
        assert combo['stdMethod'] == 'camera-vlog-alchemy-v1'
        assert combo['previewMode'] == 'runtime-std'
        assert combo['previews'] == {}
        assert len(combo['stdByCamera']) == 10
