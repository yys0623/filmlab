"""Colour contracts and export fidelity for the editorial reference mode."""
import copy
import json

import colour
import numpy as np
import pytest

from pipeline.common import ROOT, read_cube, vlog_encode
from pipeline.research import (apply_reference_std, apply_reference_vlog, circular_weight,
    bound_oklab_to_linear_srgb, linear_to_oklab, oklab_to_linear, srgb_encode,
    validate_parameters, vlog_to_display_srgb)
from spektrafilm_lut_creator.formats import Lut
from spektrafilm_lut_creator.formats.lumix import LumixCubeFormat
from spektrafilm_lut_creator.grid import cube_grid
from spektrafilm_lut_creator.qa.evaluators import apply_tetrahedral


def configured_looks():
    return json.loads((ROOT / 'pipeline/config/reference-looks.json').read_text())['looks']


def identity_parameters():
    return {'tone': {'x': [0, .25, .5, .75, 1], 'y': [0, .25, .5, .75, 1]},
            'saturation': 1, 'hueBands': [], 'shadowTint': [0, 0], 'highlightTint': [0, 0]}


def test_oklab_matrices_match_independent_colour_science():
    linear = np.random.default_rng(176).random((1024, 3))
    independent = colour.XYZ_to_Oklab(colour.RGB_to_XYZ(linear, 'sRGB'))
    # Published sRGB matrix roundings differ slightly between colour and the
    # original OKLab direct-sRGB matrices. This detects swapped axes/signs.
    np.testing.assert_allclose(linear_to_oklab(linear), independent, atol=1.5e-4, rtol=0)
    np.testing.assert_allclose(oklab_to_linear(linear_to_oklab(linear)), linear, atol=2e-14, rtol=0)


def test_rgb_boundary_mapping_leaves_in_gamut_colours_unchanged():
    rgb = np.random.default_rng(179).random((2048, 3))
    np.testing.assert_allclose(bound_oklab_to_linear_srgb(linear_to_oklab(rgb)), rgb, atol=2e-14)
    # Out-of-gamut output is bounded, with no exact hue/lightness claim.
    outside = np.array([[-.1, .3, 1.2], [1.2, 1.1, -.2]])
    actual = bound_oklab_to_linear_srgb(linear_to_oklab(outside))
    np.testing.assert_allclose(actual, np.clip(outside, 0, 1), atol=2e-14)
    assert np.isfinite(actual).all()


def test_hue_weights_are_periodic_and_neutrals_resist_tint():
    angles = np.array([-.001, 0, .001])
    np.testing.assert_allclose(circular_weight(angles, 359, 24),
                               circular_weight(angles+2*np.pi, 359, 24), atol=1e-15)
    parameters = identity_parameters()
    parameters.update(shadowTint=[.02, -.02], highlightTint=[-.02, .02])
    ramp = np.repeat(np.linspace(0, 1, 1025)[:, None], 3, axis=1)
    output = apply_reference_std(ramp, parameters)
    np.testing.assert_allclose(output, ramp, atol=2e-7, rtol=0)


@pytest.mark.parametrize('look', configured_looks(), ids=lambda look: look['film'])
def test_all_looks_have_monotonic_neutral_tone_and_valid_colours(look):
    parameters = look['parameters']
    ramp = np.repeat(np.linspace(0, 1, 2049)[:, None], 3, axis=1)
    neutral = apply_reference_std(ramp, parameters)
    np.testing.assert_allclose(neutral[[0, -1]], [[0, 0, 0], [1, 1, 1]], atol=2e-7)
    assert np.max(np.ptp(neutral, axis=1)) < 2e-7
    assert np.diff(neutral[:, 0]).min() >= -1e-9
    points = np.concatenate([cube_grid(9), np.random.default_rng(177).random((4096, 3))])
    for transform in [apply_reference_std, apply_reference_vlog]:
        output = transform(points, parameters)
        assert output.shape == points.shape
        assert np.isfinite(output).all() and output.min() >= 0 and output.max() <= 1
        np.testing.assert_array_equal(output, transform(points, parameters))


def test_vlog_base_keeps_midgray_and_has_smooth_hdr_shoulder():
    gray = np.repeat(np.array([0, .184, .5, .75, 1, 10, 40])[:, None], 3, axis=1)
    output = vlog_to_display_srgb(vlog_encode(gray))
    expected = colour.models.eotf_inverse_sRGB(gray[:4])
    np.testing.assert_allclose(output[:4], expected, atol=3e-7, rtol=0)
    assert np.diff(output[:, 0]).min() > 0
    assert np.max(output) < 1
    # Matrix whitepoint and shared shoulder must never add a neutral cast.
    assert np.ptp(output, axis=1).max() < 2e-7


@pytest.mark.parametrize('look', configured_looks(), ids=lambda look: look['film'])
def test_written_std_cube_matches_continuous_grade(tmp_path, look):
    table = apply_reference_std(cube_grid(33), look['parameters']).reshape(33, 33, 33, 3)
    path = tmp_path / 'TESTSTD.cube'
    LumixCubeFormat().write(Lut(table, title='reference-test'), path, photo_style_tag='STD')
    points = np.random.default_rng(178).random((2048, 3))
    expected = apply_reference_std(points, look['parameters'])
    actual = apply_tetrahedral(read_cube(path, 'STD'), points)
    error = np.max(np.abs(actual-expected), axis=1)
    # Bounded display RGB removes the steep fixed-L/hue gamut-boundary
    # compression. Keep explicit off-grid bounds, including saturated edges.
    assert np.quantile(error, .99) < .012
    assert error.max() < .04
    # Independent .cube reader catches any axis/order mismatch.
    external = colour.read_LUT(str(path)).apply(points, interpolator=colour.algebra.table_interpolation_tetrahedral)
    np.testing.assert_allclose(actual, external, atol=1e-12, rtol=0)


def test_invalid_parameters_fail_instead_of_silently_reversing_tone():
    parameters = identity_parameters()
    bad = copy.deepcopy(parameters); bad['tone']['y'][2] = .1
    with pytest.raises(ValueError, match='strictly increasing'):
        validate_parameters(bad)
    bad = copy.deepcopy(parameters); bad['tone']['y'][0] = .05
    with pytest.raises(ValueError, match='black and white'):
        validate_parameters(bad)
    bad = copy.deepcopy(parameters); bad['shadowTint'] = [float('nan'), 0]
    with pytest.raises(ValueError, match='Tint'):
        validate_parameters(bad)
    with pytest.raises(ValueError, match='finite'):
        apply_reference_std([[float('nan'), .5, .5]], parameters)
