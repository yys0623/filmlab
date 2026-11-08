"""Official FUJIFILM source composition and historical input-adapter audits.

The downloaded 65-grid F-Log2 LUT values and exported VLOG path are unchanged.
Production Standard A/B uses the shared single-tone precurve over a serialized
VLOG export. The older PROVIA inverse/JPG output corrections remain only for
explicit historical audits and are not called by production generators.
"""
from __future__ import annotations

import io
import json
import subprocess
import zipfile
from functools import lru_cache

import numpy as np
from pipeline.common import ROOT, srgb_decode, VGAMUT_TO_SRGB, sha256
from pipeline.research import srgb_encode
from pipeline.jpg import JpgToneProtection
from spektrafilm_lut_creator.qa.evaluators import apply_tetrahedral

CONFIG_PATH = ROOT / 'pipeline/config/fujifilm-official.json'
METHOD_ID = 'film-lab-fujifilm-official-paper-v3'
STD_ADAPTER_ID = 'film-lab-shared-provia-neutral-inverse-v1'
STD_REFERENCE_FILM = 'gfx_provia'
STD_NEUTRAL_SAMPLES = 16385
SRGB_LUMINANCE = np.array([.2126, .7152, .0722])
# D65 sRGB -> BT.2020; F-Gamut has exactly the BT.2020 primaries.
SRGB_TO_FGAMUT = np.array([
    [.627403895934699, .329283038377883, .043313065687418],
    [.069097289358232, .919540395075459, .011362315566309],
    [.016391438875150, .088013307877226, .895595253247624],
])


def load_study():
    study = json.loads(CONFIG_PATH.read_text())
    if study['methodId'] != METHOD_ID or len(study['looks']) != 10:
        raise ValueError('Unexpected official LUT study')
    return study


def official_archive(*, download=False):
    study = load_study()
    path = ROOT / '.cache/fujifilm-gfx/gfx-eterna-55-3d-lut-v110.zip'
    if not path.exists() and download:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.download')
        subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error',
                        '--output', str(temporary), study['downloadUrl']], check=True)
        if sha256(temporary) != study['sourceSha256']:
            raise ValueError('Official package changed; review a new version before use')
        temporary.replace(path)
    if not path.exists() or sha256(path) != study['sourceSha256']:
        raise ValueError('Missing or changed official package; run generator with --download')
    return path


@lru_cache(maxsize=10)
def official_table(film_id):
    import hashlib
    look = next(x for x in load_study()['looks'] if x['film'] == film_id)
    with zipfile.ZipFile(official_archive()) as archive:
        raw = archive.read(look['sourceArchivePath'])
    if hashlib.sha256(raw).hexdigest() != look['sourceSha256']:
        raise ValueError('Official LUT hash mismatch')
    lines = raw.decode('utf-8-sig').splitlines()
    if 'LUT_3D_SIZE 65' not in lines:
        raise ValueError('Expected official 65-grid LUT')
    rows = '\n'.join(line for line in lines if line.strip() and not line.startswith(('#', 'LUT_3D_SIZE')))
    table = np.loadtxt(io.StringIO(rows)).reshape(65, 65, 65, 3)
    if not np.isfinite(table).all() or table.min() < 0 or table.max() > 1:
        raise ValueError('Invalid official LUT')
    table.setflags(write=False)
    return table


def flog2_encode(linear):
    """Fujifilm F-Log2 datasheet 1.1, scene reflection to full-range code."""
    x = np.asarray(linear, dtype=float)
    return np.where(x >= .000889,
                    .245281 * np.log10(np.maximum(5.555556*x + .064829, 1e-30)) + .384316,
                    8.799461*x + .092864)


def flog2_decode(encoded):
    x = np.asarray(encoded, dtype=float)
    return np.where(x >= .100686685370811,
                    (10**((x-.384316)/.245281)-.064829)/5.555556,
                    (x-.092864)/8.799461)


@lru_cache(maxsize=1)
def std_neutral_inverse():
    """Return a bounded, monotone display-Y -> virtual scene-Y curve.

    Use the *same* PROVIA curve for every simulation. Inverting each selected
    look separately would erase their intended differences in neutral tone.
    Sampling the source LUT's full F-Log2 axis also restores the scene range
    above 1.0 needed by already rendered JPEG highlights. No photo statistics
    or selected-look coefficients participate in this fixed curve.
    """
    codes = np.linspace(float(flog2_encode(0.)), 1., STD_NEUTRAL_SAMPLES)
    gray = np.repeat(codes[:, None], 3, axis=1)
    display = apply_tetrahedral(official_table(STD_REFERENCE_FILM), gray)
    luminance = display**2.2 @ SRGB_LUMINANCE
    # Source quantization can create plateaus or tiny reversals. Keep the
    # earliest code at each monotone output to avoid jumping across a plateau.
    luminance = np.maximum.accumulate(luminance)
    unique, indices = np.unique(luminance, return_index=True)
    scene = flog2_decode(codes[indices])
    if unique[0] != 0. or unique[-1] < 1. - 1e-12:
        raise ValueError('The pinned PROVIA neutral curve must cover display black and white')
    unique.setflags(write=False)
    scene.setflags(write=False)
    return unique, scene


