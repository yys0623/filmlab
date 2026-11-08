"""Direct positive-film scanning for pinned spektrafilm 0.3.4.

The upstream runtime supports scan_film, but its LUT builder and QA factory
do not set it. Keep the vendor checkout unchanged and adapt both paths here.
The required init print profile is an unused runtime dependency, not a look.
"""
from dataclasses import replace

import numpy as np
from spektrafilm.runtime.params_builder import digest_params, init_params
from spektrafilm.runtime.pipeline import SimulationPipeline
from spektrafilm_lut_creator.builders import BundleBuilder
from spektrafilm_lut_creator.color_spaces import decode_cctf, encode_cctf, get

INIT_PRINT_PROFILE = 'kodak_portra_endura'


class SlideBundleBuilder(BundleBuilder):
    def _make_pipeline(self, spec, in_entry, out_entry, print_stock):
        params = init_params(film_profile=spec.film_profile, print_profile=print_stock)
        if not params.film.is_positive:
            raise ValueError('Direct slide scan requires a positive film')
        params.io.scan_film = True
        params.debug.lut_mode = True
        params.io.input_color_space = in_entry.primaries
        params.io.output_color_space = out_entry.primaries
        params.io.input_cctf_decoding = False
        params.io.output_cctf_encoding = False
        params.io.input_gamut_compress = spec.input_gamut_compress
        params.io.output_gamut_compress = spec.output_gamut_compress
        # Print neutral filters are irrelevant to the direct-scan graph.
        params.settings.neutral_print_filters_from_database = False
        return SimulationPipeline(digest_params(params))

    def build(self):
        if self.spec.topology != '1lut' or len(self.spec.print_profiles) != 1:
            raise ValueError('Direct scan supports one combined 1lut only')
        bundle = super().build()
        snapshot = dict(next(iter(bundle.meta.params_snapshot.values())))
        snapshot.update(print_profile=None, scan_film=True,
                        runtime_init_print_profile=self.spec.print_profiles[0],
                        neutral_print_filters_from_database=False)
        bundle.meta = replace(
            bundle.meta,
            name=f'{self.spec.film_profile}__direct_scan',
            stocks=replace(bundle.meta.stocks, prints=()),
            luts=tuple(replace(lut, print_profile=None, path='direct_scan.cube') for lut in bundle.meta.luts),
            params_snapshot={'direct_scan': snapshot},
        )
        bundle.luts = [('direct_scan.cube', bundle.luts[0][1])]
        return bundle


def run_slide_reference(spec, samples_encoded, init_print_profile=INIT_PRINT_PROFILE):
    """Off-grid runtime evaluation independent of the builder's factory."""
    params = init_params(film_profile=spec.film_profile, print_profile=init_print_profile)
    if not params.film.is_positive:
        raise ValueError('Direct slide scan requires a positive film')
    params.io.scan_film = True
    params.debug.lut_mode = True
    params.settings.neutral_print_filters_from_database = False
    params.io.input_color_space = get(spec.input_color_space).primaries
    params.io.output_color_space = get(spec.output_color_space).primaries
    params.io.input_cctf_decoding = False
    params.io.output_cctf_encoding = False
    params.io.input_gamut_compress = spec.input_gamut_compress
    params.io.output_gamut_compress = spec.output_gamut_compress
    pipeline = SimulationPipeline(digest_params(params))
    frame = spec.bake_frame()
    samples = np.asarray(samples_encoded, dtype=np.float32).reshape(1, -1, 3)
    linear = (decode_cctf(samples, spec.input_color_space) * frame.input_gain).astype(np.float32)
    output = np.asarray(pipeline.process(linear), dtype=float).reshape(-1, 3)
    return np.clip(encode_cctf(output * frame.output_gain, spec.output_color_space), 0, 1)
