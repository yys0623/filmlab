"""Compare saved v1 assets with exported v2 cubes, independently of the engine.

Run after generation: python -m pipeline.audit_fuji_contrast
The before snapshot is preserved in artifacts/contrast-v2, never deployed.
Brightness here is weighted encoded RGB, NOT physical luminance or camera accuracy.
"""
from pathlib import Path
import json

import colour
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageCms

from pipeline.common import ROOT, PUBLIC, save_json, sha256

OUT = ROOT / 'artifacts/contrast-v2'
WEIGHTS = np.array([.2126, .7152, .0722])


def read_lut(path, digest):
    if sha256(path) != digest:
        raise ValueError(f'Unexpected LUT bytes: {path}')
    return colour.read_LUT(str(path))


def apply(lut, rgb):
    return lut.apply(rgb, interpolator=colour.algebra.table_interpolation_tetrahedral)


def brightness_stats(rgb, source):
    y = rgb @ WEIGHTS
    source_y = source @ WEIGHTS
    eligible = source_y >= 32 / 255
    return {
        'nearBlackPercent': float(np.mean(y < 13 / 255) * 100),
        'newNearBlackPercentOfEligible': float(np.mean(y[eligible] < 13 / 255) * 100),
        'brightnessPercentiles': np.quantile(y, [.01, .05, .5, .95, .99]).tolist(),
    }


def main():
    before = json.loads((OUT / 'catalog-before.json').read_text())
    after = json.loads((PUBLIC / 'catalog.json').read_text())
    old = {c['id']: c for c in before['combinations']}
    preserved = [c for c in after['combinations'] if not c['processMode'].startswith('official_')]
    assert len(preserved) == 152 and all(c == old[c['id']] for c in preserved)
    for combo in preserved:
        for asset in [*combo['files'].values(), *combo['previews'].values()]:
            assert sha256(PUBLIC / asset['path'].lstrip('/')) == asset['sha256']
    samples = after['samples']
    images = {s['id']: np.asarray(Image.open(PUBLIC / s['path'].lstrip('/')).convert('RGB')) / 255 for s in samples}
    # Deterministic stride samples cover the entire image; no fit or tuning uses them.
    pixels = {key: value[::4, ::4].reshape(-1, 3) for key, value in images.items()}
    gray_codes = np.arange(256)
    gray = np.repeat((gray_codes / 255)[:, None], 3, axis=1)
    records = []
    luts = {}
    for combo in after['combinations']:
        if not combo['processMode'].startswith('official_'):
            continue
        previous = old[combo['id']]
        a, b = previous['files']['std'], combo['files']['std']
        first = read_lut(OUT / 'before' / combo['id'] / a['name'], a['sha256'])
        second = read_lut(PUBLIC / b['path'].lstrip('/'), b['sha256'])
        luts[combo['id']] = first, second
        gray_before, gray_after = apply(first, gray), apply(second, gray)
        y = gray_after @ WEIGHTS
        assert np.isfinite(gray_after).all() and gray_after.min() >= 0 and gray_after.max() <= 1
        assert np.min(np.diff(y)) > -1e-5, combo['id']
        entry = {'id': combo['id'], 'beforeSha256': a['sha256'], 'afterSha256': b['sha256'],
                 'grayInputCodes': [16, 32, 64, 128, 192, 240],
                 'grayBefore': (gray_before[[16, 32, 64, 128, 192, 240]] @ WEIGHTS * 255).tolist(),
                 'grayAfter': (gray_after[[16, 32, 64, 128, 192, 240]] @ WEIGHTS * 255).tolist(), 'samples': {}}
        for sid, rgb in pixels.items():
            x, z = apply(first, rgb), apply(second, rgb)
            assert np.isfinite(z).all() and z.min() >= -1e-9 and z.max() <= 1 + 1e-9
            entry['samples'][sid] = {'count': len(rgb), 'before': brightness_stats(x, rgb), 'after': brightness_stats(z, rgb)}
        records.append(entry)
    save_json(OUT / 'report.json', {'metric': 'weighted encoded sRGB (.2126,.7152,.0722); near-black <13/255; eligible original >=32/255; not physical luminance',
        'preservedCombinations': len(preserved), 'officialCombinations': len(records), 'samplesPerCombination': len(samples), 'records': records})
    font_path = '/System/Library/Fonts/AppleSDGothicNeo.ttc'
    font = lambda size: ImageFont.truetype(font_path, size)
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    for film in ['gfx_classic_chrome', 'gfx_classic_neg', 'gfx_reala_ace']:
        sheet = Image.new('RGB', (1600, 1700), '#151718')
        draw = ImageDraw.Draw(sheet)
        draw.text((20, 18), f'FUJI 암부 수정 전후 · {film.removeprefix("gfx_").upper().replace("_", " ")}', font=font(30), fill='white')
        draw.text((20, 60), '같은 STD 원본 · LUT 100% · 사진별 노출 / WB 보정 없음 · Crystal Archive Type II', font=font(21), fill='#bfc8c2')
        for col, title in enumerate(['STD 원본', '수정 전 + 인화지', '수정 후 LUT만', '수정 후 + 인화지']):
            draw.text((col * 400 + 16, 105), title, font=font(25), fill='#d6e8b1')
        direct = luts[f'{film}__official_direct'][1]
        first, second = luts[f'{film}__fujifilm_crystal_archive_typeii']
        for row, sample in enumerate(samples):
            y0 = 148 + row * 252
            rgb = images[sample['id']]
            draw.text((20, y0), sample['name'], font=font(20), fill='white')
            for col, rgb_out in enumerate([rgb, apply(first, rgb), apply(direct, rgb), apply(second, rgb)]):
                photo = Image.fromarray(np.round(np.clip(rgb_out, 0, 1) * 255).astype('uint8'))
                photo.thumbnail((380, 210), Image.Resampling.LANCZOS)
                sheet.paste(photo, (col * 400 + (400 - photo.width) // 2, y0 + 29 + (210 - photo.height) // 2))
        sheet.save(OUT / f'{film}-before-after.jpg', quality=95, subsampling=0, icc_profile=icc)
    direct_unchanged = sum(c['files']['vlog']['sha256'] == old[c['id']]['files']['vlog']['sha256'] for c in after['combinations'] if c['processMode'] == 'official_direct')
    print(json.dumps({'preserved': len(preserved), 'audited': len(records), 'sampleComparisons': len(records) * len(samples), 'unchangedDirectVlog': direct_unchanged, 'report': str(OUT / 'report.json')}))


if __name__ == '__main__':
    main()
