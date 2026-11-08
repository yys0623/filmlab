import numpy as np
import pytest

from pipeline.common import CONFIG, vlog_encode
from pipeline.print_blend import (REFERENCE_FILM, FilmCastBundleBuilder, blend_settings,
                                  run_blend_reference, measure_cast, solve_amount, solve_hue_shift, target_chroma,
                                  target_hue, gray_chroma, MIN_AMOUNT, HUE_FORMULA)
from pipeline.generate_film_cast import plan
from spektrafilm_lut_creator.bundles import BundleSpec
from spektrafilm_lut_creator.builders import BundleBuilder
from spektrafilm_lut_creator.qa.reference import run_pipeline_at
from spektrafilm_lut_creator.qa.evaluators import apply_tetrahedral

PAPER = 'fujifilm_crystal_archive_typeii'
PAPERS = (PAPER, 'kodak_2383', 'kodak_2393', 'kodak_ektacolor_edge', 'kodak_endura_premier',
          'kodak_portra_endura', 'kodak_supra_endura', 'kodak_ultra_endura')


def spec(film, paper=PAPER):
    return BundleSpec(film_profile=film, print_profiles=(paper,), input_color_space=CONFIG['input'],
                      output_color_space=CONFIG['output'], topology=CONFIG['topology'], resolution=CONFIG['resolution'],
                      target=CONFIG['target'], stops_above_midgray=CONFIG['stops_above_midgray'],
                      output_gamut_compress=CONFIG['output_gamut_compress'])


def test_blend_formula_and_endpoints():
    settings = blend_settings('kodak_gold_200', PAPER, 0.25)
    film, ref, applied = map(np.asarray, (settings['filmCC'], settings['referenceCC'], settings['appliedCC']))
    assert np.allclose(applied, 0.25 * film + 0.75 * ref)
    assert settings['referenceFilm'] == REFERENCE_FILM
    assert np.allclose(blend_settings('kodak_gold_200', PAPER, 1.)['appliedCC'], film)
    assert np.allclose(blend_settings('kodak_gold_200', PAPER, 0.)['appliedCC'], ref)
    # Never an unfiltered enlarger: every applied value stays between film and reference.
    assert np.all(applied >= np.minimum(film, ref) - 1e-12) and np.all(applied <= np.maximum(film, ref) + 1e-12)
    with pytest.raises(ValueError):
        blend_settings('kodak_gold_200', PAPER, 1.2)


def test_amount_one_reproduces_the_base_look_exactly():
    s = spec('kodak_gold_200')
    base = BundleBuilder(s).build().luts[0][1].table
    cast = FilmCastBundleBuilder(s, 1.).build().luts[0][1].table
    assert np.array_equal(base, cast)
    points = np.random.default_rng(1).random((64, 3))
    assert np.array_equal(run_blend_reference(s, points, 1.), run_pipeline_at(s, BundleBuilder(s).build(), 0, points))


@pytest.mark.parametrize('film', ['kodak_portra_800', 'kodak_verita_200d', 'kodak_vision3_50d'])
def test_amount_is_solved_to_the_gray_chroma_target(film):
    s = spec(film)
    amount, chroma, hue = solve_amount(s)
    assert MIN_AMOUNT <= amount < 1
    assert abs(chroma - target_chroma(film)) < 0.6  # amount is rounded to whole percent
    planned_amount, planned_chroma, planned_hue, shift = plan({'film': film, 'paper': PAPER})
    assert shift == (0., 0.) and (planned_amount, planned_chroma, planned_hue) == (amount, chroma, hue)
    settings = blend_settings(film, PAPER, amount)
    assert settings['percent'] == round(amount * 100)
    assert np.allclose(settings['appliedCC'], amount * np.array(settings['filmCC']) + (1 - amount) * np.array(settings['referenceCC']))
    assert (chroma, hue) == measure_cast(s, amount)


def test_a_film_that_never_reaches_the_target_uses_the_minimum_amount():
    amount, chroma, _ = solve_amount(spec('kodak_gold_200'))
    assert amount == MIN_AMOUNT and chroma <= target_chroma('kodak_gold_200')


def test_fixed_thirty_percent_was_much_stronger_for_c200():
    s = spec('fujifilm_c200')
    assert measure_cast(s, 0.3)[0] > 3 * solve_amount(s)[1]


