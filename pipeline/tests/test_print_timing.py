import numpy as np
import pytest

from pipeline.common import CONFIG
from pipeline.print_timing import (GRID_CC, build_tables, evaluate, lagrange, pack, run_shift_reference,
                                   shift_weights, unpack)
from spektrafilm_lut_creator.bundles import BundleSpec
from spektrafilm_lut_creator.qa.evaluators import apply_tetrahedral


def spec(film='kodak_vision3_500t', paper='kodak_2383'):
    return BundleSpec(film_profile=film, print_profiles=(paper,), input_color_space=CONFIG['input'],
                      output_color_space=CONFIG['output'], topology=CONFIG['topology'], resolution=CONFIG['resolution'],
                      target=CONFIG['target'], stops_above_midgray=CONFIG['stops_above_midgray'],
                      output_gamut_compress=CONFIG['output_gamut_compress'])


def test_weights_are_exact_at_nodes_and_sum_to_one():
    for t, node in [(-1., 0), (0., 1), (1., 2)]:
        assert np.allclose(lagrange(t), np.eye(3)[node])
    for m, y in [(-17., 4.), (12.5, -29.), (0., 0.)]:
        assert abs(shift_weights(m, y).sum() - 1) < 1e-12
    with pytest.raises(ValueError):
        shift_weights(31., 0.)


@pytest.fixture(scope='module')
def baked():
    s = spec()
    wire, a, b = build_tables(s, n=17)
    header = {'method': 'test', 'resolution': 17}
    return s, wire, a, b, unpack(pack(header, a, b))


def test_pack_round_trip_is_uint16_exact(baked):
    _, _, a, b, (header, a2, b2) = baked
    assert header['resolution'] == 17
    assert np.abs(a2 - a).max() <= 0.5 / 65535 + 1e-12 and np.abs(b2 - b).max() <= 0.5 / 65535 + 1e-12


def test_chain_tracks_direct_engine_between_and_at_nodes(baked):
    s, wire, a, b, _ = baked
    points = np.random.default_rng(5).random((512, 3))
    for m, y in [(0., 0.), (-15., 15.), (GRID_CC[2], GRID_CC[0])]:
        chain = evaluate(a, b, wire, points, m, y, apply_tetrahedral)
        error = np.abs(chain - run_shift_reference(s, points, m, y)).max(axis=1)
        assert error.mean() < 0.01 and np.percentile(error, 99) < 0.05  # coarse 17^3 test resolution


def test_filter_shift_moves_gray_in_the_darkroom_direction():
    s = spec('kodak_portra_400', 'fujifilm_crystal_archive_typeii')
    from pipeline.common import vlog_encode
    gray = vlog_encode(np.array([[0.184] * 3]))
    neutral = run_shift_reference(s, gray, 0, 0)[0]
    more_y, more_m = run_shift_reference(s, gray, 0, 20)[0], run_shift_reference(s, gray, 20, 0)[0]
    assert more_y[2] - more_y[0] > neutral[2] - neutral[0]  # more yellow filter -> bluer print
    assert more_m[1] - (more_m[0] + more_m[2]) / 2 > neutral[1] - (neutral[0] + neutral[2]) / 2  # more magenta -> greener
