from pipeline.common import PUBLIC, read_cube
import json
import zipfile
import hashlib


def test_every_bundle_contains_exact_downloads_and_attribution():
    catalog=json.loads((PUBLIC/'catalog.json').read_text())
    for combo in catalog['combinations']:
        if combo['status']!='ready':
            continue
        files=combo['files']
        with zipfile.ZipFile(PUBLIC/files['zip']['path'].lstrip('/')) as archive:
            assert archive.testzip() is None
            for key in ['vlog','std','qa','provenance'] + (['stdB'] if 'stdB' in files else []):
                asset=files[key]
                assert hashlib.sha256(archive.read(asset['name'])).hexdigest()==asset['sha256']
            for name in ['README.txt','CHANGELOG.txt','SPEKTRAFILM_LICENSE.txt']:
                assert name in archive.namelist()
            assert 'Andrea Volpato' in archive.read('README.txt').decode()
            assert 'CC BY-SA 4.0' in archive.read('SPEKTRAFILM_LICENSE.txt').decode()
