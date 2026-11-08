"""Fixed-lab-pack print filters: keep part of each film's colour cast.

The upstream database holds calibrated enlarger CMY filters (Kodak CC) that
make a mid-gray print neutral for every film/paper pair. A real lab that does
not re-time every roll prints all films through one fixed filter pack, so each
film keeps its own cast relative to that pack.

Here the filter pack is a blend between the film's own neutral filters and a
fixed reference pack, the reference film's neutral filters on the same paper:

    appliedCC = amount * filmCC + (1 - amount) * referenceCC

amount = 1 reproduces the base look exactly. amount = 0 is a fully fixed pack.
Unlike scaling the filters towards an unfiltered enlarger, each blended filter
value stays between the film and reference values. This does not guarantee a
neutral print: cast strength varies by film and paper. The direction comes
from the database, not from an editorial colour target; it is not guaranteed
to match how a film is popularly remembered.

Exception (TARGET_HUE): a few films whose database direction contradicts their
well-known look get an editorial hue instead. They skip the reference blend
(amount = 1, the film's own neutral filters) and add an M/Y shift solved so
18% gray lands on that CIELAB hue at the usual chroma target:

    appliedCC = filmCC + hueShiftCC,  hueShiftCC = [0, m, y]

The upstream scalar mid-gray print-exposure normalization remains active.
"""
from __future__ import annotations

from dataclasses import replace
import math

import numpy as np

from pipeline.common import UPSTREAM, sha256
from spektrafilm.runtime.params_builder import digest_params, init_params
from spektrafilm.runtime.pipeline import SimulationPipeline
from spektrafilm.utils.io import read_neutral_print_filters
from spektrafilm_lut_creator.builders import BundleBuilder
from spektrafilm_lut_creator.color_spaces import decode_cctf, encode_cctf, get

METHOD = 'spektrafilm-print-reference-blend-v1'
SUFFIX = '__filmcast'
NUMBER_OFFSET = 1000
REFERENCE_FILM = 'kodak_portra_400'
DATABASE_PATH = UPSTREAM / 'src/spektrafilm/data/filters/neutral_print_filters.json'

# The "30%" slot in the UI is filled with a per-film/paper amount: the
# smallest correction cut that brings the rendered 18% gray (sRGB, D65) to a
# CIELAB chroma target. A shared percentage gives anything from an invisible
# tint (Gold 200) to a heavy cast (C200 at C* 25-39), because the CC gap to the
# reference pack differs a lot between films. Tungsten cine stocks get a
# stronger target; their cool cast is the point. The solved amount is stored
# with every variant and shown in the UI.
AMOUNT_POLICY = 'chroma-target'
TARGET_CHROMA_DEFAULT = 6.0
TARGET_CHROMA = {'kodak_vision3_200t': 10.0, 'kodak_vision3_500t': 10.0,
                 # Known as the most neutral Portra / daylight-balanced cine stocks: keep only a hint.
                 'kodak_portra_160': 2.0, 'kodak_vision3_50d': 2.0, 'kodak_vision3_250d': 2.0}
MIN_AMOUNT = 0.2
# Editorial cast direction (CIELAB hue, degrees) for films whose database
# direction is the opposite of their known look (database hue in brackets):
#   C200 green-cyan (orange-yellow 51-63), X-Tra 400 green (orange 50-64),
#   Gold 200 warm golden yellow and Ultramax 400 warm orange-yellow (pink-red),
#   Vision3 tungsten stocks in daylight cyan-blue (green-cyan 168-202).
TARGET_HUE = {'fujifilm_c200': 180.0, 'fujifilm_xtra_400': 160.0,
              'kodak_gold_200': 75.0, 'kodak_ultramax_400': 60.0,
              'kodak_vision3_200t': 215.0, 'kodak_vision3_500t': 215.0}
DIRECTION_POLICY_DATA = 'film-data'
DIRECTION_POLICY_HUE = 'editorial-hue'
HUE_FORMULA = 'appliedCC = filmCC + hueShiftCC'

LIMITATIONS = [
    'Experimental Film Lab variant, not an upstream spektrafilm preset.',
    'The cast direction comes from the calibrated filter database; it is not tuned to a remembered film colour.',
    'The amount is solved per film and paper so 18% gray reaches a CIELAB chroma target; the targets are an editorial choice, not a measured lab recipe.',
    'Films listed in TARGET_HUE (C200, X-Tra 400, Gold 200, Ultramax 400, Vision3 200T/500T) use an editorial cast hue instead of the database direction; the hue is a chosen look, not a measurement.',
    'Cast strength is matched only at mid-gray; the cast direction still differs by film and paper, including pink/magenta casts.',
    'Mid-gray print exposure normalization stays on, so brightness is aligned but colour is not neutralized.',
]