@pytest.mark.parametrize('paper', PAPERS)
def test_reference_film_thirty_percent_is_exactly_the_base_look(paper):
    settings = blend_settings(REFERENCE_FILM, paper, 0.3)
    assert settings['appliedCC'] == settings['filmCC'] == settings['referenceCC']
    s = spec(REFERENCE_FILM, paper)
    base = BundleBuilder(s).build().luts[0][1].table
    cast = FilmCastBundleBuilder(s, 0.3).build().luts[0][1].table
    assert np.array_equal(cast, base)


@pytest.mark.parametrize('film,paper', [
    (film, paper)
    for film in (REFERENCE_FILM, 'kodak_ektar_100', 'kodak_portra_160')
    for paper in PAPERS
])
def test_previous_thirty_one_exclusions_are_available(film, paper):
    amount, chroma, hue, shift = plan({'film': film, 'paper': paper})
    assert MIN_AMOUNT <= amount < 1 and shift == (0., 0.)
    assert np.isfinite(chroma) and np.isfinite(hue)


def _hue_distance(a, b):
    return abs((a - b + 180.) % 360. - 180.)


@pytest.mark.parametrize('paper', PAPERS)
def test_c200_uses_its_editorial_green_cyan_hue(paper):
    s = spec('fujifilm_c200', paper)
    # The database direction would be orange-yellow; the editorial hue replaces it.
    assert _hue_distance(measure_cast(s, solve_amount(s)[0])[1], 60.) < 20.
    amount, chroma, hue, shift = plan({'film': 'fujifilm_c200', 'paper': paper})
    assert amount == 1. and shift != (0., 0.) and all(abs(v) <= 30. for v in shift)
    assert abs(chroma - target_chroma('fujifilm_c200')) < 0.3
    assert _hue_distance(hue, target_hue('fujifilm_c200')) < 2.
    assert (chroma, hue) == measure_cast(s, 1., shift)
    settings = blend_settings('fujifilm_c200', paper, 1., shift)
    assert settings['formula'] == HUE_FORMULA and settings['directionPolicy'] == 'editorial-hue'
    assert settings['hueShiftCC'] == [0., *shift]
    assert np.allclose(settings['appliedCC'], np.array(settings['filmCC']) + np.array([0., *shift]))


def test_hue_shift_needs_the_films_own_filters():
    with pytest.raises(ValueError):
        blend_settings('fujifilm_c200', PAPER, 0.8, (5., 3.))
    with pytest.raises(ValueError):
        blend_settings('fujifilm_c200', PAPER, 1., (40., 0.))
    with pytest.raises(ValueError):
        solve_hue_shift(spec('kodak_portra_800'))


def test_shifted_cube_matches_the_independent_reference():
    s = spec('fujifilm_c200')
    shift = solve_hue_shift(s)[0]
    cube = FilmCastBundleBuilder(s, 1., shift).build().luts[0][1].table
    base = BundleBuilder(s).build().luts[0][1].table
    assert not np.array_equal(cube, base)
    points = np.random.default_rng(3).random((256, 3))
    direct = run_blend_reference(s, points, 1., shift)
    assert np.max(np.abs(apply_tetrahedral(cube, points) - direct)) < 0.02


@pytest.mark.parametrize('film', ['fujifilm_xtra_400', 'kodak_gold_200', 'kodak_ultramax_400', 'kodak_vision3_200t', 'kodak_vision3_500t'])
def test_other_editorial_hue_films_reach_their_hue(film):
    amount, chroma, hue, shift = plan({'film': film, 'paper': PAPER})
    assert amount == 1. and shift != (0., 0.) and all(abs(v) <= 30. for v in shift)
    assert abs(chroma - target_chroma(film)) < 0.3
    assert _hue_distance(hue, target_hue(film)) < 2.


@pytest.mark.parametrize('film', ['kodak_portra_160', 'kodak_vision3_50d', 'kodak_vision3_250d'])
def test_neutral_known_films_keep_only_a_hint_of_cast(film):
    amount, chroma, _, shift = plan({'film': film, 'paper': PAPER})
    assert shift == (0., 0.) and MIN_AMOUNT <= amount < 1
    assert target_chroma(film) == 2. and abs(chroma - 2.) < 0.6
