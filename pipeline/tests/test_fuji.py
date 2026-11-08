"""Official source identity plus historical v3 input-adapter regressions.

Production camera Standard export is checked in test_camera_std and test_precurve_exports. The
explicit legacy adapter here preserves the old PROVIA/JPG audit baseline.
"""
import hashlib
import io
import zipfile
import colour
import numpy as np
import pytest
from pipeline.fuji import (load_study, official_archive, official_table, flog2_encode,
                           flog2_decode, input_to_flog2, apply_official_legacy as apply_official, SRGB_TO_FGAMUT,
                           std_to_scene_linear, std_neutral_inverse, input_adapter_metadata,
                           apply_official_native)
from pipeline.common import srgb_decode, std_to_vlog, metrics
from pipeline.research import srgb_encode
from spektrafilm_lut_creator.grid import cube_grid
from spektrafilm_lut_creator.qa.evaluators import apply_tetrahedral


def test_official_archive_and_all_ten_sources_are_pinned():
    study=load_study();archive=official_archive()
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==study['sourceSha256']
    with zipfile.ZipFile(archive) as z:
        for look in study['looks']:
            raw=z.read(look['sourceArchivePath'])
            assert hashlib.sha256(raw).hexdigest()==look['sourceSha256']
            assert b'#model:GFX ETERNA 55' in raw
            assert b'#Gamut:F-Gamut to ITU-R BT.709' in raw
            assert b'LUT_3D_SIZE 65' in raw
    assert len({look['sourceSha256'] for look in study['looks']})==10


def test_flog2_matches_published_code_values_and_roundtrip():
    assert np.allclose(flog2_encode([0,.18,.9])*1023,[95,400,570],atol=.65)
    values=np.r_[np.linspace(0,.0008,12),np.geomspace(.001,20,200)]
    assert np.allclose(flog2_decode(flog2_encode(values)),values,atol=1e-12)
    expected=colour.RGB_to_RGB(np.eye(3),'sRGB','ITU-R BT.2020',apply_cctf_decoding=False,apply_cctf_encoding=False)
    # colour's sRGB matrix uses four-decimal published coefficients.
    assert np.allclose(SRGB_TO_FGAMUT.T,expected,atol=9e-5)
    assert np.allclose(SRGB_TO_FGAMUT@np.ones(3),1,atol=1e-12)


def test_vlog_remains_scene_linear_but_rendered_jpg_gets_shared_tone_adaptation():
    points=np.random.default_rng(14).random((1024,3))
    expected=flog2_encode(srgb_decode(points)@SRGB_TO_FGAMUT.T)
    assert np.allclose(expected,input_to_flog2(std_to_vlog(points),'vlog'),atol=3e-6)
    # A JPEG already includes a display tone scale; treating that as camera
    # scene exposure was the cause of the duplicated shadow toe.
    assert not np.allclose(input_to_flog2(points),expected,atol=.01)


@pytest.mark.parametrize('film',[look['film'] for look in load_study()['looks']])
def test_official_lut_order_and_gamma_match_independent_colour_reader(film,tmp_path):
    look=next(l for l in load_study()['looks'] if l['film']==film)
    with zipfile.ZipFile(official_archive()) as archive: raw=archive.read(look['sourceArchivePath'])
    path=tmp_path/'source.cube';path.write_bytes(raw)
    lut=colour.read_LUT(str(path))
    points=np.concatenate([np.random.default_rng(8).random((512,3)),np.eye(3),np.zeros((1,3)),np.ones((1,3))])
    # Independently build F-Gamut coordinates from exact D65 primary matrices.
    srgb=colour.models.RGB_COLOURSPACE_sRGB.copy();srgb.use_derived_transformation_matrices(True)
    bt2020=colour.models.RGB_COLOURSPACE_BT2020.copy();bt2020.use_derived_transformation_matrices(True)
    linear=colour.cctf_decoding(points,function='sRGB')
    fg=colour.RGB_to_RGB(linear,srgb,bt2020,apply_cctf_decoding=False,apply_cctf_encoding=False)
    encoded=np.where(fg>=.000889,.245281*np.log10(np.maximum(5.555556*fg+.064829,1e-30))+.384316,8.799461*fg+.092864)
    display=lut.apply(np.clip(encoded,0,1),interpolator=colour.algebra.table_interpolation_tetrahedral)
    expected=colour.cctf_encoding(np.clip(display,0,1)**2.2,function='sRGB')
    # The unchanged V-Log scene path isolates source interpolation, gamut and
    # gamma from the new, explicitly creative JPEG input reconstruction.
    assert np.allclose(apply_official(std_to_vlog(points),film,'vlog'),expected,atol=7e-6)


