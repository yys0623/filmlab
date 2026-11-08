"""Historical v3 controls; production camera STD is checked in test_camera_std.

Retains the independent native engine and retired JPG adapter comparisons for
auditing earlier output. None of these legacy functions is a production path.
"""
from dataclasses import replace
import json

import colour
import numpy as np
import pytest
from PIL import Image

from pipeline.common import CONFIG, PUBLIC, std_to_vlog
from pipeline.slide import SlideBundleBuilder
from pipeline.std import (legacy_bake_std as bake_std, run_std_native,
                          legacy_run_std_reference as run_std_reference)
from pipeline.jpg import JpgToneProtection
from spektrafilm_lut_creator.grid import cube_grid
from spektrafilm.runtime.params_builder import init_params, digest_params
from spektrafilm.runtime.pipeline import SimulationPipeline
from spektrafilm_lut_creator.bundles import BundleSpec
from spektrafilm_lut_creator.builders import BundleBuilder
from spektrafilm_lut_creator.qa.evaluators import apply_tetrahedral


def independent_native_runtime(spec, pixels, *, slide):
    """No production adapter, CCTF helper, builder factory or QA reference."""
    params=init_params(film_profile=spec.film_profile,print_profile=spec.print_profiles[0])
    params.debug.lut_mode=True
    params.io.input_color_space='V-Gamut'
    params.io.output_color_space='sRGB'
    params.io.input_cctf_decoding=False
    params.io.output_cctf_encoding=False
    params.io.input_gamut_compress=spec.input_gamut_compress
    params.io.output_gamut_compress=spec.output_gamut_compress
    params.io.scan_film=slide
    if slide:
        params.settings.neutral_print_filters_from_database=False
    engine=SimulationPipeline(digest_params(params))
    # Decode sRGB and change primaries independently. Deliberately do not
    # encode/decode V-Log and do not apply any exposure normalization.
    linear=colour.RGB_to_RGB(colour.models.eotf_sRGB(pixels),'sRGB','V-Gamut')
    out=engine.process(linear.astype(np.float32).reshape(1,-1,3))
    return np.clip(colour.models.eotf_inverse_sRGB(np.asarray(out).reshape(-1,3)),0,1)


@pytest.mark.parametrize('film,paper,slide',[
    ('kodak_portra_400','kodak_portra_endura',False),
    ('fujifilm_c200','fujifilm_crystal_archive_typeii',False),
    ('fujifilm_velvia_100','kodak_portra_endura',True),
])
def test_direct_std_preserves_native_engine_and_improves_photo_accuracy(film,paper,slide):
    spec=BundleSpec(film_profile=film,print_profiles=(paper,),
                    input_color_space=CONFIG['input'],output_color_space='sRGB',
                    resolution=33,stops_above_midgray=None,
                    output_gamut_compress=CONFIG['output_gamut_compress'])
    bundle=(SlideBundleBuilder if slide else BundleBuilder)(spec).build()
    before=bundle.luts[0][1].table.copy()
    native_std=run_std_native(spec,bundle,cube_grid(33),is_slide=slide).reshape(33,33,33,3)
    std=bake_std(spec,bundle,is_slide=slide)
    # Include actual source-domain colors, off-grid random colors and gray.
    rng=np.random.default_rng(20261102)
    photo=[]
    camera_samples = [s for s in json.loads((PUBLIC/'samples/manifest.json').read_text()) if s['inputKind']=='camera-std']
    for sample in camera_samples[:2]:
        pixels=np.asarray(Image.open(PUBLIC/sample['path'].lstrip('/')).convert('RGB')).reshape(-1,3)/255.
        photo.append(pixels[rng.choice(len(pixels),1024,replace=False)])
    samples=np.concatenate(photo+[rng.random((2048,3)),np.repeat(np.linspace(0,1,257)[:,None],3,axis=1)])
    truth=independent_native_runtime(spec,samples,slide=slide)
    reference=run_std_native(spec,bundle,samples,is_slide=slide)
    # The published six-decimal Panasonic matrix and float32 V-Log transport
    # account for tiny differences from colour's chromaticity-derived matrix.
    np.testing.assert_allclose(reference,truth,atol=.0006,rtol=0)
    error=np.max(np.abs(apply_tetrahedral(native_std,samples)-truth),axis=1)
    assert np.quantile(error,.99)<.006
    legacy=apply_tetrahedral(before,std_to_vlog(samples))
    old_photo_mae=np.abs(legacy[:2048]-truth[:2048]).mean()
    new_photo_mae=np.abs(apply_tetrahedral(native_std,samples[:2048])-truth[:2048]).mean()
    assert new_photo_mae<old_photo_mae*.5
    # Keep the preceding independent native-engine accuracy checks. The
    # protected STD intentionally differs from that native tone response.
    independently_protected=JpgToneProtection(
        lambda rgb: independent_native_runtime(spec,rgb,slide=slide)).apply(samples)
    protected_reference=run_std_reference(spec,bundle,samples,is_slide=slide)
    np.testing.assert_allclose(protected_reference,independently_protected,atol=.001,rtol=0)
    protected_error=np.max(np.abs(apply_tetrahedral(std,samples)-protected_reference),axis=1)
    assert np.quantile(protected_error,.99)<.02
    assert np.quantile(protected_error[:2048],.99)<.012
    assert np.mean(np.abs(protected_reference-truth))>.005
    # STD baking must never rewrite or mutate VLOG values.
    np.testing.assert_array_equal(bundle.luts[0][1].table,before)


def test_std_rejects_unintended_exposure_gain_and_input_space():
    spec=BundleSpec(film_profile='kodak_portra_400',print_profiles=('kodak_portra_endura',),
                    input_color_space='Panasonic V-Log',output_color_space='sRGB',stops_above_midgray=None)
    sample=np.full((1,3),.5)
    with pytest.raises(ValueError,match='native input exposure'):
        run_std_reference(replace(spec,stops_above_midgray=4.0),None,sample)
    with pytest.raises(ValueError,match='Panasonic V-Log'):
        run_std_reference(replace(spec,input_color_space='sRGB'),None,sample)