def _amount(value):
    value = float(value)
    if not math.isfinite(value) or not 0. <= value <= 1.:
        raise ValueError('Film cast amount must be finite and within 0..1')
    return value


def _database():
    return read_neutral_print_filters()


def gray_chroma(rgb):
    """CIELAB C* (D65) of one encoded sRGB triple."""
    import colour
    lab = colour.XYZ_to_Lab(colour.sRGB_to_XYZ(np.clip(np.asarray(rgb, dtype=float), 0., 1.)))
    return float(np.hypot(lab[1], lab[2])), float(np.degrees(np.arctan2(lab[2], lab[1])) % 360.)


def target_chroma(film_id):
    return TARGET_CHROMA.get(film_id, TARGET_CHROMA_DEFAULT)


def target_hue(film_id):
    return TARGET_HUE.get(film_id)


def _shift(value):
    m, y = (float(v) for v in value)
    if not (math.isfinite(m) and math.isfinite(y) and abs(m) <= 30. and abs(y) <= 30.):
        raise ValueError('Film cast hue shift must be finite and within +-30 CC')
    return m, y


def measure_cast(spec, amount, shift=(0., 0.)):
    """CIELAB chroma and hue of the rendered 18% gray at one blend amount and M/Y shift."""
    from pipeline.common import vlog_encode
    gray = vlog_encode(np.array([[0.184, 0.184, 0.184]]))
    return gray_chroma(run_blend_reference(spec, gray, amount, shift)[0])


def solve_hue_shift(spec):
    """M/Y shift (Kodak CC, 0.1 CC steps) that puts 18% gray on the editorial hue at the chroma target.

    Gray a*/b* respond almost linearly to small filter shifts, so a Newton
    step with a central-difference Jacobian converges in a couple of steps.
    Returns ((m, y), chroma, hue).
    """
    hue, chroma = target_hue(spec.film_profile), target_chroma(spec.film_profile)
    if hue is None: raise ValueError('No editorial hue for this film')
    def ab(m, y):
        c, h = measure_cast(spec, 1., (m, y))
        return np.array([c * math.cos(math.radians(h)), c * math.sin(math.radians(h))])
    goal = chroma * np.array([math.cos(math.radians(hue)), math.sin(math.radians(hue))])
    step = 1.
    jac = np.column_stack([(ab(step, 0.) - ab(-step, 0.)) / (2 * step), (ab(0., step) - ab(0., -step)) / (2 * step)])
    x = np.zeros(2)
    for _ in range(8):
        r = ab(*x) - goal
        if math.hypot(*r) < 0.05: break
        x = x - np.linalg.solve(jac, r)
    shift = _shift(np.round(x, 1) + 0.)  # + 0. turns -0.0 into 0.0
    c, h = measure_cast(spec, 1., shift)
    return shift, c, h


def solve_amount(spec):
    """Smallest correction cut that brings 18% gray to the chroma target.

    The cast grows almost linearly with (1 - amount), so a secant search
    converges in a few steps. Returns (amount, chroma, hue) at whole-percent precision.
    The reference film cannot change colour, so it gets MIN_AMOUNT.
    """
    target = target_chroma(spec.film_profile)
    measure = lambda a: measure_cast(spec, a)[0]
    if spec.film_profile == REFERENCE_FILM:
        amount = MIN_AMOUNT
    else:
        c1, c0 = measure(1.), measure(MIN_AMOUNT)
        if c0 <= target: amount = MIN_AMOUNT
        else:
            lo, hi, clo, chi = MIN_AMOUNT, 1., c0, c1
            for _ in range(8):
                amount = hi - (chi - target) * (hi - lo) / (chi - clo) if chi != clo else (lo + hi) / 2
                amount = min(max(amount, lo), hi)
                c = measure(amount)
                if abs(c - target) < 0.05: break
                if c > target: lo, clo = amount, c
                else: hi, chi = amount, c
    # Whole percent, so the UI label is the exact blend ratio.
    amount = round(amount, 2)
    chroma, hue = measure_cast(spec, amount)
    return amount, chroma, hue


