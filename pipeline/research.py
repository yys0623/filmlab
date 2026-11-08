"""Explicit editorial colour interpretations informed by real-film references.

No spektrafilm film/paper transform is used here. Parameters describe a small,
auditable display-referred OKLab grade; they are not fitted film calibration.
"""
from __future__ import annotations

import numpy as np
from scipy.interpolate import PchipInterpolator

from pipeline.common import VGAMUT_TO_SRGB, srgb_decode

REFERENCE_METHOD_ID = 'film-lab-reference-interpretation-v1'
REFERENCE_CONTRACT = (
    'Encoded sRGB -> linear sRGB -> OKLab -> monotonic PCHIP lightness tone; '
    'smooth circular hue-weighted chroma and hue changes; near-neutral protected '
    'shadow/highlight tint -> linear sRGB channel boundary clamp -> encoded sRGB. '
    'Editorial interpretation, not a film/paper physical model '
    'or a measured match to the reference photographs.'
)
VLOG_CONTRACT = (
    'Panasonic V-Log decode -> V-Gamut to linear sRGB -> shared per-channel '
    'shoulder above 0.75 (18.4% gray unchanged), negative channels clamped to zero '
    '-> encoded sRGB -> reference interpretation. This is an approximate '
    'display base for V-Log, not a camera or film calibration.'
)
VLOG_KNEE = .75
NEUTRAL_CHROMA = .035

# Björn Ottosson's published linear-sRGB / OKLab matrices.
_M1 = np.array([[.4122214708, .5363325363, .0514459929],
                [.2119034982, .6806995451, .1073969566],
                [.0883024619, .2817188376, .6299787005]])
_M2 = np.array([[.2104542553, .7936177850, -.0040720468],
                [1.9779984951, -2.4285922050, .4505937099],
                [.0259040371, .7827717662, -.8086757660]])
_M1_INV = np.linalg.inv(_M1)
_M2_INV = np.linalg.inv(_M2)


def linear_to_oklab(rgb):
    return np.cbrt(np.asarray(rgb, dtype=float) @ _M1.T) @ _M2.T


def oklab_to_linear(lab):
    return ((np.asarray(lab, dtype=float) @ _M2_INV.T) ** 3) @ _M1_INV.T


def srgb_encode(rgb):
    rgb = np.asarray(rgb, dtype=float)
    return np.where(rgb <= .0031308, 12.92 * rgb,
                    1.055 * np.maximum(rgb, 0) ** (1 / 2.4) - .055)


def validate_parameters(parameters):
    tone = parameters['tone']
    x, y = np.asarray(tone['x'], float), np.asarray(tone['y'], float)
    if x.ndim != 1 or x.size < 3 or x.shape != y.shape or not np.isfinite([x, y]).all():
        raise ValueError('Tone points must be matching finite one-dimensional arrays')
    if (x[0], x[-1], y[0], y[-1]) != (0., 1., 0., 1.):
        raise ValueError('Tone must preserve exact black and white endpoints')
    if (np.diff(x) <= 0).any() or (np.diff(y) <= 0).any():
        raise ValueError('Tone knots must be strictly increasing')
    if not .5 <= parameters.get('saturation', 1.) <= 1.5:
        raise ValueError('Global saturation outside supported range')
    for band in parameters.get('hueBands', []):
        values = [band['centerDeg'], band['widthDeg'], band.get('saturation', 1), band.get('hueShiftDeg', 0)]
        if not np.isfinite(values).all() or not 5 <= values[1] <= 180:
            raise ValueError('Hue band must have finite values and a 5–180 degree width')
        if not .5 <= values[2] <= 1.5 or abs(values[3]) > 20:
            raise ValueError('Hue band saturation/hue shift outside supported range')
    for key in ['shadowTint', 'highlightTint']:
        tint = np.asarray(parameters.get(key, [0, 0]), float)
        if tint.shape != (2,) or not np.isfinite(tint).all() or np.max(np.abs(tint)) > .02:
            raise ValueError('Tint must be two finite OKLab a/b offsets within ±0.02')
    return parameters


def circular_weight(hue, center_degrees, width_degrees):
    """Smooth periodic weight: no discontinuity at the 0/360 degree seam."""
    sigma = np.deg2rad(width_degrees)
    return np.exp((np.cos(hue - np.deg2rad(center_degrees)) - 1) / sigma ** 2)


