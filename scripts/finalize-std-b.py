#!/usr/bin/env python3
"""Make B the sole published STD, preserving every B/VLOG byte and local history.

Run after the historical A/B generator. This is packaging, not colour processing.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / 'public'


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def describe(root, filename):
    data = filename.read_bytes()
    return {'path': '/' + filename.relative_to(root).as_posix(), 'name': filename.name,
            'bytes': len(data), 'sha256': sha256(data).hexdigest()}


def read_verified(root, asset):
    assert not asset.get('encoding'), 'Finalize the unpacked authoring tree, before pack-static'
    filename = (root / asset['path'].lstrip('/')).resolve()
    assert filename.is_relative_to(root.resolve()), 'Unsafe asset path'
    data = filename.read_bytes()
    assert len(data) == asset['bytes'] and sha256(data).hexdigest() == asset['sha256'], filename
    return data


def bundle_readme(combo):
    return f'''Film Lab / {combo['film']} / {combo.get('paper') or 'direct'}

{combo['files']['vlog']['name']}: unchanged Panasonic V-Log / V-Gamut -> sRGB source renderer.
{combo['files']['std']['name']}: Standard/sRGB, B (18% linear-gray anchor + highlight roll-off).
The STB file uses #LUMIXPHOTOSTYLE STD. This bundle contains one STD and one VLOG LUT.
33 x 33 x 33; full range 0..1; output sRGB, NOT Rec.709.

One identical scalar input curve is applied to each RGB channel, then the
unchanged exported VLOG cube is evaluated tetrahedrally. Renderer RGB returns
unchanged: no output tone edit, neutral subtraction, chroma gain, OKLab bounds
or added output gamut mapping. Native colour casts remain.
B is identity through 18% linear gray (about code 117.65/255), then rolls off
to reachable white. B cannot retain detail below the native black floor.
Black/white are source endpoints, not measured photographic paper Dmin/Dmax.
No image statistics, automatic exposure or camera-specific measured inverse.
Existing source clipping cannot be recovered. Paired camera validation has
NOT been performed; compare same-scene V-Log + VLOG with Standard + STD.

All previews and uploads apply this exact STB file once, tetrahedrally.
stdVsDirectEngine measures B regridding against exact precurve + exported-VLOG
composition, not the continuous engine or physical film accuracy. VLOG QA
retains its original meaning. Source SHA256 and limits: provenance.json / qa.json.

spektrafilm: Andrea Volpato, https://github.com/andreavolpato/spektrafilm
SPEKTRAFILM_LICENSE.txt applies to upstream code/profiles and their derivatives.
Original third-party rights are preserved. Where FUJIFILM_NOTICE.txt is present,
FUJIFILM's original data retains its rights and is not relicensed under CC.
'''


def finalize(root=PUBLIC, archive=None):
    root = Path(root).resolve()
    catalog = json.loads((root / 'catalog.json').read_text())
    active = [c for c in catalog['combinations'] if c['processMode'] != 'reference_interpretation']
    assert len(active) == 238 and all(c['status'] == 'ready' for c in active)
    if all(c.get('stdVariant') == 'B' and set(c['files']) == {'std', 'vlog', 'zip', 'qa', 'provenance'} for c in active):
        for combo in active:
            for key in ('std', 'vlog'):
                read_verified(root, combo['files'][key])
        print('B-only catalog already finalized; 238 STD/VLOG pairs verified.')
        return
    assert all('stdB' in c['files'] and 'B' in c['stdVariants'] for c in active), 'Incomplete A/B input'
    # Verify all math-bearing input before changing any active files.
    for combo in active:
        for key in ('vlog', 'std', 'stdB', 'zip', 'qa', 'provenance'):
            read_verified(root, combo['files'][key])
    if archive is None:
        archive = ROOT / 'artifacts/std-b-only-archive'
        if archive.exists():
            archive = archive.with_name(archive.name + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    archive = Path(archive).resolve()
    assert not archive.is_relative_to(root) and not archive.exists(), 'Archive must be new and outside public'
    archive.mkdir(parents=True)
    shutil.copy2(root / 'catalog.json', archive / 'catalog.json')

    def preserve(filename):
        destination = archive / filename.relative_to(root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(filename, destination)

    checked = []
    for original in active:
        combo = deepcopy(original)
        directory = root / 'luts' / combo['id']
        with zipfile.ZipFile(root / combo['files']['zip']['path'].lstrip('/')) as old_zip:
            rights = {name: old_zip.read(name) for name in old_zip.namelist()
                      if name in ('SPEKTRAFILM_LICENSE.txt', 'FUJIFILM_NOTICE.txt')}
        assert 'SPEKTRAFILM_LICENSE.txt' in rights
        if combo.get('officialSource'):
            assert 'FUJIFILM_NOTICE.txt' in rights
        provenance = json.loads((directory / 'provenance.json').read_text())
        variant = deepcopy(combo['stdVariants']['B']['metadata'])
        combo['stdVariant'] = 'B'
        combo['files']['std'] = combo['files'].pop('stdB')
        combo.pop('stdVariants', None)
        combo['previewMode'] = 'runtime-std'
        combo['previews'] = {}
        qa = combo['qa']
        qa['stdVariant'] = 'B'
        qa['singleTonePrecurve'] = deepcopy(variant)
        qa.pop('stdVariants', None)
        qa['stdVsDirectEngine'] = qa.pop('stdBVsDirectEngine')
        qa['photoPixelFidelity'] = qa.pop('photoPixelFidelityB')
        response = qa['grayResponse']
        qa['grayResponse'] = {'inputCodes': response['inputCodes'], 'scale': response['scale'], 'rgb': response['B'],
                              'purpose': 'Exported B diagnostic, not physical camera/print calibration'}
        qa['grayBlackToWhiteDelta'] = sum(b-a for a, b in zip(response['B'][0], response['B'][-1])) / (3*255)
        qa['warnings'] = [warning for warning in qa['warnings'] if not warning.startswith('STD A ')]
        qa['cameraInterpolation'] = 'unknown; exported B tetrahedral and trilinear measured'
        # The pre-existing serialization bound covers B too; retain its conservative value.
        qa['stdSerializationBoundScope'] = 'Conservative bound measured during the source A/B export; B bytes unchanged.'
        provenance.pop('stdVariants', None)
        provenance['stdVariant'] = 'B'
        provenance['singleTonePrecurve'] = deepcopy(variant)
        provenance['preview'] = 'Standard/sRGB source pixels -> exported B STD LUT once, tetrahedral; no extra adapter or output edit.'
        provenance['distribution'] = {'stdVariant': 'B', 'stdSha256': combo['files']['std']['sha256'],
                                      'vlogSha256': combo['files']['vlog']['sha256'], 'colourDataRecomputed': False}
        # Move every replaced or retired file out of the served directory. Preserve
        # the selected B/VLOG and unchanged rights files in place.
        keep = {combo['files']['std']['name'], combo['files']['vlog']['name'], *rights}
        for filename in list(directory.iterdir()):
            if filename.name not in keep:
                preserve(filename)
        (directory / 'qa.json').write_bytes(encoded(qa))
        (directory / 'provenance.json').write_bytes(encoded(provenance))
        (directory / 'README.txt').write_text(bundle_readme(combo))
        (directory / 'CHANGELOG.txt').write_text('B-only distribution: keep the existing B STD and original VLOG bytes unchanged. Remove alternate STD versions and their previews. Update metadata and documentation to the selected B transform.\n')
        for name, data in rights.items():
            assert (directory / name).read_bytes() == data, f'Changed rights notice: {combo["id"]}/{name}'
        zip_path = directory / combo['files']['zip']['name']
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            names = [combo['files']['vlog']['name'], combo['files']['std']['name'], 'README.txt', 'CHANGELOG.txt', 'qa.json', 'provenance.json', *rights]
            for name in names:
                info = zipfile.ZipInfo(name, date_time=(2026, 11, 3, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                bundle.writestr(info, (directory / name).read_bytes(), compresslevel=9)
        for key in ('zip', 'qa', 'provenance'):
            combo['files'][key] = describe(root, directory / combo['files'][key]['name'])
        (directory / 'metadata.json').write_bytes(encoded(combo))
        with zipfile.ZipFile(zip_path) as bundle:
            for key, old_key in [('std', 'stdB'), ('vlog', 'vlog')]:
                asset = combo['files'][key]
                assert sha256(bundle.read(asset['name'])).hexdigest() == original['files'][old_key]['sha256']
            assert sum(name.endswith('.cube') for name in bundle.namelist()) == 2
        checked.append({'id': combo['id'], 'stdSha256': combo['files']['std']['sha256'], 'vlogSha256': combo['files']['vlog']['sha256']})
        original.clear()
        original.update(combo)
    removed = [combo for combo in catalog['combinations'] if combo['processMode'] == 'reference_interpretation']
    for combo in removed:
        preserve(root / 'luts' / combo['id'])
    for relative in ['legacy-v3', 'refined-v3', 'audit', 'research/reference-looks.json']:
        filename = root / relative
        if filename.exists():
            preserve(filename)
    catalog['combinations'] = active
    catalog.pop('referenceStudy', None)
    catalog['counts'] = {key: sum(combo['status'] == key for combo in active) for key in catalog['counts']}
    catalog['stdVariant'] = 'B'
    (root / 'catalog.json').write_bytes(encoded(catalog))
    (archive / 'preserved-b-vlog-hashes.json').write_bytes(encoded(checked))
    report = {'combinations': len(active), 'cubes': len(active)*2, 'archives': len(active),
              'stdBytesUnchanged': True, 'vlogBytesUnchanged': True, 'removedReferenceLooks': len(removed),
              'archiveDirectory': str(archive.relative_to(ROOT)) if archive.is_relative_to(ROOT) else str(archive)}
    (ROOT / 'artifacts/std-b-only-packaging.json').write_bytes(encoded(report))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public', type=Path, default=PUBLIC)
    parser.add_argument('--archive', type=Path)
    args = parser.parse_args()
    finalize(args.public, args.archive)
