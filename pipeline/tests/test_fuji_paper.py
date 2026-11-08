"""Paper-only bridge semantics, measured anchors, and context independence."""
import json

import numpy as np
import pytest

from pipeline.common import profiles
from pipeline.fuji_paper import (
    GRAY_ANCHOR, METHOD_ID, NEUTRAL_SAMPLES, STAGE_NAMES, PaperBridge,
)
from pipeline.common import srgb_decode
from pipeline.research import srgb_encode
from scipy.interpolate import PchipInterpolator
from scipy.optimize import brentq
from spektrafilm.model.develop import develop_print_morph
from spektrafilm.runtime.topology import Tap


PAPERS = [s['id'] for s in profiles() if s['stage'] == 'printing']


def assert_only_print_develop_and_scan_ran(bridge):
    timings = bridge._pipeline.get_timings()
    # The scanner also reports its internal spectral service; it is not a
    # separate topology node and does not indicate LUT interpolation is on.
    assert set(timings) == {*STAGE_NAMES, 'SpectralLUTService.spectral_compute_scanner'}
    assert [name for name in timings if name in STAGE_NAMES] == list(STAGE_NAMES)


@pytest.fixture(scope='module')
def bridges():
    return {paper: PaperBridge(paper) for paper in PAPERS}


@pytest.mark.parametrize('paper', PAPERS)
def test_all_print_stocks_calibrate_gray_and_keep_positive_neutral_ramp(bridges, paper):
    bridge = bridges[paper]
    gray = bridge.apply(np.full(3, GRAY_ANCHOR))
    np.testing.assert_allclose(gray, GRAY_ANCHOR, atol=1e-7, rtol=0)
    levels = np.concatenate([[0.], np.geomspace(1e-6, 1., 1024)])
    ramp = bridge.apply(np.repeat(levels[:, None], 3, axis=1))
    assert np.isfinite(ramp).all()
    assert 0 <= ramp.min() <= ramp.max() <= 1
    # Retain the paper's attainable black/white and gray-axis casts. Do not
    # normalize them away or allow a new shadow plateau after calibration.
    luminance = ramp @ [.2126, .7152, .0722]
    assert np.min(np.diff(luminance)) > -1e-5
    assert luminance[-1] - luminance[0] > .5
    assert luminance[-1] < .9
    assert_only_print_develop_and_scan_ran(bridge)


@pytest.mark.parametrize('paper', PAPERS)
def test_completed_display_shadows_retain_separation_after_printing(bridges, paper):
    # Behavioral regression: the original shared .60 slope mapped 64/255 to
    # 24..40/255 and 32/255 to 1..17/255. It doubled the existing image contrast.
    # The calibrated printer must preserve meaningful shadow differences in
    # every stock, without demanding identical stock color or endpoints.
    encoded = np.array([0., .1, .125, .25, .375, .5, .75, 1.])
    rgb = np.repeat(srgb_decode(encoded)[:, None], 3, axis=1)
    result = bridges[paper].apply(rgb)
    shown = srgb_encode(result) @ [.2126, .7152, .0722]
    assert shown[1] > .09
    assert .115 < shown[2] < .18
    assert .24 < shown[3] < .30
    assert shown[3] - shown[1] > .12
    assert .48 < shown[5] < .52
    assert np.all(np.diff(shown) > 0)
    # White is a stock limit; the correction must not simply renormalize every
    # stock to display black/white or blend the paper effect back into input.
    assert .75 < shown[-1] < .9


def test_bridge_skips_film_and_optical_enlarger_nodes(monkeypatch):
    from spektrafilm.runtime.stages import FilmingStage, PrintingStage

    def forbidden(*args, **kwargs):
        raise AssertionError('A film or enlarger exposure node executed')

    monkeypatch.setattr(FilmingStage, 'expose', forbidden)
    monkeypatch.setattr(FilmingStage, 'develop', forbidden)
    monkeypatch.setattr(PrintingStage, 'expose', forbidden)
    samples = np.random.default_rng(55).random((16, 3))
    first = PaperBridge('kodak_portra_endura', init_film='kodak_portra_400')
    second = PaperBridge('kodak_portra_endura', init_film='fujifilm_c200')
    np.testing.assert_array_equal(first.apply(samples), second.apply(samples))
    np.testing.assert_array_equal(first.offset, second.offset)
    assert_only_print_develop_and_scan_ran(first)


