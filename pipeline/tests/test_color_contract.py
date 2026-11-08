from pipeline.common import CONFIG, PUBLIC, std_to_vlog, vlog_encode, read_cube, sha256
import numpy as np
import pytest
import colour
from scipy.interpolate import RegularGridInterpolator
from spektrafilm_lut_creator.grid import cube_grid
from spektrafilm_lut_creator.formats import Lut
from spektrafilm_lut_creator.formats.lumix import LumixCubeFormat
from spektrafilm_lut_creator.qa.evaluators import apply_tetrahedral, apply_trilinear
from spektrafilm_lut_creator.bundles import BundleSpec
from spektrafilm_lut_creator.builders import BundleBuilder
from pipeline.camera_std import compose, serialize_std


def test_panasonic_reference_anchors_and_independent_colour_science():
    assert vlog_encode(0) == 0.125
    assert abs(vlog_encode(.18) - 433/1023) < .0001
    points=np.random.default_rng(7).random((2000,3))
    independent=colour.RGB_to_RGB(points,'sRGB','V-Gamut',apply_cctf_decoding=True)
    expected=colour.models.log_encoding_VLog(independent)
    # Official published six-decimal matrix vs colour's chromaticity-derived one.
    assert np.max(np.abs(std_to_vlog(points)-expected)) < .0002
    assert np.max(np.abs(std_to_vlog(np.ones((1,3)))-vlog_encode(1))) < 1e-6


def test_axis_order_writer_and_independent_readers(tmp_path):
    n=33; coordinates=cube_grid(n)
    # Asymmetric affine map detects R/B transposes and channel swaps.
    values=coordinates @ np.array([[.6,.1,.2],[.2,.5,.1],[.1,.2,.4]]) + .02
    file=tmp_path/'TESTVLOG.cube'
    LumixCubeFormat().write(Lut(values.reshape(n,n,n,3),title='axis-test'),file,photo_style_tag='VLOG')
    table=read_cube(file,'VLOG')
    independent=colour.read_LUT(str(file))
    np.testing.assert_allclose(independent.table,table.transpose(2,1,0,3),atol=1e-7)
    points=np.random.default_rng(8).random((1234,3))
    truth=points @ np.array([[.6,.1,.2],[.2,.5,.1],[.1,.2,.4]]) + .02
    for interpolation in [apply_trilinear,apply_tetrahedral]:
        np.testing.assert_allclose(interpolation(table,points),truth,atol=1e-6)
    grid=np.linspace(0,1,n)
    scipy=RegularGridInterpolator((grid,grid,grid),table)(points[:,::-1])
    np.testing.assert_allclose(apply_trilinear(table,points),scipy,atol=1e-12)


def test_generated_std_matches_camera_composition_not_retagged_vlog():
    base=PUBLIC/'luts/kodak_portra_400__kodak_portra_endura'
    vlog=read_cube(base/'0086VLOG.cube','VLOG')
    std=read_cube(base/'0086STD.cube','STD')
    assert np.max(np.abs(vlog-std)) > .2
    samples=np.random.default_rng(12).random((20000,3))
    reference=compose(vlog,'S1II',samples)
    # Independent colour-science reader/interpolator evaluates the saved file.
    evaluated=colour.read_LUT(str(base/'0086STD.cube')).apply(samples)
    error=np.max(np.abs(reference-evaluated),axis=1)
    assert np.quantile(error,.99) < .04


def test_regeneration_is_byte_identical(tmp_path):
    spec=BundleSpec(film_profile='kodak_portra_400',print_profiles=('kodak_portra_endura',),
                    input_color_space=CONFIG['input'],output_color_space=CONFIG['output'],
                    topology='1lut',resolution=33,target=CONFIG['target'],
                    stops_above_midgray=None,output_gamut_compress=CONFIG['output_gamut_compress'])
    bundle=BundleBuilder(spec).build()
    table=bundle.luts[0][1].table
    base=PUBLIC/'luts/kodak_portra_400__kodak_portra_endura'
    path=tmp_path/'0086VLOG.cube'
    LumixCubeFormat().write(Lut(table,title='0086_VLOG'),path,photo_style_tag='VLOG')
    assert sha256(path)==sha256(base/path.name)
    std=compose(read_cube(base/'0086VLOG.cube','VLOG'),'S1II',cube_grid(33))
    data=serialize_std(std,'S1II','0086VLOG.cube')
    assert data==(base/'0086STD.cube').read_bytes()


@pytest.mark.parametrize('film',['fujifilm_provia_100f','fujifilm_velvia_100','kodak_ektachrome_100','kodak_kodachrome_64'])
def test_slide_stock_requires_separate_scan_path(film):
    spec=BundleSpec(film_profile=film,print_profiles=('kodak_portra_endura',),
                    input_color_space='vlog',output_color_space='srgb',resolution=33,
                    stops_above_midgray=None)
    table=BundleBuilder(spec).build().luts[0][1].table
    ends=apply_tetrahedral(table,std_to_vlog(np.array([[0,0,0],[1,1,1]])))
    assert (ends[1]-ends[0]).mean() < 0, 'Reevaluate exclusion: positive stock no longer inverts print path'
