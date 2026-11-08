"""Single tone before a fixed colour renderer, with no output colour edits.

R(x) = exported VLOG cube(F(x)), N(x) = E(Y(D(R(x,x,x)))), P = inverse(N).
STD_v(x) = R(P(T_v(x))), applying the SAME scalar P and T to each channel.
The neutral inverse is a working assumption about rendered JPEGs, not a
measured inverse of Panasonic Standard. All calibration is per LUT, not image.
"""
from __future__ import annotations

from copy import deepcopy
import numpy as np

from pipeline.common import srgb_decode
from pipeline.research import srgb_encode

METHOD_ID = 'film-lab-single-tone-precurve-v1'
GENERATION = 'exported-vlog-single-tone-precurve-v4'
NEUTRAL_SAMPLES = 4097
MIDDLE_GRAY = .18
LUMINANCE_WEIGHTS = np.array([.2126, .7152, .0722])


class SingleTonePrecurve:
    """Invert only the renderer's scalar neutral luminance before rendering.

    The output RGB is returned untouched. In particular, neutral colour casts,
    source gamut mapping, source paper black/white, and chromatic responses are
    retained. No neutral subtraction, chroma gain, OKLab constraint or output
    gamut mapping occurs here. The source renderer itself can contain its
    original gamut compression and clipping; this class cannot reverse it.
    """

    def __init__(self, raw_render, source_metadata=None):
        self.raw_render = raw_render
        self.source_metadata = deepcopy(source_metadata or {})
        self.axis = np.linspace(0., 1., NEUTRAL_SAMPLES)
        gray = np.repeat(self.axis[:, None], 3, axis=1)
        response = np.asarray(raw_render(gray), dtype=float)
        if response.shape != gray.shape or not np.isfinite(response).all():
            raise ValueError('Invalid neutral response from source renderer')
        if response.min() < 0 or response.max() > 1:
            raise ValueError('Source renderer must return encoded sRGB in 0..1')
        self.neutral_response = response.copy()
        measured_y = srgb_decode(response) @ LUMINANCE_WEIGHTS
        self.measured_neutral_code = srgb_encode(measured_y)
        self.neutral_code = np.maximum.accumulate(self.measured_neutral_code)
        self.y_black, self.y_white = float(measured_y[0]), float(measured_y[-1])
        if self.y_white <= self.y_black:
            raise ValueError('No increasing neutral range in source renderer')
        # A must retain the actual N(0) and N(1), not an earlier peak chosen by
        # the monotonic correction. Reject contradictory source endpoints.
        if self.neutral_code[-1] > self.measured_neutral_code[-1] + 1e-12:
            raise ValueError('Source neutral endpoint falls below an earlier peak')
        unique, indices = np.unique(self.neutral_code, return_index=True)
        self.inverse_output = unique
        self.inverse_input = self.axis[indices].copy()
        self.inverse_input_right = self.axis[np.r_[indices[1:] - 1, len(self.axis)-1]]
        # Invert each increasing segment between the END of a lower plateau
        # and START of the next. Overwriting a plateau's first point with its
        # final point distorts interpolation in the adjacent rising segment.
        # Exact endpoints are handled separately in inverse(). No epsilon
        # slope or missing detail is invented.
        self.rolloff_k = ((1. - self.y_white) / (self.y_white - MIDDLE_GRAY)
                          if self.y_white > MIDDLE_GRAY else None)

    @staticmethod
    def _pixels(samples):
        samples = np.asarray(samples, dtype=float)
        if samples.ndim < 1 or samples.shape[-1] != 3 or not samples.size:
            raise ValueError('Expected nonempty RGB triples')
        if not np.isfinite(samples).all() or samples.min() < 0 or samples.max() > 1:
            raise ValueError('Input must be finite encoded sRGB in 0..1')
        return samples

    def inverse(self, encoded_samples):
        """P: monotone piecewise linear inverse, saturating outside its range.

        Clamping is relevant for B's identity shadows below native black;
        A constructs its target wholly inside the attainable neutral range.
        """
        encoded_samples = np.asarray(encoded_samples, dtype=float)
        hi = np.clip(np.searchsorted(self.inverse_output, encoded_samples, side='left'),
                     1, len(self.inverse_output)-1)
        lo = hi-1
        fraction = np.clip((encoded_samples-self.inverse_output[lo]) /
                           (self.inverse_output[hi]-self.inverse_output[lo]), 0., 1.)
        result = self.inverse_input_right[lo] + fraction * (self.inverse_input[hi]-self.inverse_input_right[lo])
        result = np.where(encoded_samples <= self.inverse_output[0], 0., result)
        return np.where(encoded_samples >= self.inverse_output[-1], 1., result)

    def target(self, samples, variant='A'):
        samples = self._pixels(samples)
        y = srgb_decode(samples)
        if variant == 'A':
            target_y = self.y_black + (self.y_white - self.y_black) * y
        elif variant == 'B':
            if self.rolloff_k is None:
                raise ValueError('B cannot retain 18% gray when source white is <= 18%')
            high = np.maximum(y - MIDDLE_GRAY, 0.)
            shoulder = MIDDLE_GRAY + high / (1. + self.rolloff_k * high / (1. - MIDDLE_GRAY))
            target_y = np.where(y <= MIDDLE_GRAY, y, shoulder)
        else:
            raise ValueError('STD variant must be A or B')
        return srgb_encode(target_y)

    def apply(self, samples, variant='A'):
        source = self._pixels(samples)
        warped = self.inverse(self.target(source, variant))
        output = np.asarray(self.raw_render(warped.reshape(-1, 3)), dtype=float).reshape(source.shape)
        if not np.isfinite(output).all() or output.min() < 0 or output.max() > 1:
            raise ValueError('Invalid source renderer output')
        return output

    def metadata(self, variant='A'):
        if variant not in ('A', 'B'):
            raise ValueError('STD variant must be A or B')
        if variant == 'B' and self.rolloff_k is None:
            raise ValueError('B cannot retain 18% gray when source white is <= 18%')
        return {
            'method': METHOD_ID,
            'generation': GENERATION,
            'variant': variant,
            'contract': 'R(x)=L_VLOG(F(x)); F=VLogEncode(sRGBDecode(x) @ sRGB_to_VGamut.T); L_STD(x)=R(P(T(x)))',
            'source': deepcopy(self.source_metadata),
            'neutralSamples': NEUTRAL_SAMPLES,
            'neutralDefinition': 'N(x)=sRGBEncode(dot(sRGBDecode(R([x,x,x])), [0.2126,0.7152,0.0722]))',
            'monotonicPolicy': 'cumulative maximum of N; piecewise-linear generalised inverse; first plateau occurrence, true endpoint at white; no fabricated slope',
            'decreasingNeutralSteps': int(np.count_nonzero(np.diff(self.measured_neutral_code) < 0)),
            'plateauNeutralSteps': int(np.count_nonzero(np.diff(self.neutral_code) == 0)),
            'maximumMonotonicCorrection': float(np.max(self.neutral_code - self.measured_neutral_code)),
            'channelPolicy': 'identical scalar T then P on each encoded RGB channel; return source-renderer RGB unchanged',
            'blackLinearY': self.y_black,
            'whiteLinearY': self.y_white,
            'blackEncodedY': float(self.measured_neutral_code[0]),
            'whiteEncodedY': float(self.measured_neutral_code[-1]),
            'blackRgb': self.neutral_response[0].tolist(),
            'whiteRgb': self.neutral_response[-1].tolist(),
            'targetTone': ('E(b+(w-b)*D(x)); native black/white range in linear light'
                           if variant == 'A' else
                           'y=D(x); y<=m: y; y>m: m+(y-m)/(1+k*(y-m)/(1-m)); encode with sRGB'),
            'rolloff': (None if variant == 'A' else {
                'parameter': 'k', 'value': self.rolloff_k,
                'derivation': 'k=(1-w)/(w-m); determined by T(1)=w with T(m)=m and T_prime(m)=1',
                'middleGrayLinear': MIDDLE_GRAY,
                'middleGrayEncoded255': float(srgb_encode(MIDDLE_GRAY) * 255),
                'continuity': 'C1 at middle gray; monotone with strictly positive derivative when w>m',
                'shadowFloor': 'P saturates below E(b); B cannot preserve detail below the source black floor',
            }),
            'perImageAdaptation': False,
            'neutralCastRemoval': False,
            'chromaGain': False,
            'outputColourEdits': False,
            'vlogModified': False,
            'cameraInverseCalibrated': False,
            'pairedCameraValidation': 'NOT performed: same-scene V-Log + VLOG LUT versus Standard + new STD LUT required',
            'limitations': [
                'Assumes the already rendered camera tone takes the place of the film tone; Panasonic Standard tone is not known or measured here.',
                'An RGB-shared scalar inverse does not preserve all hues or undo camera rendering; only neutral luminance is inverted.',
                'Native colour casts and source gamut compression/clipping remain. No new chroma gain or neutral subtraction.',
                'Cannot recover clipped camera/source detail. Quantised 8-bit display can repeat levels despite an increasing float curve.',
                'Black/white are the reachable neutral endpoints of R on input 0..1, not measured paper Dmin/Dmax.',
            ],
        }