def test_bridge_is_pixel_local_and_preserves_array_shape(bridges):
    bridge = bridges['fujifilm_crystal_archive_typeii']
    samples = np.random.default_rng(55).random((7, 11, 3))
    original = samples.copy()
    result = bridge.apply(samples)
    flat = bridge.apply(samples.reshape(-1, 3))
    np.testing.assert_array_equal(result.reshape(-1, 3), flat)
    np.testing.assert_array_equal(samples, original)
    np.testing.assert_allclose(bridge.apply(samples[2, 5]), result[2, 5], atol=1e-14, rtol=0)
    padded = np.concatenate([samples.reshape(-1, 3), np.zeros((13, 3)), np.ones((4, 3))])
    np.testing.assert_array_equal(flat, bridge.apply(padded)[:len(flat)])


def test_calibrated_exposure_matches_independent_inverse_and_original_development(bridges):
    bridge = bridges['kodak_endura_premier']
    inputs = np.array([[.02, .4, .7], [.01, .184, .85]])
    pipeline = bridge._pipeline
    info = bridge.metadata()['neutralCalibration']
    # Independently solve the requested neutral luminance directly against
    # the spectral pipeline. Do not use the production inverse lookup table.
    target = PchipInterpolator([0, .184, 1], info['targetOutputLinearY'])(inputs)
    def luminance(delta):
        return float(bridge._from_log_exposure(bridge.offset + delta) @ [.2126, .7152, .0722])
    low, high = info['deltaLogExposureRange']
    deltas = np.array([brentq(lambda d: luminance(d) - y, low, high, xtol=1e-13)
                       for y in target.flat]).reshape(inputs.shape)
    exposures = bridge.offset + deltas
    expected_density = develop_print_morph(
        exposures[None, ...], pipeline.print.data.log_exposure,
        pipeline.print.data.density_curves_model,
        pipeline.print_render.density_curves_morph,
        profile_type=pipeline.print.info.type,
    )
    actual_density = pipeline.process(exposures[None, ...], inject=Tap.LOG_E_PRINT, collect=Tap.CMY_PRINT)
    np.testing.assert_array_equal(actual_density, expected_density)
    expected_output = pipeline.process(expected_density, inject=Tap.CMY_PRINT)
    np.testing.assert_allclose(bridge.apply(inputs), np.clip(expected_output[0], 0, 1), atol=2e-7, rtol=0)
    assert not pipeline.print_render.density_curves_morph.active
    assert not pipeline.scanner.white_correction
    assert not pipeline.scanner.black_correction


def test_common_mapping_keeps_distinct_print_stock_responses(bridges):
    colors = np.random.default_rng(66).random((64, 3))
    assert len({bridge.apply(colors).tobytes() for bridge in bridges.values()}) == len(PAPERS)
    for bridge in bridges.values():
        info = bridge.metadata()
        calibration = info['neutralCalibration']
        assert calibration['baseSampleCount'] == NEUTRAL_SAMPLES == 4097
        assert calibration['sampleCount'] >= NEUTRAL_SAMPLES
        assert calibration['targetInputLinearRGB'] == [0., GRAY_ANCHOR, 1.]
        assert calibration['attainableBlackLinearY'] < GRAY_ANCHOR
        assert calibration['attainableWhiteLinearY'] > GRAY_ANCHOR
        assert 'commonSlope' not in info
        assert info['grayLinearAnchor'] == GRAY_ANCHOR
        assert info['method'] == METHOD_ID
        assert info['physicalPrinterCalibrated'] is False
        assert info['fujifilmOfficialPaperTransform'] is False
        assert info['runtimeInitFilmApplied'] is False
        assert info['upstreamFilmStagesApplied'] is False
        assert info['upstreamOpticalEnlargerApplied'] is False
        assert info['perSimulationCalibration'] is False
        assert info['perImageCalibration'] is False
        assert info['calibrationMaxAbsLinearRGBError'] < 1e-7
        json.dumps(info, allow_nan=False)
        # Metadata callers cannot mutate the calibrated state or endpoint data.
        info['offset'][0] = 100
        info['linearEndpointOutputs']['white'][0] = 100
        assert bridge.metadata()['offset'][0] != 100
        assert bridge.metadata()['linearEndpointOutputs']['white'][0] != 100


@pytest.mark.parametrize('bad', [
    [], [1, 2], 1, [[0, 0, 0, 0]], [[np.nan, 0, 0]],
    [[np.inf, 0, 0]], [[-.01, 0, 0]], [[1.01, 0, 0]], [['x', 0, 0]],
])
def test_reject_invalid_input(bridges, bad):
    with pytest.raises(ValueError):
        bridges['kodak_portra_endura'].apply(bad)
