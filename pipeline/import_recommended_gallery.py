"""Import user-supplied WebPs for the recommended pairings gallery.

Run in film-lab: .venv/bin/python -m pipeline.import_recommended_gallery
--source /path/to/2601107_film/webp. ExifTool reads only the public allowlist;
the LUT filename in each WebP identifies the exact catalog film, paper and FC
variant. A filename does not authenticate the original LUT bytes or M/Y shifts.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from pipeline.common import PUBLIC, ROOT, save_json, sha256
from pipeline.import_user_gallery import (
    CAMERA_ID, CAMERA_NAME, EXPECTED_MODEL, EXIF_FIELDS, LICENSE,
    public_metadata, read_srgb, save_webp,
)

COLLECTION = 'recommended'
PREFIX = '/gallery/recommended'
EVIDENCE = 'camera-exif-lut-filename'


def lut_index() -> dict:
    """Use the UI's actual exporter function, not guesses based on name prefixes."""
    script = """
        import fs from 'node:fs';
        import {downloadFilename} from './src/lutNames.ts';
        const catalog = JSON.parse(fs.readFileSync('public/catalog.json', 'utf8'));
        const names = new Map();
        for (const combo of catalog.combinations) {
          if (combo.status !== 'ready' || combo.processMode !== 'negative_print') continue;
          const film = catalog.films.find(f => f.id === combo.film);
          const paper = catalog.papers.find(p => p.id === combo.paper);
          // Resolve the captured filename even if a paper recommendation
          // changes after the shoot. Never relabel a historic photograph.
          const name = downloadFilename(film, paper, combo.processMode, 'std', 'S1II', !!combo.castBaseId);
          if (names.has(name)) throw new Error(`Ambiguous exported LUT name: ${name}`);
          names.set(name, {filmId: film.id, paperId: paper.id, combinationId: combo.id});
        }
        console.log(JSON.stringify(Object.fromEntries(names)));
    """
    bundled = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
    for node in filter(None, [os.environ.get('NODE_BINARY'), shutil.which('node'), str(bundled)]):
        if not Path(node).is_file():
            continue
        version = subprocess.check_output([node, '--version'], text=True).strip().lstrip('v')
        if tuple(map(int, version.split('.')[:2])) >= (22, 12):
            return json.loads(subprocess.check_output([node, '--experimental-strip-types', '--input-type=module', '-e', script], cwd=ROOT, text=True))
    raise RuntimeError('Set NODE_BINARY to a Node.js 22.12+ executable to resolve catalog names')


def camera_metadata(paths: list[Path]) -> dict:
    fields = ('FileName', 'Model', 'DateTimeOriginal', 'ColorSpace', *EXIF_FIELDS)
    command = ['exiftool', '-json', '-charset', 'filename=UTF8', *(f'-{f}' for f in fields), *map(str, paths)]
    rows = json.loads(subprocess.check_output(command, text=True))
    by_name = {row['FileName']: row for row in rows}
    if len(rows) != len(paths) or set(by_name) != {p.name for p in paths}:
        raise ValueError('ExifTool did not identify every source photograph')
    return by_name


def identify(row: dict, index: dict) -> dict:
    if (row.get('Model') != EXPECTED_MODEL or row.get('PhotoStyle') != 'Standard or Custom'
            or row.get('LUT1Opacity') != 100 or row.get('LUT2Opacity') != 0):
        raise ValueError(f"Unexpected camera, photo style or LUT settings: {row['FileName']}")
    name = row.get('LUT1Name')
    if name not in index:
        raise ValueError(f"No catalog pairing for {row['FileName']}: {name!r}")
    return index[name]


def prepare(source: Path, row: dict, pair: dict, staging: Path) -> dict:
    # Use the selected WebP itself. Do not reprocess any sibling JPG through a LUT.
    image = read_srgb(source, row)
    key = source.stem.lower()
    full = staging / 'images' / f'{key}.webp'
    thumb = staging / 'thumbs' / full.name
    width, height = save_webp(image, full, 2400, 92)
    tw, th = save_webp(image, thumb, 480, 85)
    return {
        'id': key, 'sourceFilename': source.name, **pair,
        'path': f'{PREFIX}/images/{full.name}', 'thumbnailPath': f'{PREFIX}/thumbs/{thumb.name}',
        'width': width, 'height': height, 'thumbnailWidth': tw, 'thumbnailHeight': th,
        'cameraId': CAMERA_ID, 'cameraName': CAMERA_NAME,
        'capturedAt': datetime.strptime(row['DateTimeOriginal'], '%Y:%m:%d %H:%M:%S').isoformat(),
        'exif': public_metadata(row, EXIF_FIELDS), 'sourceSha256': sha256(source),
        'preparedSha256': sha256(full), 'thumbnailSha256': sha256(thumb),
        'filmEvidence': 'camera-exif-lut1-name', 'paperEvidence': EVIDENCE,
        'renderKind': 'camera-rendered', 'license': LICENSE,
        'credit': f'사용자 촬영 · {CAMERA_NAME} · {source.name}',
    }


def import_recommended(source: Path, jobs: int) -> dict:
    source = source.expanduser().resolve(strict=True)
    output = PUBLIC / 'gallery' / COLLECTION
    if output.resolve() in (source, *source.parents) or source in (output.resolve(), *output.resolve().parents):
        raise ValueError('Select an external source folder, not the published gallery')
    if output.is_symlink() or (output.exists() and json.loads((output / 'manifest.json').read_text())['id'] != COLLECTION):
        raise ValueError('Existing destination is not the generated recommended gallery')
    paths = sorted((p for p in source.iterdir() if p.is_file() and p.suffix.lower() == '.webp'), key=lambda p: p.name)
    if not paths or any(p.is_symlink() or not re.fullmatch(r'P\d+\.webp', p.name, re.I) for p in paths):
        raise ValueError('Expected camera WebP filenames (for example P1503852.webp)')
    if len({p.stem.lower() for p in paths}) != len(paths):
        raise ValueError('Duplicate camera filenames')
    index, metadata = lut_index(), camera_metadata(paths)
    pairs = {p.name: identify(metadata[p.name], index) for p in paths}
    # Publish only after preparing the complete collection. Never touch the
    # existing examples gallery or the Standard inputs in public/samples.
    (ROOT / 'artifacts').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ROOT / 'artifacts', prefix='recommended-gallery-') as temp:
        staging = Path(temp) / 'new'
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            items = list(pool.map(lambda p: prepare(p, metadata[p.name], pairs[p.name], staging), paths))
        counts = {'photos': len(items), 'films': len({i['filmId'] for i in items}),
                  'combinations': len({i['combinationId'] for i in items})}
        manifest = {
            'schemaVersion': 1, 'id': COLLECTION, 'title': {'ko': '추천 조합', 'en': 'Recommended pairings'},
            'source': 'user-provided', 'cameraId': CAMERA_ID, 'cameraName': CAMERA_NAME,
            'paperEvidence': EVIDENCE, 'license': LICENSE,
            'preparation': 'From user-supplied sRGB WebP; oriented, resized (2400px, thumbnails 480px), with sRGB ICC. No additional LUT or color editing. EXIF and XMP removed.',
            'counts': counts, 'items': items,
        }
        save_json(staging / 'manifest.json', manifest)
        backup = Path(temp) / 'previous'
        if output.exists():
            output.rename(backup)
        try:
            staging.rename(output)
        except OSError:
            if backup.exists():
                backup.rename(output)
            raise
    return counts


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--jobs', default=4, type=int, choices=range(1, 17))
    args = parser.parse_args()
    print(json.dumps(import_recommended(args.source, args.jobs)))
