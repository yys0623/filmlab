"""Interactive print filter timing (Y/M CC shift) for the web app.

spektrafilm's enlarger has Y/M filter shifts in Kodak CC, applied on top of
the database neutral filters (the GUI's "Print Y/M filter shift"). Their
effect is spectral, so it cannot be reproduced by adding a constant to a
finished LUT. Instead the chain is split at the paper exposure:

    A_(m,y): V-Log RGB -> log10 paper exposure (film exposure, development,
             enlarger with neutral filters + shift (m, y))
    B:       log10 paper exposure -> sRGB (paper development + scan)

B does not depend on the enlarger filters. A is baked on a 3 x 3 grid of
shifts (-30, 0, +30 CC per filter) and blended per element with biquadratic
Lagrange weights, which keeps the interpolation error below ~0.4 of an 8-bit
level against the direct engine. The browser composes
STD -> camera adapter -> sum(w * A) -> B into one 33^3 cube.
"""
from __future__ import annotations

import json
import struct

import numpy as np

from spektrafilm.runtime.params_builder import digest_params, init_params
from spektrafilm.runtime.pipeline import SimulationPipeline
from spektrafilm_lut_creator.color_spaces import decode_cctf, encode_cctf, get
from spektrafilm_lut_creator.grid import cube_grid

METHOD = 'spektrafilm-print-filter-timing-v1'
GRID_CC = (-30.0, 0.0, 30.0)
RESOLUTION = 33
WIRE_MARGIN = 0.1  # log10 E padding on both ends of the measured span
MAGIC = b'SFPT1\n'
QA_SHIFTS = ((0., 0.), (-15., 15.), (15., -15.), (-7., 3.), (25., 25.))


def lagrange(t):
    """Quadratic weights for nodes -1, 0, +1 at t in [-1, 1]."""
    return np.array([t * (t - 1) / 2, (1 - t) * (1 + t), t * (t + 1) / 2])


def shift_weights(m, y):
    """3 x 3 weights, index [m_node, y_node]."""
    span = GRID_CC[2]
    if not (abs(m) <= span and abs(y) <= span): raise ValueError('Filter shift outside the baked range')
    return np.outer(lagrange(m / span), lagrange(y / span))


def make_pipeline(spec, m=0., y=0.):
    params = init_params(film_profile=spec.film_profile, print_profile=spec.print_profiles[0])
    params.debug.lut_mode = True
    i, o = get(spec.input_color_space), get(spec.output_color_space)
    params.io.input_color_space = i.primaries
    params.io.output_color_space = o.primaries
    params.io.input_cctf_decoding = False
    params.io.output_cctf_encoding = False
    params.io.input_gamut_compress = spec.input_gamut_compress
    params.io.output_gamut_compress = spec.output_gamut_compress
    params = digest_params(params)  # database neutral filters for this film/paper
    params.enlarger.m_filter_shift = float(m)
    params.enlarger.y_filter_shift = float(y)
    return SimulationPipeline(params)


def _linear(spec, encoded):
    frame = spec.bake_frame()
    samples = np.asarray(encoded, dtype=np.float32).reshape(-1, 3)
    return (decode_cctf(samples, spec.input_color_space) * frame.input_gain).astype(np.float32).reshape(1, -1, 3)


def _encode_output(spec, linear):
    frame = spec.bake_frame()
    out = np.asarray(linear, dtype=float).reshape(-1, 3) * frame.output_gain
    return np.clip(encode_cctf(out, spec.output_color_space), 0., 1.)


def run_shift_reference(spec, encoded, m, y):
    """Direct engine output for encoded V-Log samples at one filter shift."""
    return _encode_output(spec, make_pipeline(spec, m, y).process(_linear(spec, encoded)))


def build_tables(spec, n=RESOLUTION):
    """Return (wire, A[3,3,n,n,n,3], B[n,n,n,3]); tables use .cube order [b,g,r]."""
    pipes = {(a, b): make_pipeline(spec, GRID_CC[a], GRID_CC[b]) for a in range(3) for b in range(3)}
    grid = cube_grid(n)
    log_e = {k: np.asarray(p.process(_linear(spec, grid), collect='log_e_print'), dtype=float).reshape(-1, 3)
             for k, p in pipes.items()}
    lo = min(v.min() for v in log_e.values()) - WIRE_MARGIN
    hi = max(v.max() for v in log_e.values()) + WIRE_MARGIN
    wire = {'min': float(np.floor(lo * 1000) / 1000), 'max': float(np.ceil(hi * 1000) / 1000)}
    span = wire['max'] - wire['min']
    a = np.zeros((3, 3, n, n, n, 3))
    for (i, j), v in log_e.items():
        a[i, j] = ((v - wire['min']) / span).reshape(n, n, n, 3)
    if a.min() < 0 or a.max() > 1: raise ValueError('Paper exposure outside its wire')
    code = (wire['min'] + grid * span).astype(np.float32).reshape(1, -1, 3)
    raw = pipes[1, 1].process(code, inject='log_e_print', collect='rgb_out')
    b = _encode_output(spec, raw).reshape(n, n, n, 3)
    return wire, a, b


def quantize(table):
    return np.round(np.clip(table, 0., 1.) * 65535.).astype('<u2')


def dequantize(data):
    return data.astype(float) / 65535.


def pack(header, a, b):
    """Binary pack: MAGIC, u32 header length, UTF-8 JSON header, u16 tables (A[3][3], B)."""
    head = json.dumps(header, sort_keys=True, separators=(',', ':')).encode()
    return MAGIC + struct.pack('<I', len(head)) + head + quantize(a).tobytes() + quantize(b).tobytes()


def unpack(data):
    if not data.startswith(MAGIC): raise ValueError('Not a print timing pack')
    (length,) = struct.unpack_from('<I', data, len(MAGIC))
    start = len(MAGIC) + 4
    header = json.loads(data[start:start + length])
    n = header['resolution']
    body = np.frombuffer(data, dtype='<u2', offset=start + length)
    size = n ** 3 * 3
    if body.size != 10 * size: raise ValueError('Truncated print timing pack')
    a = dequantize(body[:9 * size]).reshape(3, 3, n, n, n, 3)
    b = dequantize(body[9 * size:]).reshape(n, n, n, 3)
    return header, a, b


def evaluate(a, b, wire, encoded, m, y, tetrahedral):
    """Browser-equivalent chain for encoded V-Log samples."""
    w = shift_weights(m, y)
    combined = np.tensordot(w, a, axes=([0, 1], [0, 1]))
    return tetrahedral(b, np.clip(tetrahedral(combined, encoded), 0., 1.))
