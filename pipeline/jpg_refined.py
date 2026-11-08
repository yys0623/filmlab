"""Opt-in v3 refinement: a smooth chroma shoulder near the sRGB boundary.

All upstream v3 colour, neutral, lightness and gain calculations are inherited
unchanged. Only the final radial gamut mapper differs. This is an engineering
rendering choice, not a measured film, paper or camera transform.
"""
from __future__ import annotations

import numpy as np

from pipeline.jpg import JpgToneProtection
from pipeline.research import oklab_to_linear, _M1_INV, _M2_INV

METHOD_ID = 'legacy-v3-soft-gamut-v1'
DEFAULT_KNEE = .90
BOUNDARY_ITERATIONS = 24


def soft_chroma_ratio(ratio, knee=DEFAULT_KNEE):
    """C1 monotone shoulder: identity to knee, asymptotically approach 1."""
    if not np.isfinite(knee) or not 0. < knee < 1.:
        raise ValueError('Gamut knee must be finite and strictly between 0 and 1')
    ratio = np.asarray(ratio, dtype=float)
    if not np.isfinite(ratio).all() or np.any(ratio < 0):
        raise ValueError('Expected nonnegative finite chroma ratios')
    excess = np.maximum(ratio - knee, 0.)
    shoulder = knee + (1. - knee) * excess / (excess + 1. - knee)
    return np.where(ratio <= knee, ratio, shoulder)


def _first_exit_brackets(lab, upper):
    """Find the first exit, including rays with disconnected blue re-entry.

    Each linear RGB channel along fixed-L, scaled-ab is cubic in scale t.
    Partition [0, upper] at every real derivative root of all three cubics.
    Every channel is monotone within a partition, so an excursion cannot be
    hidden by a later re-entry. The first out-of-range partition endpoint
    brackets the boundary connected to neutral.
    """
    base = lab[:, :1] * _M2_INV[:, 0]
    direction = lab[:, 1:] @ _M2_INV[:, 1:].T
    c0 = base**3 @ _M1_INV.T
    c1 = (3 * base**2 * direction) @ _M1_INV.T
    c2 = (3 * base * direction**2) @ _M1_INV.T
    c3 = direction**3 @ _M1_INV.T
    aa, bb, cc = 3*c3, 2*c2, c1
    scale = np.maximum.reduce([abs(aa), abs(bb), abs(cc)])
    quadratic = abs(aa) > 1e-14 * scale
    discriminant = bb**2 - 4*aa*cc
    real = quadratic & (discriminant >= 0.)
    root_disc = np.sqrt(np.maximum(discriminant, 0.))
    q = -.5 * (bb + np.copysign(root_disc, bb))
    first = np.divide(q, aa, out=np.full_like(aa, np.inf), where=real)
    second = np.divide(cc, q, out=np.full_like(aa, np.inf), where=real & (q != 0.))
    linear = ~quadratic & (abs(bb) > 1e-14 * scale)
    first = np.where(linear, np.divide(-cc, bb, out=np.full_like(bb, np.inf), where=linear), first)
    roots = np.concatenate([first, second], axis=1)
    roots = np.where(np.isfinite(roots) & (roots > 0.) & (roots < upper), roots, upper)
    points = np.sort(np.column_stack([roots, np.full(len(lab), upper)]), axis=1)
    low = np.zeros(len(lab)); high = np.full(len(lab), upper)
    pending = np.ones(len(lab), dtype=bool)
    for t in points.T:
        v = ((c3*t[:, None] + c2)*t[:, None] + c1)*t[:, None] + c0
        outside = (v.min(axis=1) < 0.) | (v.max(axis=1) > 1.)
        hit = pending & outside
        high[hit] = t[hit]
        low[pending & ~outside] = t[pending & ~outside]
        pending[hit] = False
    return low, high, ~pending, (c0, c1, c2, c3)


