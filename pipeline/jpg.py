"""Display-referred tone protection for already rendered Standard JPEGs.

This is a Film Lab rendering policy, not a camera inverse or a measured print
profile. The underlying film / official LUT remains the colour source. A fixed
neutral response removes most repeated model tonality and neutral casts; a
smooth source-lightness bound also protects coloured shadows. No image-wide
statistics, exposure adjustment or spatial filtering are used.
"""
from __future__ import annotations

import numpy as np

from pipeline.common import srgb_decode
from pipeline.research import linear_to_oklab, oklab_to_linear, srgb_encode

METHOD_ID = 'film-lab-jpg-tone-protection-v1'
NEUTRAL_SAMPLES = 4097
TONE_RETENTION = .20
LUMINANCE_WEIGHTS = np.array([.2126, .7152, .0722])


def lightness_limit(lightness):
    """Smooth interior allowance, tapered to exact black/white endpoints."""
    lightness = np.clip(np.asarray(lightness, dtype=float), 0., 1.)
    interior = .028 + .012 * np.exp(-((lightness - .6) / .2) ** 2)
    return np.minimum(interior, .5 * np.minimum(lightness, 1. - lightness))


def gamut_map(lab):
    """Fit chroma into sRGB at fixed OKLab lightness and hue.

    In-gamut values are untouched. Out-of-gamut values move only toward the
    neutral axis, so channel clipping cannot change the requested lightness.
    The endpoint assignment avoids residual matrix roundoff at exact black.
    """
    lab = np.asarray(lab, dtype=float)
    rgb = oklab_to_linear(lab)
    # The published OKLab matrices round-trip gamut-face primaries with small
    # floating-point overshoot. Treat this as roundoff, not a gamut excursion.
    tolerance = 2e-7
    outside = (rgb.min(axis=-1) < -tolerance) | (rgb.max(axis=-1) > 1. + tolerance)
    if np.any(outside):
        selected = lab[outside].copy()
        lo = np.zeros(len(selected))
        hi = np.ones(len(selected))
        for _ in range(18):
            mid = (lo + hi) * .5
            candidate = selected.copy()
            candidate[:, 1:] *= mid[:, None]
            candidate_rgb = oklab_to_linear(candidate)
            valid = (candidate_rgb.min(axis=-1) >= -tolerance) & (candidate_rgb.max(axis=-1) <= 1. + tolerance)
            lo = np.where(valid, mid, lo)
            hi = np.where(valid, hi, mid)
        selected[:, 1:] *= lo[:, None]
        rgb = rgb.copy()
        rgb[outside] = oklab_to_linear(selected)
    neutral = np.linalg.norm(lab[..., 1:], axis=-1) < 1e-7
    rgb = np.where(neutral[..., None], lab[..., :1] ** 3, rgb)
    rgb = np.where((lab[..., 0] <= 0)[..., None], 0., rgb)
    rgb = np.where((lab[..., 0] >= 1)[..., None], 1., rgb)
    return np.clip(rgb, 0., 1.)


class JpgToneProtection:
    """Calibrate once per colour model, independently of any photograph."""

    def __init__(self, raw_render, *, digital=False):
        self.raw_render = raw_render
        self.digital = bool(digital)
        self.retention = 0. if digital else TONE_RETENTION
        self.axis = np.linspace(0., 1., NEUTRAL_SAMPLES)
        gray = np.repeat(self.axis[:, None], 3, axis=1)
        response = np.asarray(raw_render(gray), dtype=float)
        if response.shape != gray.shape or not np.isfinite(response).all():
            raise ValueError('Invalid neutral response from colour model')
        if response.min() < 0 or response.max() > 1:
            raise ValueError('Colour model must return bounded encoded sRGB')
        self.neutral_lab = linear_to_oklab(srgb_decode(response))

    def apply(self, samples, rendered=None):
        source = np.asarray(samples, dtype=float)
        if source.ndim < 1 or source.shape[-1] != 3 or not source.size:
            raise ValueError('Expected nonempty RGB triples')
        if not np.isfinite(source).all() or source.min() < 0 or source.max() > 1:
            raise ValueError('JPG input must be finite encoded sRGB in 0..1')
        shape = source.shape
        source = source.reshape(-1, 3)
        output = np.asarray(self.raw_render(source) if rendered is None else rendered, dtype=float).reshape(-1, 3)
        if output.shape != source.shape or not np.isfinite(output).all() or output.min() < 0 or output.max() > 1:
            raise ValueError('Invalid colour-model output')
        linear = srgb_decode(source)
        source_l = np.clip(linear_to_oklab(linear)[:, 0], 0., 1.)
        y = linear @ LUMINANCE_WEIGHTS
        neutral_code = srgb_encode(y)
        neutral = np.stack([np.interp(neutral_code, self.axis, self.neutral_lab[:, i]) for i in range(3)], axis=1)
        lab = linear_to_oklab(srgb_decode(output))
        raw_l = lab[:, 0] + (1. - self.retention) * (np.cbrt(y) - neutral[:, 0])
        limit = lightness_limit(source_l)
        deviation = np.divide(raw_l - source_l, limit, out=np.zeros_like(limit), where=limit > 1e-12)
        target_l = source_l + limit * np.tanh(deviation)
        # Remove the model's response to a neutral input at the same Y. This
        # specifically removes the digital scanner's brown black floor.
        chroma = lab[:, 1:] - neutral[:, 1:]
        gain = np.divide(target_l, lab[:, 0], out=np.ones_like(target_l), where=lab[:, 0] > 1e-12)
        protected = np.column_stack([target_l, chroma * np.clip(gain, 0., 3.)[:, None]])
        encoded = np.clip(srgb_encode(self.map_gamut(protected)), 0., 1.)
        encoded[np.all(source == 0., axis=1)] = 0.
        encoded[np.all(source == 1., axis=1)] = 1.
        return encoded.reshape(shape)

    def map_gamut(self, lab):
        """Original v3 boundary mapping; subclasses can opt into another mapper."""
        return gamut_map(lab)

    def metadata(self):
        return {
            'method': METHOD_ID,
            'input': 'already rendered encoded sRGB / Standard JPEG',
            'neutralSamples': NEUTRAL_SAMPLES,
            'neutralAxis': 'uniform encoded sRGB 0..1; interpolate OKLab response at equal input linear Y',
            'neutralToneRetention': self.retention,
            'neutralCastRemoval': 1.,
            'lightness': 'Lraw = Lmodel + (1-retention)*(cuberoot(inputY)-Lneutral); Ltarget = Lsource + limit*tanh((Lraw-Lsource)/limit)',
            'limit': 'min(0.028+0.012*exp(-((Lsource-0.6)/0.2)^2), 0.5*min(Lsource,1-Lsource)) in OKLab L',
            'chroma': '(ab_model-ab_neutral) * clip(Ltarget/Lmodel, 0, 3)',
            'gamutMapping': 'reduce OKLab chroma at fixed lightness and hue; exact neutral black/white endpoints',
            'digitalBlackCorrection': self.digital,
            'perImageAdaptation': False,
            'vlogModified': False,
            'cameraInverseCalibrated': False,
            'physicalFilmOrPrintMatch': False,
            'limitations': [
                'An explicit Film Lab JPEG rendering policy; not unmodified upstream tonality or an official Fujifilm JPEG recipe.',
                'Keeps model colour differences while reducing repeated tonality; gamut-boundary chroma and contrast can change.',
                'Cannot restore source detail already clipped or lost by the camera.',
            ],
        }
