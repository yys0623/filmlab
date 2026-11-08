import numpy as np
import pytest

from pipeline.jpg import JpgToneProtection, gamut_map
from pipeline.jpg_refined import RefinedJpgToneProtection, soft_chroma_ratio, soft_gamut_map
from pipeline.research import linear_to_oklab


def test_shoulder_is_identity_then_c1_strictly_monotone_and_bounded():
    k=.9
    x=np.r_[np.linspace(0,k,101),np.linspace(k+1e-6,8,10000)]
    y=soft_chroma_ratio(x,k)
    assert np.array_equal(x[x<=k],y[x<=k])
    assert np.all(np.diff(y)>0)
    assert np.all(y<1)
    assert soft_chroma_ratio(1,k)==pytest.approx(.95)
    e=1e-6
    assert (soft_chroma_ratio(k+e,k)-soft_chroma_ratio(k,k))/e==pytest.approx(1,abs=2e-5)
    assert soft_chroma_ratio(2,k)>soft_chroma_ratio(1,k)
    for invalid in [0,1,-.1,np.nan]:
        with pytest.raises(ValueError):soft_chroma_ratio(.5,invalid)


def test_neutrals_endpoints_and_safe_colors_are_unchanged():
    gray=np.column_stack([np.linspace(0,1,1001),np.zeros((1001,2))])
    assert np.array_equal(soft_gamut_map(gray),gamut_map(gray))
    rng=np.random.default_rng(24)
    safe=linear_to_oklab(rng.uniform(.2,.6,(10000,3)))
    assert np.array_equal(soft_gamut_map(safe),gamut_map(safe))
    endpoints=np.array([[0,.2,-.1],[1,-.3,.2]])
    assert np.array_equal(soft_gamut_map(endpoints),np.array([[0,0,0],[1,1,1]]))


def test_outside_colors_preserve_lightness_and_hue_but_keep_chroma_separation():
    # A fixed hue/ray beyond sRGB: old mapping collapses distinct chromas.
    requested=np.column_stack([np.full(20,.6),np.linspace(.35,.8,20),np.zeros(20)])
    old=linear_to_oklab(gamut_map(requested))
    rgb=soft_gamut_map(requested)
    new=linear_to_oklab(rgb)
    assert np.all((rgb>=0)&(rgb<=1))
    assert np.max(abs(new[:,0]-.6))<1e-7
    assert np.max(abs(new[:,2]))<1e-7
    assert np.ptp(old[:,1])<4e-6
    assert np.all(np.diff(new[:,1])>0)
    assert np.ptp(new[:,1])>1e-3


def test_protection_changes_only_mapper_and_keeps_gray_tone_identical():
    render=lambda x:np.clip(.03+np.asarray(x)**1.5*.92,0,1)
    original=JpgToneProtection(render)
    refined=RefinedJpgToneProtection(render)
    gray=np.repeat(np.linspace(0,1,4097)[:,None],3,axis=1)
    assert np.array_equal(original.apply(gray),refined.apply(gray))
    assert refined.metadata()['parentMethod']==original.metadata()['method']
    rng=np.random.default_rng(33)
    sample=rng.random((50,60,3))
    out=refined.apply(sample)
    assert out.shape==sample.shape and np.isfinite(out).all()
    assert out.min()>=0 and out.max()<=1
    with pytest.raises(ValueError):refined.apply(np.array([[2.,0,0]]))


def test_near_degenerate_lightness_is_finite_and_bounded():
    samples=np.array([[1e-15,1e-3,-1e-3],[1-1e-15,-.4,.3],[.5,0,0],[0,0,0],[1,0,0]])
    output=soft_gamut_map(samples)
    assert np.isfinite(output).all()
    assert output.min()>=0 and output.max()<=1


def test_blue_reentry_uses_first_connected_boundary_from_independent_cubic_roots():
    from pipeline.research import _M1_INV, _M2_INV
    # Regression: along this blue ray, RGB can leave and then re-enter sRGB.
    # Searching a single [neutral, upper] bracket can choose the later island.
    base=np.array([.32352043,-.01999264,-.19493118])
    hue=base[1:]/np.linalg.norm(base[1:]); lms0=base[0]*_M2_INV[:,0]
    direction=_M2_INV[:,1:]@hue
    co=np.stack([direction**3,3*lms0*direction**2,3*lms0**2*direction,lms0**3])@_M1_INV.T
    roots=[]
    for channel in range(3):
        for boundary in (0.,1.):
            poly=co[:,channel].copy();poly[-1]-=boundary
            roots.extend(r.real for r in np.roots(poly) if abs(r.imag)<1e-9 and r.real>0)
    first=min(roots)
    assert first==pytest.approx(.19595,abs=.0001)
    c=np.linspace(first*.85,first*1.4,101)
    requested=np.column_stack([np.full(len(c),base[0]),c[:,None]*hue])
    rgb=soft_gamut_map(requested)
    output=linear_to_oklab(rgb)
    expected=first*soft_chroma_ratio(c/first)
    assert np.max(abs(np.linalg.norm(output[:,1:],axis=1)-expected))<1e-7
    assert np.all(np.diff(np.linalg.norm(output[:,1:],axis=1))>0)
    assert np.max(abs(output[:,0]-base[0]))<1e-7