def test_invalid_input_is_not_silently_interpreted_as_another_profile():
    for values in [[[-.1,0,0]],[[0,1.1,0]],[[np.nan,0,0]],[[0,0]]]:
        with pytest.raises(ValueError):input_to_flog2(values)
    with pytest.raises(ValueError):input_to_flog2([[0,0,0]],'flog2c')


def test_ten_simulations_differ_and_acros_is_monochrome():
    p=np.random.default_rng(53).random((256,3))
    outputs=[apply_official(p,l['film']) for l in load_study()['looks']]
    assert len({x.tobytes() for x in outputs})==10
    acros=apply_official(p,'gfx_acros')
    assert np.max(np.ptp(acros,axis=1))<1e-12


def test_shared_provia_adapter_restores_rendered_gray_scale_without_white_clipping():
    gray=np.repeat(np.linspace(0,1,1025)[:,None],3,axis=1)
    # An independent, observable contract: reference PROVIA's neutral output
    # should retain the Standard JPEG's display tone instead of crushing it.
    restored=apply_official(gray,'gfx_provia')
    assert np.max(np.abs(restored-gray))<2e-5
    scene=std_to_scene_linear(srgb_decode(gray))
    assert np.all(scene[0]==0)
    assert np.all(np.diff(scene,axis=0)>=0)
    assert np.all(scene[-1]>1)
    display_axis,scene_axis=std_neutral_inverse()
    assert not display_axis.flags.writeable and not scene_axis.flags.writeable
    assert np.all(np.diff(display_axis)>0)
    assert np.all(np.diff(scene_axis)>0)
    assert input_adapter_metadata()['referenceFilm']=='gfx_provia'


def test_jpg_adapter_preserves_chromaticity_and_is_continuous_at_black():
    colors=np.concatenate([np.eye(3),[[1,1,0],[1,0,1],[0,1,1],[1,.2,.01]],
                           np.random.default_rng(502).random((256,3))])
    scene=std_to_scene_linear(colors)
    assert np.max(np.abs(np.cross(colors,scene)))<2e-14
    assert np.isfinite(scene).all() and np.all(scene>=0)
    assert np.all(scene[colors==0]==0)
    tiny=np.geomspace(1e-14,1e-10,64)[:,None,None]*colors[None,:,:]
    adapted=std_to_scene_linear(tiny)
    # The inverse has a steep but finite first segment; approach black without
    # a nonzero scene pedestal or a change in RGB direction.
    assert np.max(adapted[0])<1e-7
    assert np.allclose(std_to_scene_linear(tiny[0]/10),adapted[0]/10,atol=1e-18)
    assert np.isfinite(adapted).all()
    assert np.max(np.abs(np.diff(adapted,axis=0)))<1e-4


@pytest.mark.parametrize('film',[look['film'] for look in load_study()['looks']])
def test_all_looks_retain_shadow_separation_and_33_grid_fidelity(film):
    levels=np.array([0,16,32,64,128,192,255])/255.
    gray=np.repeat(levels[:,None],3,axis=1)
    transformed=apply_official(gray,film)
    # Velvia keeps its characteristic strong toe, but at gray32 even the
    # darkest source look now stays above 18/255 instead of collapsing to0.
    luminance=srgb_encode(srgb_decode(transformed)@np.array([.2126,.7152,.0722]))
    assert luminance[2]>.065
    assert luminance[3]>.19
    assert np.all(np.diff(luminance)>0)
    assert np.allclose(apply_official(np.full((1,3),1e-12),film),transformed[:1],atol=1e-8)
    saturated=np.concatenate([np.linspace(0,1,129)[:,None]*hue
                  for hue in [[1,0,0],[0,1,0],[0,0,1],[1,1,0],[1,0,1],[0,1,1]]])
    points=np.concatenate([np.random.default_rng(883).random((4096,3)),gray,saturated])
    table=apply_official(cube_grid(33),film).reshape(33,33,33,3)
    exact=apply_official(points,film)
    approximation=apply_tetrahedral(table,points)
    fidelity=metrics(approximation,exact)
    assert np.isfinite(exact).all() and exact.min()>=0 and exact.max()<=1
    assert fidelity['p99']<.02
    assert fidelity['max']<.06


def test_shared_adapter_keeps_relative_simulation_tones():
    gray=np.array([[64/255]*3])
    output={look['film']:float(np.mean(apply_official(gray,look['film'])))
            for look in load_study()['looks']}
    assert output['gfx_classic_chrome']<output['gfx_provia']<output['gfx_eterna']
    native={look['film']:float(np.mean(apply_official_native(gray,look['film'])))
            for look in load_study()['looks']}
    # Protection deliberately reduces the tonal spread while retaining its
    # ordering; it must not silently replace all ten looks with one curve.
    assert .01 < max(output.values())-min(output.values()) < max(native.values())-min(native.values())