def soft_gamut_map(lab, *, knee=DEFAULT_KNEE):
    """Fit to linear sRGB, preserving requested OKLab L and hue.

    Chroma up to knee*Cmax is unchanged. Cmax is the first boundary connected
    to neutral, never a later re-entry into sRGB along the same ray. Cubic
    critical points bracket that first exit before bisection. There is no
    film-specific coefficient or image statistic. Endpoints have zero radial
    chroma capacity and are handled explicitly.
    """
    soft_chroma_ratio(0., knee)  # validate even for empty/neutral inputs
    lab = np.asarray(lab, dtype=float)
    if lab.ndim < 1 or lab.shape[-1] != 3 or not np.isfinite(lab).all():
        raise ValueError('Expected finite OKLab triples')
    shape = lab.shape
    flat = lab.reshape(-1, 3)
    if np.any((flat[:, 0] < 0.) | (flat[:, 0] > 1.)):
        raise ValueError('Expected OKLab lightness in 0..1')
    rgb = oklab_to_linear(flat)
    neutral = np.linalg.norm(flat[:, 1:], axis=1) < 1e-7
    interior = (flat[:, 0] > 0.) & (flat[:, 0] < 1.) & ~neutral
    # Search all interior rays: testing only the expanded endpoint can miss
    # an earlier excursion followed by a valid re-entry in blue hue slices.
    indices = np.flatnonzero(interior)
    if len(indices):
        chosen = flat[indices].copy()
        low, high, near, coefficients = _first_exit_brackets(chosen, 1. / knee)
        indices = indices[near]
        chosen = chosen[near]
        lo, hi = low[near], high[near]
        c0, c1, c2, c3 = (c[near] for c in coefficients)
        for _ in range(BOUNDARY_ITERATIONS):
            mid = (lo + hi) * .5
            t = mid[:, None]
            probe_rgb = ((c3*t + c2)*t + c1)*t + c0
            valid = (probe_rgb.min(axis=1) >= 0.) & (probe_rgb.max(axis=1) <= 1.)
            lo = np.where(valid, mid, lo)
            hi = np.where(valid, hi, mid)
        # lo is Cmax/C. The algebra below avoids reciprocal overflow at the
        # degenerate near-black/near-white limit Cmax -> 0.
        width = 1. - knee
        excess = np.maximum(1. - knee * lo, 0.)
        scale = lo * (knee + width * excess / (excess + width * lo))
        chosen[:, 1:] *= scale[:, None]
        rgb[indices] = oklab_to_linear(chosen)
    rgb[neutral] = flat[neutral, :1] ** 3
    rgb[flat[:, 0] <= 0.] = 0.
    rgb[flat[:, 0] >= 1.] = 1.
    # Only numerical roundoff remains: the mapping itself was constrained
    # in linear RGB, rather than repaired by a post-hoc channel clip.
    return np.clip(rgb, 0., 1.).reshape(shape)


class RefinedJpgToneProtection(JpgToneProtection):
    def __init__(self, raw_render, *, digital=False, knee=DEFAULT_KNEE):
        soft_chroma_ratio(0., knee)
        self.knee = float(knee)
        super().__init__(raw_render, digital=digital)

    def map_gamut(self, lab):
        return soft_gamut_map(lab, knee=self.knee)

    def metadata(self):
        original = super().metadata()
        return {
            **original,
            'method': METHOD_ID,
            'parentMethod': original['method'],
            'gamutMapping': 'C1 chroma shoulder near sRGB boundary at fixed OKLab lightness and hue',
            'gamutKnee': self.knee,
            'gamutBoundaryIterations': BOUNDARY_ITERATIONS,
            'gamutBoundarySearch': 'First exit connected to neutral: partition at all real RGB cubic derivative roots, then bisect the first out-of-range interval. Handles disconnected blue re-entry.',
            'formula': 'r=C/Cmax(L,h); f=r for r<=k; otherwise f=k+(1-k)*(r-k)/(r-k+1-k); C_out=Cmax*f',
            'kneeRationale': f'A {self.knee:.2f} knee reduces chroma at the first gamut boundary by {(1-self.knee)*50:.3g}%; colors below {self.knee*100:.3g}% of that radial limit remain unchanged. This is a shared design choice, not a measured film parameter.',
            'firstConnectedBoundaryChromaReductionPercent': (1. - self.knee) * 50.,
            'chromaBoundScope': 'The 5% bound at knee .90 refers to the first neutral-connected boundary; later in-gamut re-entry islands can receive a larger reduction.',
            'gamutGeometryReference': 'https://bottosson.github.io/posts/gamutclipping/',
            'inheritedToneAndChromaCalculationsUnchanged': True,
            'changesInGamutColorsNearBoundary': True,
            'limitations': original['limitations'] + [
                'Already clipped native film/LUT detail cannot be recovered.',
                'The soft shoulder also changes near-boundary colors that were already in gamut.',
                'Quantized 8-bit or 33-grid outputs can still reach channel endpoints; no guarantee of eliminating all clipping.',
            ],
        }
