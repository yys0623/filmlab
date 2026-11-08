"""Independent spectral integration of the declared Film Lab digital model.

This checks implementation of an explicit model, not measured scanner or film
fidelity. It deliberately does not call production digital conversion helpers.
"""
import colour
import numpy as np
import pytest

from pipeline.common import CONFIG
from pipeline.digital import run_digital_reference
from spektrafilm.runtime.params_builder import digest_params, init_params
from spektrafilm.runtime.pipeline import SimulationPipeline
from spektrafilm.utils.gamut_compression import compress_rgb
from spektrafilm_lut_creator.bundles import BundleSpec


def independent_spectral_positive(spec, encoded_vlog):
    params = init_params(spec.film_profile, 'fujifilm_crystal_archive_typeii')
    params.debug.lut_mode = True
    params.io.scan_film = True
    params.settings.neutral_print_filters_from_database = False
    params.io.input_color_space = 'V-Gamut'
    params.io.output_color_space = 'sRGB'
    params.io.input_cctf_decoding = False
    params.io.output_cctf_encoding = False
    params.io.input_gamut_compress = spec.input_gamut_compress
    params.io.output_gamut_compress = spec.output_gamut_compress
    engine = SimulationPipeline(digest_params(params))
    assert engine.film.info.stock == spec.film_profile

    encoded_vlog = np.asarray(encoded_vlog, dtype=np.float32)
    linear = colour.models.log_decoding_VLog(encoded_vlog).astype(np.float32)
    cmy = engine.process(linear.reshape(1, -1, 3), collect='cmy_film').reshape(-1, 3)
    assert {'preprocess', 'filming.expose', 'filming.develop'} <= set(engine.timings)
    assert not any(key.startswith(('printing.', 'scanning.')) for key in engine.timings)
    gray = engine.process(np.full((1, 1, 3), .184), collect='cmy_film').reshape(1, 3)

    # Independent direct sums over the profile's own wavelength samples.
    # D50 normalization and Gaussian integral normalization both cancel in
    # S/S_base, so no production scanner weights or illuminant helper is used.
    wavelengths = np.asarray(engine.film.data.wavelengths)
    shape = colour.SpectralShape(float(wavelengths[0]), float(wavelengths[-1]), 5)
    d50 = colour.SDS_ILLUMINANTS['D50'].copy().align(shape).values
    dyes = np.asarray(engine.film.data.channel_density)
    base = np.asarray(engine.film.data.base_density)

    def scan_density(density):
        spectral = np.empty((len(density), len(wavelengths)))
        for sample in range(len(density)):
            spectral[sample] = (base + density[sample, 0] * dyes[:, 0]
                                + density[sample, 1] * dyes[:, 1]
                                + density[sample, 2] * dyes[:, 2])
        transmitted = 10.0 ** (-spectral)
        # A zero CMY density still has the same undefined dye bands as the
        # full film spectrum. Match upstream's missing-band policy exactly.
        base_spectrum = base + np.zeros(3) @ dyes.T
        transmitted_base = 10.0 ** (-base_spectrum)
        transmitted[np.isnan(transmitted)] = 0
        transmitted_base[np.isnan(transmitted_base)] = 0
        result = np.empty((len(density), 3))
        for channel, (center, sigma) in enumerate([(620., 35.), (540., 30.), (460., 25.)]):
            weights = d50 * np.exp(-((wavelengths - center) ** 2) / (2 * sigma ** 2))
            signal = np.sum(transmitted * weights, axis=1)
            base_signal = np.sum(transmitted_base * weights)
            result[:, channel] = -np.log10(np.maximum(signal / base_signal, 1e-30))
        return result

    density = scan_density(cmy)
    gray_density = scan_density(gray)
    positive = .184 * np.exp(np.log(10.) * (density - gray_density) / .60)
    positive /= .816 + positive
    positive = compress_rgb(positive, spec.output_gamut_compress, output_color_space='sRGB')
    return np.clip(colour.models.eotf_inverse_sRGB(positive), 0, 1)


@pytest.mark.parametrize('film', [
    'kodak_portra_400', 'fujifilm_c200', 'kodak_vision3_500t',
])
def test_digital_model_matches_independent_wavelength_integrals(film):
    spec = BundleSpec(film_profile=film, print_profiles=('kodak_portra_endura',),
                      input_color_space='Panasonic V-Log', output_color_space='sRGB',
                      resolution=33, stops_above_midgray=None,
                      output_gamut_compress=CONFIG['output_gamut_compress'])
    rng = np.random.default_rng(401)
    points = np.concatenate([
        rng.random((1024, 3)),
        np.array(np.meshgrid([0., .5, 1.], [0., .5, 1.], [0., .5, 1.])).reshape(3, -1).T,
        colour.models.log_encoding_VLog(np.repeat(np.geomspace(1e-5, 10, 129)[:, None], 3, axis=1)),
    ])
    expected = independent_spectral_positive(spec, points)
    actual = run_digital_reference(spec, points)
    assert np.isfinite(expected).all() and np.isfinite(actual).all()
    np.testing.assert_allclose(actual, expected, atol=2e-6, rtol=0)
