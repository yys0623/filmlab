"""Digital-negative semantics, topology and deterministic LUT limitations."""
from dataclasses import replace

import numpy as np
import pytest

from pipeline.common import CONFIG, profiles, std_to_vlog
from pipeline.digital import (
    DIGITAL_METHOD_ID, GRAY_ANCHOR, INIT_PRINT_PROFILE,
    DigitalScanBundleBuilder, DigitalScanPipeline, _params,
    digital_settings, run_digital_reference,
)
from spektrafilm_lut_creator.bundles import BundleSpec
from spektrafilm_lut_creator.color_spaces import encode_cctf
from spektrafilm_lut_creator.qa.evaluators import apply_tetrahedral

NEGATIVES = [s['id'] for s in profiles() if s['stage'] == 'filming' and s['type'] == 'negative']


def spec_for(film='kodak_portra_400', **kwargs):
    return BundleSpec(film_profile=film, print_profiles=(INIT_PRINT_PROFILE,),
                      input_color_space='vlog', output_color_space='srgb',
                      topology='1lut', resolution=33, stops_above_midgray=None,
                      output_gamut_compress=CONFIG['output_gamut_compress'], **kwargs)


@pytest.mark.parametrize('film', NEGATIVES)
def test_negative_output_is_positive_finite_and_gray_anchored(film):
    spec = spec_for(film)
    # Include dark-to-bright scene-linear exposure and fully saturated sRGB.
    ramp_linear = np.geomspace(1e-5, 10.0, 129)
    ramp = encode_cctf(np.repeat(ramp_linear[:, None], 3, axis=1), spec.input_color_space)
    colors = std_to_vlog(np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1],
                                  [1, 1, 0], [1, 0, 1], [0, 1, 1]]))
    gray = encode_cctf(np.full((1, 3), GRAY_ANCHOR), spec.input_color_space)
    output = run_digital_reference(spec, np.concatenate([ramp, colors, gray]))
    assert np.isfinite(output).all()
    assert output.min() >= 0 and output.max() <= 1
    luminance = output[:129] @ [.2126, .7152, .0722]
    assert luminance[-1] - luminance[0] > .6
    # Profile/toe interpolation has a measured <0.019/255 downward wiggle at
    # ~0.0004 linear exposure. Reject a reversal above a tenth of an 8-bit
    # code value, without silently flattening or refitting stock curves.
    assert np.min(np.diff(luminance)) > -0.1 / 255
    expected_gray = encode_cctf(np.full(3, GRAY_ANCHOR), spec.output_color_space)
    np.testing.assert_allclose(output[-1], expected_gray, atol=5e-4, rtol=0)


def test_paper_independence_and_no_print_nodes(monkeypatch):
    from spektrafilm.runtime.stages import PrintingStage

    def forbidden(*args, **kwargs):
        raise AssertionError('Paper stage executed in digital mode')

    monkeypatch.setattr(PrintingStage, 'expose', forbidden)
    monkeypatch.setattr(PrintingStage, 'develop', forbidden)
    samples = std_to_vlog(np.random.default_rng(118).random((512, 3)))
    for film in ['kodak_portra_400', 'fujifilm_c200']:
        spec = spec_for(film)
        default = run_digital_reference(spec, samples)
        alternate = run_digital_reference(spec, samples, 'fujifilm_crystal_archive_typeii')
        np.testing.assert_array_equal(default, alternate)
        pipeline = DigitalScanPipeline(_params(spec, INIT_PRINT_PROFILE))
        labels = [node.label for node in pipeline._topology]
        assert labels == ['preprocess', 'filming.expose', 'filming.develop', 'scanning.digital_negative']
        np.testing.assert_allclose(pipeline.optical_density(np.zeros((1, 1, 3))), 0, atol=1e-14)
        assert pipeline.conversion_snapshot()['method'] == DIGITAL_METHOD_ID


def test_no_image_dependent_adjustment_or_film_aliasing():
    samples = std_to_vlog(np.random.default_rng(20261102).random((64, 3)))
    first = run_digital_reference(spec_for(), samples)
    padded = np.concatenate([samples, np.zeros((32, 3)), np.ones((32, 3))])
    np.testing.assert_allclose(first, run_digital_reference(spec_for(), padded)[:64], atol=1e-12, rtol=0)
    outputs = [run_digital_reference(spec_for(film), samples) for film in NEGATIVES]
    # A shared conversion must still use every distinct stock's film data.
    assert len({array.tobytes() for array in outputs}) == len(NEGATIVES)
    settings = digital_settings()
    assert settings['commonGamma'] == .60
    assert settings['perFilmSlopeFit'] is False and settings['perFilmColorMatrixFit'] is False


def test_builder_metadata_and_offgrid_fidelity():
    spec = spec_for()
    bundle = DigitalScanBundleBuilder(spec).build()
    assert bundle.meta.name == 'kodak_portra_400__digital_scan'
    assert bundle.meta.stocks.prints == ()
    assert bundle.luts[0][0] == 'digital_scan.cube'
    assert all(lut.print_profile is None for lut in bundle.meta.luts)
    snapshot = bundle.meta.params_snapshot['digital_scan']
    assert snapshot['print_profile'] is None and snapshot['scan_film'] is True
    assert snapshot['digital_conversion']['physicalScannerCalibrated'] is False
    samples = std_to_vlog(np.random.default_rng(883).random((2048, 3)))
    error = np.max(np.abs(apply_tetrahedral(bundle.luts[0][1].table, samples)
                          - run_digital_reference(spec, samples)), axis=1)
    assert np.quantile(error, .99) < .025
    assert error.max() < .06


def test_invalid_stock_topology_and_output_are_rejected():
    with pytest.raises(ValueError, match='negative film'):
        run_digital_reference(spec_for('fujifilm_provia_100f'), np.zeros((1, 3)))
    with pytest.raises(ValueError, match='1lut'):
        DigitalScanBundleBuilder(replace(spec_for(), topology='2lut')).build()
    with pytest.raises(ValueError, match='sRGB output'):
        run_digital_reference(replace(spec_for(), output_color_space='ACEScg'), np.zeros((1, 3)))
