"""Independent behavioral checks for the JPG rendering adapter.

These checks assess continuity, tonal bounds and execution semantics. They do
not establish a measured match to a camera, physical film or photographic print.
"""
import json

import numpy as np
import pytest

from pipeline.common import srgb_decode
from pipeline.research import linear_to_oklab, srgb_encode
from pipeline.jpg import JpgToneProtection


def lightness(encoded):
    return linear_to_oklab(srgb_decode(np.asarray(encoded)))[..., 0]


def identity_render(samples):
    return np.asarray(samples, dtype=float).copy()


def dark_cast_render(samples):
    """Monotone but excessively contrasty display rendering with a colour floor."""
    linear = srgb_decode(samples)
    toned = linear ** 1.65
    return srgb_encode(np.clip(toned * [.86, 1.01, .93] + [.023, .012, .005], 0, 1))


def warm_render(samples):
    linear = srgb_decode(samples)
    return srgb_encode(np.clip(linear ** 1.3 * [1.08, .96, .84] + [.012, .009, .006], 0, 1))


def cool_render(samples):
    linear = srgb_decode(samples)
    return srgb_encode(np.clip(linear ** 1.3 * [.84, .96, 1.08] + [.006, .009, .012], 0, 1))


@pytest.mark.parametrize('digital', [False, True])
def test_identity_renderer_stays_identity_for_neutrals_and_colours(digital):
    points = np.r_[np.random.default_rng(57).random((256, 3)),
                   np.repeat(np.linspace(0, 1, 129)[:, None], 3, axis=1),
                   np.eye(3), 1-np.eye(3)]
    np.testing.assert_allclose(JpgToneProtection(identity_render, digital=digital).apply(points),
                               points, atol=5e-5, rtol=0)


@pytest.mark.parametrize('digital', [False, True])
def test_black_white_are_exact_neutral_endpoints_despite_native_colour_floor(digital):
    protection = JpgToneProtection(dark_cast_render, digital=digital)
    points = np.array([[0., 0., 0.], [1., 1., 1.]])
    np.testing.assert_allclose(protection.apply(points), points, atol=2e-6, rtol=0)


@pytest.mark.parametrize('digital', [False, True])
def test_neutral_ramp_removes_cast_and_retains_increasing_levels(digital):
    levels = np.r_[0., np.geomspace(1e-8, .01, 50), np.linspace(.011, 1, 512)]
    samples = np.repeat(levels[:, None], 3, axis=1)
    output = JpgToneProtection(dark_cast_render, digital=digital).apply(samples)
    assert np.isfinite(output).all()
    assert output.min() >= 0 and output.max() <= 1
    assert np.max(np.ptp(output, axis=-1)) < 2e-5
    assert np.min(np.diff(lightness(output))) > -1e-8
    assert np.min(np.diff(lightness(output)[50:])) > 0
    if digital:
        np.testing.assert_allclose(output, samples, atol=2e-5, rtol=0)


def test_coloured_shadow_lightness_loss_is_bounded_after_gamut_mapping():
    # Test coloured shadows, saturated highlights and ordinary RGB together;
    # matching a middle-gray patch alone missed the earlier colour-dependent loss.
    rays = np.array([[1, .1, .1], [.1, 1, .1], [.1, .1, 1],
                     [0, 1, 1], [1, 0, 1], [1, 1, 0], [.7, .4, .2]])
    points = np.r_[(rays[:, None] * np.geomspace(1e-8, 1, 64)[None, :, None]).reshape(-1, 3),
                   np.random.default_rng(72).random((1024, 3))]
    output = JpgToneProtection(dark_cast_render).apply(points)
    original_l, output_l = lightness(points), lightness(output)
    assert np.isfinite(output).all() and output.min() >= 0 and output.max() <= 1
    # Public behavioral limits: <= .04 OKLab L, tapering to half the distance
    # to either endpoint. This also catches gamut clipping that lifts black.
    assert np.max(np.abs(output_l - original_l)) <= .040003
    assert np.all(output_l >= .5 * original_l - 3e-6)
    assert np.all(output_l <= 1.5 * original_l + 3e-6)
    assert np.all(output_l >= 1.5 * original_l - .5 - 3e-6)
    assert np.all(output_l <= .5 * original_l + .5 + 3e-6)


