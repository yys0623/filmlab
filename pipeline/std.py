"""Historical camera-agnostic Standard adapters for reproducible audit evidence.

Production Standard generation is in pipeline.camera_std. The precurve A/B
and legacy JpgToneProtection functions below remain for historical tests only;
production generate.py/generate_fuji.py do not import them.
"""
import numpy as np

from pipeline.common import std_to_vlog, read_cube, sha256, PUBLIC
from pipeline.slide import run_slide_reference
from pipeline.digital import run_digital_reference
from pipeline.jpg import JpgToneProtection
from pipeline.precurve import SingleTonePrecurve, GENERATION
from spektrafilm_lut_creator.grid import cube_grid
from spektrafilm_lut_creator.qa.evaluators import apply_tetrahedral
from spektrafilm_lut_creator.qa.reference import run_pipeline_at

STD_GENERATION = GENERATION
STD_INPUT_GAIN = 1.0
STD_CONTRACT = (
    'R(x)=L_VLOG(VLogEncode(sRGBDecode(x) @ sRGB_to_VGamut.T)); '
    'L_VLOG is the serialized, exported 33-grid VLOG cube evaluated tetrahedrally. '
    'L_STD(x)=R(P(T(x))); P is the scalar inverse of R neutral encoded luminance; '
    'the identical scalar target T and inverse P are applied to each RGB channel. '
    'The renderer output RGB is returned unchanged, with no output tone, neutral '
    'subtraction, chroma gain or new gamut mapping. This is not a measured camera inverse.'
)


def precurve_from_exported_vlog(path):
    """Use file values as truth, including the writer's six-decimal precision."""
    path = path.resolve()
    table = read_cube(path, 'VLOG')
    table.setflags(write=False)
    try:
        public_path = '/' + path.relative_to(PUBLIC).as_posix()
    except ValueError:
        public_path = str(path)
    source = {'kind': 'exported-vlog-cube', 'sourceLutPath': public_path,
              'name': path.name, 'sha256': sha256(path),
              'interpolation': 'tetrahedral', 'resolution': table.shape[0]}
    return SingleTonePrecurve(
        lambda samples: apply_tetrahedral(table, std_to_vlog(np.asarray(samples).reshape(-1, 3))),
        source_metadata=source,
    )


def run_std_reference(vlog_path, samples, *, variant='A', precurve=None):
    """Exact precurve plus exported-source composition, before STD regridding."""
    precurve = precurve or precurve_from_exported_vlog(vlog_path)
    return precurve.apply(samples, variant=variant)


def bake_std(vlog_path, *, variant='A', precurve=None):
    return run_std_reference(vlog_path, cube_grid(33), variant=variant,
                             precurve=precurve).reshape(33, 33, 33, 3)


def run_std_native(spec, bundle, samples, *, is_slide=False, is_digital=False):
    """Unprotected continuous model; retained as the colour source and audit reference."""
    if spec.input_color_space != 'Panasonic V-Log' or spec.output_color_space != 'sRGB':
        raise ValueError('STD adapter requires Panasonic V-Log input and sRGB output')
    if not np.isclose(spec.bake_frame().input_gain, STD_INPUT_GAIN, atol=1e-12, rtol=0):
        raise ValueError('STD adapter requires unchanged native input exposure (gain 1)')
    coordinates = std_to_vlog(np.asarray(samples, dtype=np.float64).reshape(-1, 3))
    if not np.isfinite(coordinates).all() or coordinates.min() < 0 or coordinates.max() > 1:
        raise ValueError('Analytic adapter outside source domain')
    if is_slide and is_digital:
        raise ValueError('Select either positive direct scan or negative digital conversion')
    if is_digital:
        return run_digital_reference(spec, coordinates)
    if is_slide:
        return run_slide_reference(spec, coordinates)
    return run_pipeline_at(spec, bundle, 0, coordinates)


def legacy_std_protection(spec, bundle, *, is_slide=False, is_digital=False):
    return JpgToneProtection(
        lambda samples: run_std_native(spec, bundle, samples, is_slide=is_slide, is_digital=is_digital),
        digital=is_digital,
    )


def legacy_run_std_reference(spec, bundle, samples, *, is_slide=False, is_digital=False, protection=None):
    protection = protection or legacy_std_protection(spec, bundle, is_slide=is_slide, is_digital=is_digital)
    return protection.apply(samples)


def legacy_bake_std(spec, bundle, *, is_slide=False, is_digital=False, protection=None):
    """One engine evaluation per STD grid node; final cube uses R-fastest order."""
    n = spec.resolution
    return legacy_run_std_reference(spec, bundle, cube_grid(n), is_slide=is_slide, is_digital=is_digital,
                             protection=protection).reshape(n, n, n, 3)
