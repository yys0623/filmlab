"""Verify actual direct-scan behavior, paper independence and export semantics."""
import json
from dataclasses import replace

import numpy as np
import pytest

from pipeline.common import CONFIG, PUBLIC, read_cube, std_to_vlog
from pipeline.slide import SlideBundleBuilder, run_slide_reference
from spektrafilm_lut_creator.bundles import BundleSpec
from spektrafilm_lut_creator.color_spaces import get
from spektrafilm_lut_creator.qa.evaluators import apply_tetrahedral

SLIDES = ['fujifilm_provia_100f', 'fujifilm_velvia_100',
          'kodak_ektachrome_100', 'kodak_kodachrome_64']


@pytest.mark.parametrize('film', SLIDES)
def test_slide_direct_scan_matches_runtime_and_ignores_paper(film):
    spec = BundleSpec(film_profile=film, print_profiles=('kodak_portra_endura',),
                      input_color_space=CONFIG['input'], output_color_space=CONFIG['output'],
                      resolution=33, stops_above_midgray=None,
                      output_gamut_compress=CONFIG['output_gamut_compress'])
    cat = json.loads((PUBLIC / 'catalog.json').read_text())
    choices = [c for c in cat['combinations'] if c['film'] == film]
    assert len(choices) == 1
    combo = choices[0]
    assert combo['status'] == 'ready'
    assert combo['paper'] is None and combo['processMode'] == 'positive_direct'
    table = read_cube(PUBLIC / combo['files']['vlog']['path'].lstrip('/'), 'VLOG')
    points = np.concatenate([np.random.default_rng(52).random((1024, 3)),
                              std_to_vlog(np.repeat(np.linspace(0, 1, 257)[:, None], 3, axis=1))])
    direct = run_slide_reference(spec, points)
    alternate = run_slide_reference(spec, points, 'fujifilm_crystal_archive_typeii')
    np.testing.assert_allclose(direct, alternate, atol=1e-12, rtol=0)
    error = np.max(np.abs(apply_tetrahedral(table, points) - direct), axis=1)
    assert np.quantile(error, .99) < .05
    # Increasing neutral exposure must not produce the inverted print path.
    ramp = apply_tetrahedral(table, points[-257:])
    luminance = ramp @ np.array([.2126, .7152, .0722])
    assert luminance[-1] - luminance[0] > .5
    assert np.diff(luminance).min() > -.002
    builder = SlideBundleBuilder(spec)
    pipeline = builder._make_pipeline(spec, get(spec.input_color_space), get(spec.output_color_space), 'kodak_portra_endura')
    labels = [node.label for node in pipeline._build_topology()]
    assert labels[-1] == 'scanning.scan_film'
    assert not any(label.startswith('printing.') for label in labels)
    provenance = json.loads((PUBLIC / combo['files']['provenance']['path'].lstrip('/')).read_text())
    assert provenance['profiles']['paper'] is None
    assert provenance['scanFilm'] is True
    assert provenance['bundle']['stocks']['prints'] == []
    assert provenance['bundle']['params_snapshot']['direct_scan']['scan_film'] is True


def test_slide_builder_rejects_negative_and_split_topology():
    spec = BundleSpec(film_profile='kodak_portra_400',print_profiles=('kodak_portra_endura',),
                      input_color_space='vlog',output_color_space='srgb')
    with pytest.raises(ValueError, match='positive film'):
        SlideBundleBuilder(spec).build()
    with pytest.raises(ValueError, match='1lut'):
        SlideBundleBuilder(replace(spec, topology='2lut')).build()
