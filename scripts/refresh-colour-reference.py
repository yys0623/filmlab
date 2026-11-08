"""Refresh camera and supplied STD fixtures with independent colour interpolation.

Run: .venv/bin/python scripts/refresh-colour-reference.py
Preserves stored RGBA inputs and alpha; imports no application pipeline code.
"""
import hashlib
import json
from pathlib import Path

import colour
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
fixture_path = ROOT / 'tests/fixtures/colour-reference.json'
fixture = json.loads(fixture_path.read_text())
original_pixels = list(fixture['pixels'])
pixels = np.asarray(original_pixels, dtype=np.uint8).reshape(-1, 4)
catalog = json.loads((ROOT / 'public/catalog.json').read_text())
assets = {asset['path'].lstrip('/'): asset for combo in catalog['combinations']
          for asset in combo['files'].values()}
assets.update({look['std']['path'].lstrip('/'): look['std'] for look in catalog['suppliedFuji']['looks']})
# Preserve retained engine coverage; the retired official/paper fixtures are
# replaced by all nine supplied STD cubes, read by colour-science independently.
ids = {case['path'].split('/')[1] for case in fixture['fixtures']
       if case['path'].startswith('luts/') and not case['path'].split('/')[1].startswith('gfx_')}
assert ids and ids.issubset({combo['id'] for combo in catalog['combinations']})
fixture['fixtures'] = []
for combo in catalog['combinations']:
    if combo['id'] not in ids:
        continue
    if combo.get('stdMethod') != 'camera-vlog-alchemy-v1':
        raise ValueError('Refresh fixtures only after camera STD generation')
    camera = catalog['cameraAdapters']['defaultCamera']
    if combo['files']['std'] != combo['stdByCamera'][camera]['std']:
        raise ValueError('Default camera STD alias differs')
    fixture['fixtures'].append({'path': combo['files']['std']['path'].lstrip('/')})
assert len(fixture['fixtures']) == len(ids)
assert catalog['suppliedFuji']['methodId'] == 'supplied-fuji-std-v1'
assert len(catalog['suppliedFuji']['looks']) == 9
fixture['fixtures'].extend({'path': look['std']['path'].lstrip('/')} for look in catalog['suppliedFuji']['looks'])
for case in fixture['fixtures']:
    path = ROOT / 'public' / case['path']
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != assets[case['path']]['sha256']:
        raise ValueError(f'Catalog hash mismatch: {case["path"]}')
    lut = colour.read_LUT(str(path))
    rgb = lut.apply(pixels[:, :3] / 255.0,
                    interpolator=colour.algebra.table_interpolation_tetrahedral)
    if rgb.shape != pixels[:, :3].shape or not np.isfinite(rgb).all():
        raise ValueError('Invalid independent interpolation output')
    expected = pixels.copy()
    expected[:, :3] = np.floor(np.clip(rgb, 0, 1) * 255 + .5).astype(np.uint8)
    assert np.array_equal(expected[:, 3], pixels[:, 3])
    case['expected'] = expected.reshape(-1).tolist()
    case['sourceSha256'] = digest
assert fixture['pixels'] == original_pixels
fixture['reference'] = ('colour-science tetrahedral, independent parser; preserved 512 seeded random + '
                        '27 RGB boundary/midpoint colors; byte output rounded nearest, half up; alpha unchanged')
fixture['generator'] = 'scripts/refresh-colour-reference.py'
fixture['colourVersion'] = colour.__version__
fixture_path.write_text(json.dumps(fixture, separators=(',', ':')) + '\n')
print(json.dumps({'fixtures': len(fixture['fixtures']), 'rgbaPixelsPerFixture': len(pixels),
                  'inputAndAlphaPreserved': True, 'catalogHashesVerified': True,
                  'sourceSha256': [case['sourceSha256'] for case in fixture['fixtures']]}))