def test_black_and_white_are_continuous_on_coloured_rays():
    rays = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1], [.3, .7, 1], [1, 1, 1]])
    eps = np.geomspace(1e-12, 1e-5, 30)
    near_black = (rays[:, None] * eps[None, :, None]).reshape(-1, 3)
    near_white = 1-near_black
    protection = JpgToneProtection(dark_cast_render)
    a, b = protection.apply(near_black), protection.apply(near_white)
    assert np.max(a[:30]) < 1e-4
    assert np.min(b[:30]) > 1-1e-4
    assert np.max(np.abs(lightness(a) - lightness(near_black))) < .02
    assert np.max(np.abs(lightness(b) - lightness(near_white))) < 1e-4


def test_precomputed_render_does_not_apply_the_model_twice():
    calls = []
    def observed(points):
        calls.append(np.asarray(points).copy())
        return dark_cast_render(points)
    points = np.random.default_rng(88).random((32, 3))
    native = dark_cast_render(points)
    protection = JpgToneProtection(observed)
    calls.clear()
    precomputed = protection.apply(points, rendered=native)
    # It may evaluate neutral reference points, but must not grade source RGB
    # again or treat already rendered RGB as fresh camera input.
    assert not any(np.array_equal(call, points) for call in calls)
    assert not any(np.array_equal(call, native) for call in calls)
    np.testing.assert_allclose(precomputed, protection.apply(points), atol=1e-12, rtol=0)


def test_processing_is_pixel_local_and_independent_of_other_image_content():
    protection = JpgToneProtection(dark_cast_render)
    points = np.random.default_rng(99).random((64, 3))
    original = points.copy()
    first = protection.apply(points)
    padded = np.r_[np.zeros((16, 3)), points, np.ones((16, 3))]
    np.testing.assert_allclose(protection.apply(padded)[16:-16], first, atol=1e-12, rtol=0)
    np.testing.assert_allclose(np.concatenate([protection.apply(p[None]) for p in points]),
                               first, atol=1e-12, rtol=0)
    np.testing.assert_array_equal(points, original)


def test_different_chromatic_renderers_do_not_collapse_into_one_look():
    points = np.array([[.3, .65, .2], [.65, .2, .15], [.15, .25, .6], [.5, .3, .2]])
    warm = JpgToneProtection(warm_render).apply(points)
    cool = JpgToneProtection(cool_render).apply(points)
    assert np.max(np.abs(warm-cool)) > .015
    assert np.max(np.abs(warm-points)) > .01


def test_metadata_is_serializable_and_does_not_call_or_mutate_rendering():
    protection = JpgToneProtection(dark_cast_render)
    first = protection.metadata()
    assert isinstance(first, dict) and first
    assert first['perImageAdaptation'] is False
    assert first['vlogModified'] is False
    assert first['physicalFilmOrPrintMatch'] is False
    assert first['neutralToneRetention'] == .2
    assert JpgToneProtection(dark_cast_render, digital=True).metadata()['neutralToneRetention'] == 0
    encoded = json.dumps(first, sort_keys=True, allow_nan=False)
    first['injected-test-key'] = True
    assert json.dumps(protection.metadata(), sort_keys=True, allow_nan=False) == encoded


@pytest.mark.parametrize('bad', [[], [[0, 0]], [[0, 0, 0, 0]], [[np.nan, 0, 0]],
                                 [[np.inf, 0, 0]], [[-.1, 0, 0]], [[1.01, 0, 0]]])
def test_invalid_source_pixels_are_rejected(bad):
    with pytest.raises(ValueError):
        JpgToneProtection(identity_render).apply(bad)


def test_real_official_source_and_paper_keep_neutral_tone_monotone():
    # Assemble the untouched source/paper calculation directly, rather than
    # calling a production wrapper that might already apply JPG protection.
    from pipeline.fuji import input_to_flog2, official_table
    from pipeline.fuji_paper import PaperBridge
    from spektrafilm_lut_creator.qa.evaluators import apply_tetrahedral
    paper = PaperBridge('fujifilm_crystal_archive_typeii')
    def raw(points):
        code = input_to_flog2(points)
        official = apply_tetrahedral(official_table('gfx_classic_chrome'), code)
        return srgb_encode(paper.apply(np.clip(official, 0, 1) ** 2.2))
    levels = np.linspace(0, 1, 257)
    gray = np.repeat(levels[:, None], 3, axis=1)
    protected = JpgToneProtection(raw).apply(gray)
    assert np.min(np.diff(lightness(protected))) > 0
    assert np.max(np.ptp(protected, axis=-1)) < 3e-6
    np.testing.assert_allclose(protected[[0, -1]], gray[[0, -1]], atol=2e-6, rtol=0)
