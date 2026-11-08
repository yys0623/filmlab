"""Current camera-STD artifacts preserve VLOG and retire historical A/B outputs."""
import hashlib
import io
import json
import zipfile
import colour
import numpy as np
import pytest
from pipeline.common import PUBLIC, ROOT, read_cube, sha256
from pipeline.camera_std import METHOD, BASELINE, models


def test_all_current_downloads_use_camera_specific_source_and_preserve_native_colour():
    catalog=json.loads((PUBLIC/'catalog.json').read_text())
    # 148 engine looks + 128 recommended-development variants (FUJI official looks retired).
    assert len(catalog['combinations'])==276
    expected={model['id'] for model in models()}
    for c in catalog['combinations']:
        assert c['stdMethod']==METHOD
        assert 'stdVariant' not in c and 'singleTonePrecurve' not in c['qa']
        assert c['qa']['cameraVerified'] is False
        assert c['qa']['vlogUnchanged'] is True
        assert set(c['stdByCamera'])==expected
        provenance=json.loads((PUBLIC/c['files']['provenance']['path'].lstrip('/')).read_text())
        assert provenance['composition']['extraToneCurve'] is False
        assert provenance['composition']['outputColourCorrection'] is False
        assert provenance['distribution']['vlogSha256']==c['files']['vlog']['sha256']
        assert provenance['cameraAdapter']['id']=='S1II'
        assert provenance['cameraAdapter']['validation']=='pending'


def test_original_vlog_matches_snapshot_before_camera_migration():
    if not (BASELINE/'catalog.json').exists():
        pytest.skip('Historical pre-migration snapshot is local audit evidence')
    previous=json.loads((BASELINE/'catalog.json').read_text())
    current=json.loads((PUBLIC/'catalog.json').read_text())
    by_id={c['id']:c for c in current['combinations']}
    for old in previous['combinations']:
        if old['id'].startswith('gfx_'):
            continue  # FUJI official looks were retired from the public catalog
        now=by_id[old['id']]
        assert now['files']['vlog']==old['files']['vlog']
        assert sha256(PUBLIC/old['files']['vlog']['path'].lstrip('/'))==old['files']['vlog']['sha256']
        saved=BASELINE/old['id']/old['files']['std']['name']
        assert sha256(saved)==old['files']['std']['sha256']
    # Runtime samples may be replaced independently; this snapshot protects
    # the creative VLOG and historical STD assets, not retired photographs.


def test_every_camera_bundle_contains_exact_selected_std_and_original_vlog():
    catalog=json.loads((PUBLIC/'catalog.json').read_text())
    for combo in catalog['combinations']:
        for camera, output in combo['stdByCamera'].items():
            with zipfile.ZipFile(PUBLIC/output['zip']['path'].lstrip('/')) as archive:
                assert len([name for name in archive.namelist() if name.endswith('.cube')])==2
                for asset in [output['std'],combo['files']['vlog']]:
                    raw=archive.read(asset['name'])
                    assert hashlib.sha256(raw).hexdigest()==asset['sha256']
                    assert len(asset['name'].split('.')[0])<=8
                qa=json.loads(archive.read('qa.json'))
                provenance=json.loads(archive.read('provenance.json'))
                assert qa['camera']==camera
                assert qa['stdMethod']==METHOD
                assert provenance['cameraAdapter']['id']==camera
                assert provenance['distribution']['stdSha256']==output['std']['sha256']
                assert qa['stdVsDirectEngine']==output['qa']
                assert archive.read(output['std']['name']).splitlines()[1]==b'#LUMIXPHOTOSTYLE STD'