def blend_settings(film_profile, print_profile, amount, shift=(0., 0.)):
    """JSON-safe recipe with the film, reference and applied CC values."""
    amount, shift = _amount(amount), _shift(shift)
    params = init_params(film_profile=film_profile, print_profile=print_profile)
    if params.film.info.type != 'negative' or params.print.info.stage != 'printing':
        raise ValueError('Film cast variants require negative-film printing')
    illuminant = params.enlarger.illuminant
    table = _database()[print_profile][illuminant]
    film_cc = np.asarray(table[film_profile], dtype=float)
    reference_cc = np.asarray(table[REFERENCE_FILM], dtype=float)
    if film_cc.shape != (3,) or reference_cc.shape != (3,) or not (np.isfinite(film_cc).all() and np.isfinite(reference_cc).all()):
        raise ValueError('Invalid neutral print filter database entry')
    # The reference film remains exactly unchanged at every blend amount.
    # Avoid introducing rounding noise by blending two identical values.
    applied = (film_cc.copy() if np.array_equal(film_cc, reference_cc)
               else amount * film_cc + (1. - amount) * reference_cc)
    editorial = shift != (0., 0.)
    if editorial:
        if amount != 1.: raise ValueError('An editorial hue shift is applied to the film\'s own filters only')
        applied = film_cc + np.array([0., *shift])
    settings = {'method': METHOD, 'amount': amount, 'percent': int(math.floor(amount * 100 + 0.5)), 'experimental': True,
            'film': film_profile, 'paper': print_profile, 'illuminant': illuminant,
            'channelOrder': ['C', 'M', 'Y'], 'units': 'Kodak CC; 100 CC = 1.0 filter optical density',
            'referenceFilm': REFERENCE_FILM,
            'baseline': 'Reference film neutral filters on the same paper (fixed lab pack)',
            'filmCC': film_cc.tolist(), 'referenceCC': reference_cc.tolist(), 'appliedCC': applied.tolist(),
            'formula': 'appliedCC = amount * filmCC + (1 - amount) * referenceCC',
            'databaseSha256': sha256(DATABASE_PATH), 'databaseReload': False,
            'normalizePrintExposure': True, 'filterShifts': {'M': 0, 'Y': 0},
            'imageStatistics': False, 'outputRgbMixing': False, 'notes': LIMITATIONS}
    if editorial:
        settings.update(formula=HUE_FORMULA, directionPolicy=DIRECTION_POLICY_HUE,
                        targetHue=target_hue(film_profile), hueShiftCC=[0., *shift])
    return settings


def _configure(params, settings):
    params.settings.neutral_print_filters_from_database = False
    c, m, y = settings['appliedCC']
    params.enlarger.c_filter_neutral = c
    params.enlarger.m_filter_neutral = m
    params.enlarger.y_filter_neutral = y
    params.enlarger.m_filter_shift = 0.
    params.enlarger.y_filter_shift = 0.
    params.enlarger.normalize_print_exposure = True
    return params


class FilmCastBundleBuilder(BundleBuilder):
    """Bake the ordinary spectral chain with blended print filters."""

    def __init__(self, spec, amount, shift=(0., 0.)):
        super().__init__(spec)
        self.amount, self.shift = _amount(amount), _shift(shift)

    def _make_pipeline(self, spec, in_entry, out_entry, print_stock):
        settings = blend_settings(spec.film_profile, print_stock, self.amount, self.shift)
        params = init_params(film_profile=spec.film_profile, print_profile=print_stock)
        params.debug.lut_mode = True
        params.io.input_color_space = in_entry.primaries
        params.io.output_color_space = out_entry.primaries
        params.io.input_cctf_decoding = False
        params.io.output_cctf_encoding = False
        params.io.input_gamut_compress = spec.input_gamut_compress
        params.io.output_gamut_compress = spec.output_gamut_compress
        params = _configure(params, settings)
        return SimulationPipeline(digest_params(params))

    def build(self):
        if self.spec.topology != '1lut':
            raise ValueError('Film cast variants currently support combined 1lut only')
        bundle = super().build()
        snapshot = dict(bundle.meta.params_snapshot)
        for paper, value in snapshot.items():
            snapshot[paper] = {**value, 'filmCast': blend_settings(self.spec.film_profile, paper, self.amount, self.shift)}
        bundle.meta = replace(bundle.meta, params_snapshot=snapshot)
        return bundle


def run_blend_reference(spec, points, amount, shift=(0., 0.)):
    """Evaluate off-grid samples independently of the builder and baked cube."""
    paper = spec.print_profiles[0]
    settings = blend_settings(spec.film_profile, paper, amount, shift)
    in_entry, out_entry = get(spec.input_color_space), get(spec.output_color_space)
    params = init_params(film_profile=spec.film_profile, print_profile=paper)
    params.debug.lut_mode = True
    params.io.input_color_space = in_entry.primaries
    params.io.output_color_space = out_entry.primaries
    params.io.input_cctf_decoding = False
    params.io.output_cctf_encoding = False
    params.io.input_gamut_compress = spec.input_gamut_compress
    params.io.output_gamut_compress = spec.output_gamut_compress
    pipeline = SimulationPipeline(digest_params(_configure(params, settings)))
    frame = spec.bake_frame()
    samples = np.asarray(points, dtype=np.float32).reshape(-1, 3)
    linear = (decode_cctf(samples, spec.input_color_space) * frame.input_gain).astype(np.float32)
    out = np.asarray(pipeline.process(linear.reshape(1, -1, 3)), dtype=float).reshape(-1, 3)
    return np.clip(encode_cctf(out * frame.output_gain, spec.output_color_space), 0., 1.)