def bound_oklab_to_linear_srgb(lab):
    """Convert the grade to display RGB and clamp only out-of-gamut channels.

    Fixed-lightness/hue gamut-boundary compression was rejected after its steep
    bright-yellow boundary caused large 33-cube interpolation errors. Channel
    clipping is continuous and leaves all in-gamut colours unchanged; it does
    not promise exact OKLab lightness or hue for out-of-gamut colours.
    """
    lab = np.asarray(lab, dtype=float)
    rgb = oklab_to_linear(lab)
    neutral = np.linalg.norm(lab[..., 1:], axis=-1) < 1e-7
    rgb = np.where(neutral[..., None], lab[..., :1] ** 3, rgb)
    return np.clip(rgb, 0, 1)


def apply_reference_std(samples_encoded, parameters):
    parameters = validate_parameters(parameters)
    samples = np.asarray(samples_encoded, dtype=float)
    if samples.shape[-1] != 3 or not np.isfinite(samples).all():
        raise ValueError('Expected finite encoded sRGB triples')
    if samples.min() < 0 or samples.max() > 1:
        raise ValueError('STD input must be within 0–1')
    lab = linear_to_oklab(srgb_decode(samples))
    lightness = np.clip(lab[..., 0], 0, 1)
    chroma = np.linalg.norm(lab[..., 1:], axis=-1)
    hue = np.arctan2(lab[..., 2], lab[..., 1])
    tone = parameters['tone']
    out_l = PchipInterpolator(tone['x'], tone['y'])(lightness)
    saturation = np.full_like(chroma, parameters.get('saturation', 1.))
    hue_offset = np.zeros_like(chroma)
    for band in parameters.get('hueBands', []):
        weight = circular_weight(hue, band['centerDeg'], band['widthDeg'])
        saturation *= 1 + weight * (band.get('saturation', 1.) - 1)
        hue_offset += weight * np.deg2rad(band.get('hueShiftDeg', 0.))
    out_c = chroma * saturation
    out_h = hue + hue_offset
    out_ab = np.stack([out_c * np.cos(out_h), out_c * np.sin(out_h)], axis=-1)
    # Exact neutrals remain neutral. Small chroma receives only a smooth
    # fraction of the editorial tint; endpoints have zero tint strength.
    protection = 1 - np.exp(-(chroma / NEUTRAL_CHROMA) ** 2)
    envelope = 4 * out_l * (1 - out_l) * protection
    shadows = np.exp(-.5 * ((out_l - .25) / .22) ** 2)
    highlights = np.exp(-.5 * ((out_l - .80) / .20) ** 2)
    out_ab += envelope[..., None] * (
        shadows[..., None] * np.asarray(parameters.get('shadowTint', [0, 0]))
        + highlights[..., None] * np.asarray(parameters.get('highlightTint', [0, 0])))
    result = bound_oklab_to_linear_srgb(np.concatenate([out_l[..., None], out_ab], axis=-1))
    return np.clip(srgb_encode(result), 0, 1)


def vlog_to_display_srgb(samples_encoded):
    samples = np.asarray(samples_encoded, dtype=float)
    if samples.shape[-1] != 3 or not np.isfinite(samples).all() or samples.min() < 0 or samples.max() > 1:
        raise ValueError('V-Log input must be finite RGB triples within 0–1')
    linear_vgamut = np.where(samples < .181, (samples - .125) / 5.6,
                            10 ** ((samples - .598206) / .241514) - .00873)
    linear_rgb = linear_vgamut @ VGAMUT_TO_SRGB.T
    # The same bounded display shoulder is applied to each linear RGB channel.
    # This avoids a division by luminance near highly saturated/negative gamut
    # boundaries. It may change hue in HDR; it is an approximate display base.
    above = np.maximum(linear_rgb - VLOG_KNEE, 0)
    bounded = np.where(linear_rgb <= VLOG_KNEE, np.maximum(linear_rgb, 0),
                       VLOG_KNEE + (1 - VLOG_KNEE) * above / (above + 1 - VLOG_KNEE))
    return np.clip(srgb_encode(bounded), 0, 1)


def apply_reference_vlog(samples_encoded, parameters):
    return apply_reference_std(vlog_to_display_srgb(samples_encoded), parameters)