def std_to_scene_linear(linear_srgb):
    """Undo one shared neutral rendering curve with a common RGB gain.

    The input is linearized display sRGB, not scene-linear exposure. Scaling
    all three channels equally preserves its linear RGB ratios/chromaticity
    at this adaptation stage. The official LUT may subsequently change hue,
    saturation and contrast. Never clip this reconstructed scene RGB at 1.
    """
    linear = np.asarray(linear_srgb, dtype=float)
    luminance = linear @ SRGB_LUMINANCE
    display_axis, scene_axis = std_neutral_inverse()
    mapped = np.interp(luminance, display_axis, scene_axis)
    gain = np.divide(mapped, luminance, out=np.zeros_like(mapped), where=luminance > 0)
    return linear * gain[..., None]


def input_adapter_metadata():
    """Describe the shared JPEG adaptation without claiming camera calibration."""
    _, scene_axis = std_neutral_inverse()
    source = next(x for x in load_study()['looks'] if x['film'] == STD_REFERENCE_FILM)
    return {
        'method': STD_ADAPTER_ID,
        'input': 'encoded sRGB / already rendered Standard JPEG, RGB 0..1',
        'referenceFilm': STD_REFERENCE_FILM,
        'referenceSourceSha256': source['sourceSha256'],
        'neutralSamples': STD_NEUTRAL_SAMPLES,
        'neutralSamplingDomain': 'F-Log2 code from scene-linear 0 to code 1',
        'referenceDisplayInterpretation': 'BT.709 primaries / gamma 2.2',
        'luminanceWeights': SRGB_LUMINANCE.tolist(),
        'formula': 'sceneRGB = linearDisplayRGB * inverse_PROVIA_Y(displayY) / displayY; exact RGB black maps to scene black',
        'inverse': 'piecewise-linear inverse of the monotone accumulated source neutral curve; earliest code for plateaus; bounded to sampled endpoints',
        'sceneWhiteAtDisplayWhite': float(scene_axis[-1]),
        'channelRatiosPreservedAtAdapter': True,
        'sceneRGBClippedAtOne': False,
        'sharedAcrossSimulations': True,
        'perImageAdaptation': False,
        'vlogAdaptationChanged': False,
        'cameraInverseCalibrated': False,
        'fujifilmOfficialInputTransform': False,
        'limitations': [
            'A shared virtual scene reconstruction for rendered JPEGs, not an inverse of a measured LUMIX or GFX photo style.',
            'Uses PROVIA as a neutral reference; selected simulations retain their relative official tone and color differences.',
            'Velvia and other contrasty source looks can still darken shadows relative to PROVIA.',
            'Camera white balance, local tone mapping, clipping and lost JPEG detail cannot be recovered.',
        ],
    }


def input_to_flog2(rgb, input_kind='std'):
    x = np.asarray(rgb, dtype=float)
    if x.ndim < 1 or x.shape[-1] != 3 or not np.isfinite(x).all() or np.any((x < 0) | (x > 1)):
        raise ValueError('Expected finite full-range RGB triples')
    if input_kind == 'std':
        linear = std_to_scene_linear(srgb_decode(x)) @ SRGB_TO_FGAMUT.T
    elif input_kind == 'vlog':
        vlinear = np.where(x < .181, (x-.125)/5.6, 10**((x-.598206)/.241514)-.00873)
        linear = vlinear @ (SRGB_TO_FGAMUT @ VGAMUT_TO_SRGB).T
    else:
        raise ValueError('Input must be std or vlog')
    # Negative/over-domain code values cannot be queried in a bounded cube.
    return np.clip(flog2_encode(linear), 0, 1)


def apply_official_native(rgb, film_id, input_kind='std', paper=None):
    x = np.asarray(rgb, dtype=float)
    flog = input_to_flog2(x, input_kind)
    encoded709 = apply_tetrahedral(official_table(film_id), flog.reshape(-1, 3))
    # Whitepaper p13 recommends Rec.709/D65/gamma 2.2 for these LUTs.
    # Explicitly re-encode for the application's sRGB display contract.
    linear = np.clip(encoded709, 0, 1)**2.2
    if paper is not None:
        linear = paper.apply(linear)
    return np.clip(srgb_encode(linear), 0, 1).reshape(x.shape)


@lru_cache(maxsize=90)
def official_jpg_protection(film_id, paper=None):
    return JpgToneProtection(lambda rgb: apply_official_native(rgb, film_id, 'std', paper))


def apply_official_legacy(rgb, film_id, input_kind='std', paper=None):
    """Historical v3 adapter for regression/audit only, never production STD."""
    if input_kind == 'std':
        return official_jpg_protection(film_id, paper).apply(rgb)
    return apply_official_native(rgb, film_id, input_kind, paper)


def apply_official(rgb, film_id, input_kind='std', paper=None, *, source_vlog_path=None, camera_id='S1II'):
    if input_kind == 'std':
        if source_vlog_path is None:
            raise ValueError('Production STD requires the serialized source_vlog_path')
        from pipeline.camera_std import compose
        from pipeline.common import read_cube
        values = np.asarray(rgb, dtype=np.float64)
        return compose(read_cube(source_vlog_path, 'VLOG'), camera_id, values.reshape(-1, 3)).reshape(values.shape)
    return apply_official_native(rgb, film_id, input_kind, paper)
