"""Behavioural checks for a shared pre-render tone inverse, no output edits."""
import json
import numpy as np
import pytest
from pipeline.common import srgb_decode
from pipeline.research import srgb_encode
from pipeline.precurve import SingleTonePrecurve, LUMINANCE_WEIGHTS, MIDDLE_GRAY


def cast_render(rgb):
    """Known monotone toe/shoulder with a nonzero, coloured black and white."""
    rgb = np.asarray(rgb)
    y = srgb_decode(rgb) ** 1.45
    return srgb_encode(.006 * np.array([1.6, .9, .6]) + y * np.array([.52, .61, .67]))


def encoded_y(rgb):
    return srgb_encode(srgb_decode(rgb) @ LUMINANCE_WEIGHTS)


def test_a_retains_native_range_and_relative_linear_tone_without_removing_cast():
    p = SingleTonePrecurve(cast_render)
    axis = np.arange(256) / 255.
    gray = np.repeat(axis[:, None], 3, axis=1)
    result = p.apply(gray, 'A')
    actual = srgb_decode(result) @ LUMINANCE_WEIGHTS
    expected = p.y_black + (p.y_white-p.y_black) * srgb_decode(axis)
    np.testing.assert_allclose(actual, expected, atol=2e-7, rtol=0)
    np.testing.assert_allclose(result[[0,-1]], cast_render(gray[[0,-1]]), atol=1e-12)
    assert np.max(np.ptp(result, axis=-1)) > .01
    assert np.all(np.diff(actual[:17]) > 0)
    assert np.all(np.diff(actual[236:]) > 0)
    assert actual[0] > 0 and actual[-1] < 1


def test_b_gray_is_exact_and_shoulder_has_one_derived_parameter():
    p = SingleTonePrecurve(cast_render)
    m = MIDDLE_GRAY
    axis = np.array([m-1e-7, m, m+1e-7, 1.])
    gray = np.repeat(srgb_encode(axis)[:, None], 3, axis=1)
    target = srgb_decode(p.target(gray, 'B'))[:,0]
    assert abs(target[1]-m) < 1e-14
    assert abs(target[-1]-p.y_white) < 1e-14
    assert abs((target[2]-target[1])/1e-7-1) < 1e-6
    assert abs((target[1]-target[0])/1e-7-1) < 1e-6
    assert p.rolloff_k == (1-p.y_white)/(p.y_white-m)
    out = p.apply(gray, 'B')
    assert abs((srgb_decode(out[1]) @ LUMINANCE_WEIGHTS)-m) < 2e-7
    # 118 is the 8-bit approximation, not the exact encoding of 0.18.
    assert abs(float(srgb_encode(m)*255)-117.64581302261261) < 1e-10


def test_b_explicitly_cannot_restore_values_below_native_black():
    p = SingleTonePrecurve(cast_render)
    dark = np.repeat(srgb_encode(np.array([0., p.y_black*.5]))[:,None],3,axis=1)
    out = p.apply(dark, 'B')
    np.testing.assert_allclose(out, np.broadcast_to(cast_render(np.zeros((1,3))),out.shape), atol=1e-14)
    assert 'saturates' in p.metadata('B')['rolloff']['shadowFloor']


def test_b_rejects_unattainable_middle_gray():
    p = SingleTonePrecurve(lambda rgb: srgb_encode(.001+.1*srgb_decode(rgb)))
    assert p.rolloff_k is None
    with pytest.raises(ValueError, match='18%'):
        p.apply(np.full((2,3),.5),'B')


def test_coloured_output_is_source_renderer_at_same_scalar_prewarp_no_post_edit():
    observed = []
    def renderer(x):
        observed.append(np.asarray(x).copy())
        return cast_render(x)
    p = SingleTonePrecurve(renderer)
    source = np.random.default_rng(6).random((128,3))
    for variant in ['A','B']:
        observed.clear()
        result = p.apply(source,variant)
        # Independently reconstruct the scalar neutral inverse and target.
        axis = np.linspace(0,1,4097)
        neutral = np.repeat(axis[:,None],3,axis=1)
        neutral_y = encoded_y(cast_render(neutral))
        linear = srgb_decode(source)
        if variant == 'A':
            t = srgb_encode(p.y_black + (p.y_white-p.y_black)*linear)
        else:
            m=.18; k=(1-p.y_white)/(p.y_white-m)
            t=srgb_encode(np.where(linear<=m,linear,m+(linear-m)/(1+k*(linear-m)/(1-m))))
        warp = np.interp(t,neutral_y,axis)
        np.testing.assert_allclose(observed[0],warp,atol=1e-14,rtol=0)
        np.testing.assert_array_equal(result,cast_render(observed[0]))
        np.testing.assert_allclose(result,cast_render(warp),atol=1e-14,rtol=0)


def test_mapping_is_fixed_pixel_local_and_does_not_mutate_source():
    p=SingleTonePrecurve(cast_render)
    source=np.random.default_rng(1).random((30,3)); before=source.copy()
    for variant in ['A','B']:
        expected=p.apply(source,variant)
        surround=np.r_[np.zeros((10,3)),source,np.ones((10,3))]
        np.testing.assert_array_equal(p.apply(surround,variant)[10:-10],expected)
        np.testing.assert_array_equal(p.apply(source.reshape(5,6,3),variant).reshape(-1,3),expected)
    np.testing.assert_array_equal(source,before)
    meta=p.metadata();meta['source']['injected']='x'
    assert 'injected' not in p.metadata()['source']
    json.dumps(p.metadata('B'),allow_nan=False)


def test_nonmonotonic_response_is_disclosed_and_plateaus_use_generalised_inverse():
    def source(x):
        code=np.clip(np.asarray(x)*1.4-.1,0,1)
        return code
    p=SingleTonePrecurve(source)
    assert p.metadata()['plateauNeutralSteps'] > 0
    assert np.all(np.diff(p.neutral_code)>=0)
    assert np.isfinite(p.apply(np.random.default_rng(12).random((20,3)))).all()
    np.testing.assert_array_equal(p.inverse(np.array([0,1])),[0,1])
    # Adjacent interpolation must not stretch across either black or white
    # plateaus. Check the actual sampled piecewise-linear N independently.
    targets=np.linspace(.0001,.9999,1000)
    np.testing.assert_allclose(np.interp(p.inverse(targets),p.axis,p.neutral_code),targets,atol=2e-15)


@pytest.mark.parametrize('bad',[[], [[0,0]], [[np.nan,0,0]], [[-1,0,0]], [[1.01,0,0]]])
def test_bad_input_rejected(bad):
    with pytest.raises(ValueError):
        SingleTonePrecurve(cast_render).apply(bad)
