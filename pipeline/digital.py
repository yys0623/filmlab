"""Paperless negative conversion with one documented, shared scanner model.

This is a Film Lab digital positive conversion, not a measured commercial
scanner or an upstream spektrafilm positive-film scan. Film exposure and
development remain upstream; paper nodes are never executed.
"""
from dataclasses import replace

import numpy as np
from spektrafilm.config import SPECTRAL_SHAPE
from spektrafilm.model.illuminants import standard_illuminant
from spektrafilm.runtime.params_builder import digest_params, init_params
from spektrafilm.runtime.pipeline import SimulationPipeline
from spektrafilm.runtime.topology import Node, Tap
from spektrafilm.utils.gamut_compression import compress_rgb
from spektrafilm_lut_creator.builders import BundleBuilder
from spektrafilm_lut_creator.color_spaces import decode_cctf, encode_cctf, get

INIT_PRINT_PROFILE = 'kodak_portra_endura'
DIGITAL_METHOD_ID = 'film-lab-common-digital-negative-v1'
SCANNER_CENTERS_NM = (620.0, 540.0, 460.0)
SCANNER_SIGMA_NM = (35.0, 30.0, 25.0)
SCANNER_ILLUMINANT = 'D50'
COMMON_GAMMA = 0.60
GRAY_ANCHOR = 0.184
DIGITAL_CONTRACT = (
    'Upstream film exposure/development -> D50 fixed Gaussian RGB transmission; '
    'D=-log10(S/S_base), S=sum(D50*Gaussian*10^(-spectral_density)); '
    'q=0.184*10^((D-D_gray)/0.60), where D_gray is the same film at linear RGB 0.184; '
    'shared channel shoulder q/(0.816+q) -> upstream output gamut compression. '
    'No paper, per-film slope/matrix fit, image statistics or automatic exposure. '
    'Generic digital positive model; not a measured physical scanner.'
)


def digital_settings():
    return {
        'method': DIGITAL_METHOD_ID, 'contract': DIGITAL_CONTRACT,
        'scannerIlluminant': SCANNER_ILLUMINANT,
        'scannerGaussianCentersNm': list(SCANNER_CENTERS_NM),
        'scannerGaussianSigmaNm': list(SCANNER_SIGMA_NM),
        'commonGamma': COMMON_GAMMA, 'grayLinearAnchor': GRAY_ANCHOR,
        'tone': 'q / (1 - grayLinearAnchor + q), identical per RGB channel',
        'baseRemoval': 'channel transmission divided by unexposed base transmission',
        'missingSpectralData': 'NaN transmission contributes zero, matching upstream density_to_light',
        'grayBalance': 'one fixed simulated gray per film; density offsets only',
        'perFilmSlopeFit': False, 'perFilmColorMatrixFit': False,
        'physicalScannerCalibrated': False,
    }


class DigitalScanPipeline(SimulationPipeline):
    """Upstream negative stages followed by a fixed digital-positive node."""
    def __init__(self, params):
        if not params.film.is_negative:
            raise ValueError('Digital negative scan requires a negative film')
        super().__init__(params)
        wavelengths = np.asarray(SPECTRAL_SHAPE.wavelengths, dtype=np.float64)
        gaussians = np.exp(-0.5 * ((wavelengths[:, None] - SCANNER_CENTERS_NM)
                                  / SCANNER_SIGMA_NM) ** 2)
        self._scanner_weights = np.asarray(standard_illuminant(SCANNER_ILLUMINANT))[:, None] * gaussians
        self._scanner_weights /= self._scanner_weights.sum(axis=0)
        self._base_transmission = self._transmission(np.zeros((1, 1, 3)))[0, 0]
        gray_cmy = self.process(np.full((1, 1, 3), GRAY_ANCHOR), collect=Tap.CMY_FILM)
        self._gray_density = self.optical_density(gray_cmy)[0, 0]

    def _build_topology(self):
        # scan_film=True supplies exactly three upstream film nodes, then a
        # film-transmission scan. Replace only that last scan with conversion.
        nodes = super()._build_topology()
        if not self.io.scan_film:
            raise ValueError('Digital negative scan must bypass printing')
        return nodes[:-1] + [Node((Tap.CMY_FILM,), (Tap.RGB_OUT,),
                                self.digital_positive, 'scanning.digital_negative')]

    def _transmission(self, cmy_density):
        spectral_density = (np.asarray(cmy_density, dtype=np.float64)
                            @ np.asarray(self.film.data.channel_density).T
                            + np.asarray(self.film.data.base_density))
        transmitted = np.power(10.0, -spectral_density)
        # Profile spectra intentionally contain NaN outside their measured
        # range. Match upstream density_to_light: these bands contribute no
        # transmitted light, rather than inventing an extrapolated spectrum.
        transmitted[np.isnan(transmitted)] = 0.0
        if not np.isfinite(transmitted).all():
            raise ValueError('Non-finite digital scanner transmission')
        return transmitted @ self._scanner_weights

    def optical_density(self, cmy_density):
        transmission = self._transmission(cmy_density)
        # Do not cap transmission at 1: masking dyes can yield signed optical
        # density relative to base. The floor only protects the logarithm.
        return -np.log10(np.maximum(transmission / self._base_transmission, 1e-30))

    def digital_positive(self, cmy_density):
        density = self.optical_density(cmy_density)
        q = GRAY_ANCHOR * np.power(10.0, (density - self._gray_density) / COMMON_GAMMA)
        rgb = q / (1.0 - GRAY_ANCHOR + q)
        return compress_rgb(rgb, self.io.output_gamut_compress,
                            output_color_space=self.io.output_color_space)

    def conversion_snapshot(self):
        return {**digital_settings(), 'baseTransmission': self._base_transmission.tolist(),
                'grayScannerDensity': self._gray_density.tolist()}


