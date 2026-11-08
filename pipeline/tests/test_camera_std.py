"""The camera adapter is a calibrated input estimate, not a display tone edit."""
import hashlib
import json
import numpy as np
import pytest
from pipeline.camera_std import (
    DEFAULT_CAMERA, METHOD, PUBLIC, ROOT, adapter_table, alchemy_tetrahedral,
    alchemy_trilinear, compose, models, normalize_camera, serialize_std,
)
from pipeline.common import read_cube
from spektrafilm_lut_creator.grid import cube_grid
from spektrafilm_lut_creator.qa.evaluators import apply_tetrahedral, apply_trilinear


def test_adapter_camera_aliases_never_guess_dmc_l10():
    assert normalize_camera('DC-S1M2') == DEFAULT_CAMERA == 'S1II'
    assert normalize_camera('DC-S5M2') == 'S5II'
    assert normalize_camera('DC-L10') == 'DC-L10'
    with pytest.raises(ValueError, match='DMC-L10'):
        normalize_camera('DMC-L10')
    assert len(models()) == 10
    assert next(m for m in models() if m['id'] == 'GH6')['cameraUse'] == 'post-only'
    assert next(m for m in models() if m['id'] == 'S1RII')['validation'] == 'controlled'
    assert next(m for m in models() if m['id'] == 'S1II')['validation'] == 'pending'


def test_composition_axis_order_and_independent_evaluators():
    rng = np.random.default_rng(73)
    table = rng.random((5, 5, 5, 3))
    points = np.concatenate([rng.random((1003, 3)), cube_grid(5), [[-1., .5, 2.]]])
    np.testing.assert_allclose(alchemy_trilinear(table, points), apply_trilinear(table, points), atol=8e-16)
    np.testing.assert_allclose(alchemy_tetrahedral(table, points), apply_tetrahedral(table, points), atol=8e-16)
    identity = cube_grid(5).reshape(5, 5, 5, 3)
    np.testing.assert_allclose(alchemy_tetrahedral(identity, points), np.clip(points, 0., 1.), atol=8e-16)


def test_c200_s1ii_numerical_rows_exactly_match_user_approved_test():
    # Frozen hash of every numeric row in the delivered C2CATSTD.cube test.
    # This catches interpolation order, source replacement, tone edits and
    # serialization changes without relying on a generated expected result.
    path = PUBLIC / 'luts/fujifilm_c200__fujifilm_crystal_archive_typeii/0001VLOG.cube'
    raw = compose(read_cube(path, 'VLOG'), 'S1II', cube_grid(33))
    data = serialize_std(raw, 'S1II', path.name)
    rows = b'\n'.join(data.splitlines()[6:]) + b'\n'
    assert hashlib.sha256(rows).hexdigest() == '48bbac62dc8afec9a1ffe9abd2a982dabaa875767f26523d2f379490bba2751a'
    assert data.splitlines()[1] == b'#LUMIXPHOTOSTYLE STD'
    assert len(rows.splitlines()) == 33**3


def test_all_adapter_sources_have_pinned_hash_and_finite_domain():
    for model in models():
        source = PUBLIC / model['asset']['path'].lstrip('/')
        assert hashlib.sha256(source.read_bytes()).hexdigest() == model['asset']['sha256']
        table = adapter_table(model['id'])
        assert table.shape == (33, 33, 33, 3)
        assert np.isfinite(table).all()
        assert 0. <= table.min() <= table.max() <= 1.


def test_official_production_std_uses_camera_adapter_not_retired_precurve():
    from pipeline.fuji import apply_official
    path = PUBLIC / 'luts/gfx_classic_chrome__official_direct/0200VLOG.cube'
    catalog = json.loads((PUBLIC / 'catalog.json').read_text())
    combo = next((c for c in catalog['combinations'] if c['id'] == 'gfx_classic_chrome__official_direct'), None)
    if combo is None:
        pytest.skip('FUJI official looks are retired from the public catalog')
    path = PUBLIC / combo['files']['vlog']['path'].lstrip('/')
    pixels = np.random.default_rng(31).random((4, 13, 3))
    expected = compose(read_cube(path, 'VLOG'), 'S5II', pixels.reshape(-1, 3)).reshape(pixels.shape)
    actual = apply_official(pixels, 'gfx_classic_chrome', source_vlog_path=path, camera_id='S5II')
    np.testing.assert_array_equal(actual, expected)
