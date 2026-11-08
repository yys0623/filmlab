"""A declared digital-printer bridge into upstream paper development/scanning.

The input is display-linear sRGB/BT.709 RGB, *after* a film-simulation LUT.
It is not film density or scene-linear camera exposure. A fixed neutral-ramp
calibration maps completed display RGB to virtual paper-channel log exposures.
This avoids imposing a second steep photographic tone curve on an image that
already has one. Only paper-development and print-scanning nodes run; paper
dyes, spectral interactions and the stock's attainable black/white remain.
"""
from __future__ import annotations

from copy import deepcopy

import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.optimize import least_squares

from pipeline.common import CONFIG
from spektrafilm.runtime.params_builder import digest_params, init_params
from spektrafilm.runtime.pipeline import SimulationPipeline
from spektrafilm.runtime.topology import Tap
from spektrafilm.utils.gamut_compression import OutputGamutCompressSpec


METHOD_ID = 'film-lab-fuji-digital-paper-bridge-v2'
GRAY_ANCHOR = 0.184
NEUTRAL_SAMPLES = 4097
LUMINANCE_WEIGHTS = np.array([.2126, .7152, .0722])
STAGE_NAMES = ('printing.develop', 'scanning.scan_print')


class PaperBridge:
    """Map rendered RGB through a fixed, neutral-calibrated digital print model.

    Calibrate each stock once, independently of photographs and simulations.
    A smooth target connects the stock's black, neutral middle gray and white;
    invert the stock's neutral response to find printer exposures. The target
    is a declared Film Lab rendering choice, not a measured printer profile.
    Upstream paper curves, spectral dyes and the scanner remain unchanged.
    """

    def __init__(self, paper_id: str, init_film: str = 'kodak_portra_400'):
        params = init_params(film_profile=init_film, print_profile=paper_id)
        if params.print.info.stage != 'printing' or not params.print.is_negative:
            raise ValueError('Paper bridge requires a negative printing profile')
        params.debug.lut_mode = True
        params.settings.neutral_print_filters_from_database = False
        params.settings.use_scanner_lut = False
        params.io.scan_film = False
        params.io.input_color_space = 'sRGB'
        params.io.input_cctf_decoding = False
        params.io.output_color_space = 'sRGB'
        params.io.output_cctf_encoding = False
        params.io.output_gamut_compress = OutputGamutCompressSpec(
            algorithm=CONFIG['output_gamut_compress'],
        )
        self._pipeline = SimulationPipeline(digest_params(params))
        self.paper_id = paper_id
        self.init_film = init_film
        self._support = params.print.info.support

        # LOG_E_PRINT bypasses preprocess, all film nodes, and the enlarger.
        # lut_mode disables black/white correction, image statistics, and all
        # spatial/stochastic effects, so no earlier-stage state is required.
        log_exposure = np.asarray(params.print.data.log_exposure, dtype=float)
        result = least_squares(
            lambda offset: self._from_log_exposure(offset) - GRAY_ANCHOR,
            np.zeros(3),
            bounds=(float(log_exposure.min()), float(log_exposure.max())),
            xtol=1e-12, ftol=1e-12, gtol=1e-12,
        )
        self.offset = np.asarray(result.x, dtype=float)
        self._calibrated_gray = self._from_log_exposure(self.offset)
        self._calibration_error = float(np.max(np.abs(self._calibrated_gray - GRAY_ANCHOR)))
        if not result.success or self._calibration_error > 1e-7:
            raise RuntimeError(f'Paper gray calibration failed for {paper_id}')

        # Sweep the complete profile domain. Each end takes all three paper
        # channels beyond the corresponding profile boundary. Include zero
        # exactly so the already-solved middle-gray exposure remains a knot.
        lower = float(log_exposure.min() - self.offset.max())
        upper = float(log_exposure.max() - self.offset.min())
        deltas = np.unique(np.r_[np.linspace(lower, upper, NEUTRAL_SAMPLES), 0.])
        neutral_rgb = self._from_log_exposure(self.offset + deltas[:, None])
        neutral_y = neutral_rgb @ LUMINANCE_WEIGHTS
        increasing_y = np.maximum.accumulate(neutral_y[::-1])
        self._monotonic_adjustment = float(np.max(increasing_y - neutral_y[::-1]))
        # The upstream fitted profiles can have minute spline wiggles near
        # saturation. Ignore numerical plateaus when forming a monotone inverse.
        keep = np.r_[True, np.diff(increasing_y) > 1e-12]
        # Retain the exact white endpoint even if its final change is smaller
        # than the plateau tolerance; the target must never extrapolate.
        if increasing_y[-1] > increasing_y[keep][-1]:
            keep[-1] = True
        self._inverse_neutral = PchipInterpolator(
            increasing_y[keep], deltas[::-1][keep], extrapolate=False,
        )
        self._black_y, self._white_y = map(float, increasing_y[[0, -1]])
        if not 0 <= self._black_y < GRAY_ANCHOR < self._white_y <= 1:
            raise RuntimeError(f'Invalid attainable paper range for {paper_id}')
        self._target = PchipInterpolator(
            [0., GRAY_ANCHOR, 1.],
            [self._black_y, GRAY_ANCHOR, self._white_y],
            extrapolate=False,
        )
        self._neutral_sample_count = len(deltas)
        self._neutral_exposure_range = [lower, upper]
        self._profile_exposure_range = [float(log_exposure.min()), float(log_exposure.max())]
        endpoints = self.apply(np.array([[0., 0., 0.], [1., 1., 1.]]))
        self._endpoints = {'black': endpoints[0].tolist(), 'white': endpoints[1].tolist()}

    def _from_log_exposure(self, log_exposure: np.ndarray) -> np.ndarray:
        values = np.asarray(log_exposure, dtype=float)
        result = self._pipeline.process(values.reshape(1, -1, 3), inject=Tap.LOG_E_PRINT)
        return np.asarray(result, dtype=float).reshape(values.shape)

    def apply(self, linear_srgb_array) -> np.ndarray:
        """Accept finite 0..1 RGB of shape ``(..., 3)``; return the same shape."""
        try:
            rgb = np.asarray(linear_srgb_array, dtype=np.float64)
        except (TypeError, ValueError) as exc:
            raise ValueError('Paper bridge input must be a numeric RGB array') from exc
        if rgb.ndim < 1 or rgb.shape[-1] != 3 or not rgb.size:
            raise ValueError('Paper bridge input must have nonempty shape (..., 3)')
        if not np.isfinite(rgb).all():
            raise ValueError('Paper bridge input must be finite')
        if rgb.min() < 0 or rgb.max() > 1:
            raise ValueError('Paper bridge input must be display-linear RGB in 0..1')
        # Use the same neutral inverse separately for each RGB channel. This
        # compensates printer tonality without fitting away chromatic dye and
        # spectral interactions. PCHIP has finite endpoint slopes and avoids
        # hard clipping highlights to the attainable stock white.
        target_y = np.clip(self._target(rgb), self._black_y, self._white_y)
        log_exposure = self.offset + self._inverse_neutral(target_y)
        output = self._from_log_exposure(log_exposure)
        if not np.isfinite(output).all():
            raise RuntimeError('Non-finite paper bridge output')
        # The upstream gamut compressor bounds the result.  Clip only final
        # floating-point boundary overshoot; no image-dependent normalization.
        return np.clip(output, 0., 1.)

    def metadata(self) -> dict:
        """Return reproducible settings and explicit limits of the bridge."""
        return deepcopy({
            'method': METHOD_ID,
            'paperProfile': self.paper_id,
            'profileSupport': self._support,
            'input': 'display-linear sRGB / BT.709 primaries, D65, RGB 0..1',
            'output': 'display-linear sRGB, D65, RGB 0..1; encode sRGB after this stage',
            'formula': 'logE_c = offset_c + inverseNeutralY(target(linearRGB_c))',
            'offset': self.offset.tolist(),
            'grayLinearAnchor': GRAY_ANCHOR,
            'calibratedGrayLinearRGB': self._calibrated_gray.tolist(),
            'calibrationMaxAbsLinearRGBError': self._calibration_error,
            'calibration': 'fixed per-stock neutral-ramp printer calibration; no per-image or per-simulation fit',
            'neutralCalibration': {
                'response': 'Y(delta) = dot(scanPrint(developPrint(offset + delta)), [0.2126, 0.7152, 0.0722])',
                'sampleCount': self._neutral_sample_count,
                'baseSampleCount': NEUTRAL_SAMPLES,
                'profileLogExposureRange': self._profile_exposure_range,
                'deltaLogExposureRange': self._neutral_exposure_range,
                'inverseInterpolation': 'monotone PCHIP, no extrapolation; equal-Y plateaus removed at 1e-12',
                'monotonicMaxLinearYAdjustment': self._monotonic_adjustment,
                'targetInterpolation': 'monotone PCHIP, no extrapolation',
                'targetInputLinearRGB': [0., GRAY_ANCHOR, 1.],
                'targetOutputLinearY': [self._black_y, GRAY_ANCHOR, self._white_y],
                'attainableBlackLinearY': self._black_y,
                'attainableWhiteLinearY': self._white_y,
            },
            'linearEndpointOutputs': self._endpoints,
            'upstreamStagesApplied': list(STAGE_NAMES),
            'upstreamPaperCurvesModified': False,
            'upstreamOpticalEnlargerApplied': False,
            'upstreamFilmStagesApplied': False,
            'runtimeInitFilm': self.init_film,
            'runtimeInitFilmApplied': False,
            'spectralScannerLUT': False,
            'outputGamutCompression': CONFIG['output_gamut_compress'],
            'perSimulationCalibration': False,
            'perImageCalibration': False,
            'physicalPrinterCalibrated': False,
            'fujifilmOfficialPaperTransform': False,
            'limitations': [
                'Virtual digital-printer exposure mapping; not an optical negative-to-paper exposure model.',
                'The neutral-ramp calibration and three-anchor target are Film Lab choices, not measured printer or Fujifilm data.',
                'Printer calibration avoids a second steep tone curve; stock black/white, gray-axis casts and spectral color interactions remain.',
                'Paper development, spectral dyes, viewing illuminant, and gamut compression use the pinned upstream model.',
                'Kodak 2383 and 2393 are motion-picture print films, not photographic paper.',
                'Fujifilm simulation output plus this bridge is a derived creative result, not an official Fujifilm paper rendering.',
            ],
        })