def _params(spec, init_print_profile):
    params = init_params(film_profile=spec.film_profile, print_profile=init_print_profile)
    if not params.film.is_negative:
        raise ValueError('Digital negative scan requires a negative film')
    params.io.scan_film = True
    params.debug.lut_mode = True
    params.settings.neutral_print_filters_from_database = False
    params.io.input_color_space = get(spec.input_color_space).primaries
    params.io.output_color_space = get(spec.output_color_space).primaries
    params.io.input_cctf_decoding = False
    params.io.output_cctf_encoding = False
    params.io.input_gamut_compress = spec.input_gamut_compress
    params.io.output_gamut_compress = spec.output_gamut_compress
    # Scanner RGB is defined as linear sRGB by this model, not an arbitrary
    # output colourspace. Additional output spaces would need a proper mapping.
    if params.io.output_color_space != 'sRGB':
        raise ValueError('Digital negative model currently requires sRGB output')
    return digest_params(params)


class DigitalScanBundleBuilder(BundleBuilder):
    def _make_pipeline(self, spec, in_entry, out_entry, print_stock):
        pipeline = DigitalScanPipeline(_params(spec, print_stock))
        self._digital_snapshot = pipeline.conversion_snapshot()
        return pipeline

    def build(self):
        if self.spec.topology != '1lut' or len(self.spec.print_profiles) != 1:
            raise ValueError('Digital negative scan supports one combined 1lut only')
        bundle = super().build()
        snapshot = dict(next(iter(bundle.meta.params_snapshot.values())))
        snapshot.update(print_profile=None, scan_film=True,
                        runtime_init_print_profile=self.spec.print_profiles[0],
                        neutral_print_filters_from_database=False,
                        digital_conversion=self._digital_snapshot)
        bundle.meta = replace(
            bundle.meta, name=f'{self.spec.film_profile}__digital_scan',
            stocks=replace(bundle.meta.stocks, prints=()),
            luts=tuple(replace(lut, print_profile=None, path='digital_scan.cube') for lut in bundle.meta.luts),
            params_snapshot={'digital_scan': snapshot},
        )
        bundle.luts = [('digital_scan.cube', bundle.luts[0][1])]
        return bundle


def run_digital_reference(spec, samples_encoded, init_print_profile=INIT_PRINT_PROFILE):
    """Off-grid direct runtime evaluation, separate from the LUT builder."""
    pipeline = DigitalScanPipeline(_params(spec, init_print_profile))
    frame = spec.bake_frame()
    samples = np.asarray(samples_encoded, dtype=np.float32).reshape(1, -1, 3)
    linear = (decode_cctf(samples, spec.input_color_space) * frame.input_gain).astype(np.float32)
    output = np.asarray(pipeline.process(linear), dtype=float).reshape(-1, 3)
    return np.clip(encode_cctf(output * frame.output_gain, spec.output_color_space), 0, 1)
