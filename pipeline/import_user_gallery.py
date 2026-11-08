"""Import the user's camera-rendered gallery and verified LUT-OFF STD samples.

Run from the repository root with ``python -m pipeline.import_user_gallery
--source /path/to/261104_film``. No colour LUT or automatic tone operation is
performed here. EXIF identifies the film; paper identification comes from the
user's statement that the app's recommended paper was selected.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from io import BytesIO
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

from PIL import Image, ImageCms, ImageOps

from pipeline.common import PUBLIC, ROOT, save_json, sha256

COLLECTION_ID = '261104_film'
# Photographer-requested exclusions; keep the source JPGs untouched.
EXCLUDED_FILENAMES = frozenset({'P1503810.JPG', 'P1503811.JPG', 'P1503812.JPG'})
CAMERA_ID = 'S1II'
CAMERA_NAME = 'LUMIX S1II'
EXPECTED_MODEL = 'DC-S1M2'
FILM_NAMES = {
    'Fujifilm C200 Alchemy TEST.cube': 'fujifilm_c200',
    'Kodak Gold 200.cube': 'kodak_gold_200',
    'Kodak Ektar 100 .cube': 'kodak_ektar_100',
    'Kodak Vision3 200T.cube': 'kodak_vision3_200t',
    'Fujifilm Velvia 100.cube': 'fujifilm_velvia_100',
}
EXIF_FIELDS = (
    'PhotoStyle', 'LUT1Name', 'LUT1Opacity', 'LUT2Name', 'LUT2Opacity',
    'ISO', 'FNumber', 'ExposureTime', 'ExposureCompensation', 'WhiteBalance',
    'LensModel',
)
SAMPLE_METADATA_FIELDS = (
    'Model', *EXIF_FIELDS, 'ColorSpace', 'ImageWidth', 'ImageHeight',
    'Orientation', 'Contrast', 'Saturation', 'Sharpness',
)
EXTRACT_FIELDS = ('FileName', 'DateTimeOriginal', *SAMPLE_METADATA_FIELDS)
SAMPLE_NAMES = {
    'P1503769': ('노란 자전거', 'Yellow bicycles', '야외 · 노랑과 그늘', 'Outdoors · yellow and shade'),
    'P1503770': ('가을 산책로', 'Autumn path', '야외 · 단풍과 햇살', 'Outdoors · autumn leaves and sunlight'),
    'P1503771': ('햇살 아래 벤치', 'Sunlit bench', '야외 · 갈색과 그림자', 'Outdoors · browns and shadows'),
    'P1503778': ('단풍길', 'Autumn walkway', '야외 · 가로수와 암부', 'Outdoors · trees and shadows'),
    'P1503784': ('그늘 속 자전거', 'Bicycles in shade', '야외 · 노랑과 파랑', 'Outdoors · yellow and blue'),
    'P1503791': ('붉은 단풍나무', 'Red maple trees', '야외 · 빨강과 역광', 'Outdoors · reds and backlight'),
    'P1503797': ('단풍과 하늘', 'Maple leaves and sky', '야외 · 빨강과 푸른 하늘', 'Outdoors · red leaves and blue sky'),
    'P1503798': ('공원과 도시', 'Park and city', '야외 · 건물과 녹색', 'Outdoors · buildings and greens'),
    'P1503804': ('건물과 가을 하늘', 'Building and autumn sky', '야외 · 건축과 하늘', 'Outdoors · architecture and sky'),
    'P1503813': ('햇살 든 가로수길', 'Sunlit tree-lined path', '야외 · 노란 단풍과 하늘', 'Outdoors · yellow leaves and sky'),
    'P1503819': ('가로수와 푸른 하늘', 'Trees and blue sky', '야외 · 단풍과 푸른 하늘', 'Outdoors · autumn trees and blue sky'),
    'P1503825': ('낙엽 위 그림자', 'Shadow on fallen leaves', '야외 · 낙엽과 그림자', 'Outdoors · fallen leaves and shadows'),
    'P1503831': ('잔디와 낙엽', 'Grass and fallen leaves', '야외 · 녹색과 갈색', 'Outdoors · greens and browns'),
}
LICENSE = 'User photograph; all rights reserved. Not covered by the LUT or source-code license.'


# Gold 200 was re-recommended on Ektacolor Edge after this collection was shot.
RECOMMENDED_AT_CAPTURE = {'kodak_gold_200': 'kodak_portra_endura'}

def srgb_profile_bytes() -> bytes:
    """Fixed ICC timestamp keeps repeated imports byte reproducible."""
    profile = bytearray(ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
    profile[24:36] = struct.pack('>6H', 2000, 1, 1, 0, 0, 0)
    profile[84:100] = bytes(16)  # Optional ICC profile ID, deliberately unset.
    return bytes(profile)


SRGB_PROFILE = srgb_profile_bytes()


def extract_metadata(source: Path) -> list[dict]:
    """Ask ExifTool only for public-safe fields, not location or serial data."""
    paths = sorted(p for p in source.iterdir() if p.is_file() and p.suffix.lower() in ('.jpg', '.jpeg'))
    if not paths:
        raise ValueError('No JPEG photographs found')
    command = ['exiftool', '-json', '-charset', 'filename=UTF8']
    command.extend(f'-{field}' for field in dict.fromkeys(EXTRACT_FIELDS))
    command.extend(str(p) for p in paths)
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    rows = json.loads(result.stdout)
    if len(rows) != len(paths):
        raise ValueError('ExifTool did not return every input photograph')
    return rows


def classify(row: dict) -> str | None:
    if row.get('Model') != EXPECTED_MODEL or row.get('PhotoStyle') != 'Standard or Custom':
        raise ValueError(f"Unexpected camera or PhotoStyle: {row.get('FileName')}")
    if row.get('LUT2Opacity') != 0:
        raise ValueError(f"Second LUT must be disabled: {row.get('FileName')}")
    opacity = row.get('LUT1Opacity')
    if opacity == 0:
        return None
    if opacity != 100 or row.get('LUT1Name') not in FILM_NAMES:
        raise ValueError(f"Unrecognised LUT or opacity: {row.get('FileName')}")
    return FILM_NAMES[row['LUT1Name']]


def public_metadata(row: dict, fields: tuple[str, ...]) -> dict:
    return {key: value.strip() if isinstance(value, str) else value
            for key in fields if (value := row.get(key)) is not None}


def read_srgb(source: Path, row: dict) -> Image.Image:
    """Orient the photograph and honour its source colour profile."""
    with Image.open(source) as original:
        original.load()
        profile = original.info.get('icc_profile')
        oriented = ImageOps.exif_transpose(original)
        rgb = oriented.convert('RGB')
        if profile:
            incoming = ImageCms.ImageCmsProfile(BytesIO(profile))
            description = ImageCms.getProfileDescription(incoming).strip().lower()
            # Native sRGB photographs retain their exact decoded RGB values.
            if 'srgb' not in description:
                rgb = ImageCms.profileToProfile(rgb, incoming,
                    ImageCms.ImageCmsProfile(BytesIO(SRGB_PROFILE)),
                    renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
                    outputMode='RGB')
        elif row.get('ColorSpace') != 'sRGB':
            raise ValueError(f"Untagged non-sRGB photograph: {source.name}")
        rgb.info.clear()  # Do not propagate EXIF, XMP, GPS or maker notes.
        return rgb


def save_webp(image: Image.Image, destination: Path, edge: int, quality: int) -> tuple[int, int]:
    image = image.copy()
    image.thumbnail((edge, edge), Image.Resampling.LANCZOS)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, format='WEBP', quality=quality, method=4,
               icc_profile=SRGB_PROFILE, exif=b'', xmp=b'')
    return image.size


def prepare_photo(row: dict, films: dict, combinations: list[dict], staging: Path) -> tuple[str, dict]:
    source = Path(row['SourceFile'])
    film_id = classify(row)
    image = read_srgb(source, row)
    source_hash = sha256(source)
    capture_time = datetime.strptime(row['DateTimeOriginal'], '%Y:%m:%d %H:%M:%S').isoformat()
    if film_id is None:
        photo_id = f'std_{source.stem.lower()}'
        destination = staging / 'assets-samples' / f'{photo_id}.webp'
        width, height = save_webp(image, destination, 1920, 95)
        thumbnail = staging / 'assets-samples/thumbs' / f'{photo_id}.webp'
        thumb_width, thumb_height = save_webp(image, thumbnail, 480, 85)
        names = SAMPLE_NAMES.get(source.stem, (source.stem, source.stem, '야외 · Standard', 'Outdoors · Standard'))
        return 'sample', {
            'id': photo_id, 'name': names[0], 'nameEn': names[1],
            'category': names[2], 'categoryEn': names[3],
            'credit': f'사용자 촬영 · {CAMERA_NAME} · {source.name} · Standard / LUT OFF',
            'creditEn': f'User photograph · {CAMERA_NAME} · {source.name} · Standard / LUT OFF',
            'source': None, 'sourceFilename': source.name, 'inputKind': 'camera-std',
            'cameraId': CAMERA_ID, 'cameraName': CAMERA_NAME, 'capturedAt': capture_time,
            'originalSha256': source_hash, 'preparedSha256': sha256(destination),
            'thumbnailPath': f'/samples/thumbs/{photo_id}.webp',
            'thumbnailSha256': sha256(thumbnail),
            'thumbnailWidth': thumb_width, 'thumbnailHeight': thumb_height,
            'cameraMetadata': public_metadata(row, SAMPLE_METADATA_FIELDS),
            'license': LICENSE, 'width': width, 'height': height,
            'preparation': 'EXIF orientation applied; resized to max 1920px with Lanczos; WebP quality 95 with sRGB ICC; source ICC honoured; no LUT, tone or saturation edit; EXIF and XMP removed.',
        }
    # Keep the paper that was recommended when the photographs were taken.
    paper_id = RECOMMENDED_AT_CAPTURE.get(film_id, films[film_id]['recommendedPrint'])
    matches = [c for c in combinations if c['film'] == film_id and c['paper'] == paper_id]
    if len(matches) != 1:
        raise ValueError(f'Expected one recommended combination for {film_id}, found {len(matches)}')
    photo_id = source.stem.lower()
    relative = Path(COLLECTION_ID) / f'{photo_id}.webp'
    thumb_relative = Path(COLLECTION_ID) / 'thumbs' / f'{photo_id}.webp'
    destination = staging / 'gallery' / relative
    thumbnail = staging / 'gallery' / thumb_relative
    width, height = save_webp(image, destination, 2400, 92)
    thumb_width, thumb_height = save_webp(image, thumbnail, 480, 85)
    return 'gallery', {
        'id': photo_id, 'sourceFilename': source.name,
        'filmId': film_id, 'paperId': paper_id, 'combinationId': matches[0]['id'],
        'path': f'/gallery/{relative.as_posix()}', 'thumbnailPath': f'/gallery/{thumb_relative.as_posix()}',
        'width': width, 'height': height, 'thumbnailWidth': thumb_width, 'thumbnailHeight': thumb_height,
        'cameraId': CAMERA_ID, 'cameraName': CAMERA_NAME, 'capturedAt': capture_time,
        'exif': public_metadata(row, EXIF_FIELDS),
        'sourceSha256': source_hash, 'preparedSha256': sha256(destination),
        'thumbnailSha256': sha256(thumbnail),
        'filmEvidence': 'camera-exif-lut1-name', 'paperEvidence': 'user-confirmed-recommended',
        'renderKind': 'camera-rendered',
        'credit': f'사용자 촬영 · {CAMERA_NAME} · {source.name}',
        'license': LICENSE,
    }


def archive_previous_samples() -> None:
    archive = ROOT / 'artifacts/gallery-261104/previous-samples'
    for source, relative in ((ROOT / 'assets/samples', 'assets/samples'), (PUBLIC / 'samples', 'public/samples')):
        destination = archive / relative
        if source.exists() and not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, destination)


def import_gallery(source: Path, jobs: int = 4) -> dict:
    source = source.expanduser().resolve(strict=True)
    catalog_path = PUBLIC / 'catalog.json'
    catalog = json.loads(catalog_path.read_text())
    films = {film['id']: film for film in catalog['films']}
    rows = [row for row in extract_metadata(source)
            if row['FileName'].upper() not in EXCLUDED_FILENAMES]
    for row in rows:
        classify(row)  # Fail before changing any live asset.
    artifact_root = ROOT / 'artifacts/gallery-261104'
    artifact_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='import-', dir=artifact_root) as tmp:
        staging = Path(tmp)
        with ThreadPoolExecutor(max_workers=jobs) as executor:
            prepared = list(executor.map(lambda row: prepare_photo(row, films, catalog['combinations'], staging), rows))
        samples = sorted((item for kind, item in prepared if kind == 'sample'), key=lambda item: item['capturedAt'])
        photos = sorted((item for kind, item in prepared if kind == 'gallery'), key=lambda item: item['capturedAt'])
        if not samples or not photos:
            raise ValueError('Both LUT-OFF samples and camera-rendered photographs are required')
        film_counts = Counter(item['filmId'] for item in photos)
        manifest = {
            'schemaVersion': 1, 'id': COLLECTION_ID,
            'title': {'ko': '가을을 담은 다섯 가지 필름', 'en': 'Autumn in five film looks'},
            'cameraId': CAMERA_ID, 'cameraName': CAMERA_NAME, 'source': 'user-provided',
            'paperEvidence': 'user-confirmed-recommended',
            'filmEvidence': 'camera-exif-lut1-name', 'renderKind': 'camera-rendered',
            'description': {
                'ko': '카메라에서 LUT를 적용해 촬영한 JPEG입니다. 필름은 EXIF의 LUT 이름으로 확인했으며 인화지는 사용자가 확인한 웹앱 추천 조합입니다. 추가 LUT나 색 보정을 적용하지 않았습니다.',
                'en': 'JPEG photographs with a LUT applied in camera. Film is identified from the EXIF LUT name; paper is the app recommendation confirmed by the photographer. No additional LUT or colour adjustment is applied.',
            },
            'paperEvidenceNote': 'Paper is not independently encoded in EXIF; assigned from the photographer-confirmed catalog recommendation. Velvia 100 is a direct slide scan with no paper.',
            'preparation': 'EXIF orientation applied; source ICC honoured; resized with Lanczos to max 2400px; WebP quality 92, thumbnails max 480px quality 85; embedded sRGB ICC; EXIF/XMP removed. No LUT, tone or saturation edit. Original files remain untouched.',
            'capturedAtTimezone': 'camera-local; no offset present in source EXIF',
            'license': LICENSE, 'items': photos,
            'counts': {'photos': len(photos), 'standardSamples': len(samples), 'films': len(film_counts)},
            'filmCounts': dict(sorted(film_counts.items())),
        }
        save_json(staging / 'assets-samples/manifest.json', samples)
        save_json(staging / 'gallery/manifest.json', manifest)
        archive_previous_samples()
        # Only generated directories are replaced. User originals are read-only.
        for destination, prepared_directory in ((ROOT / 'assets/samples', staging / 'assets-samples'), (PUBLIC / 'gallery', staging / 'gallery')):
            if destination.exists():
                shutil.rmtree(destination)
            shutil.move(str(prepared_directory), str(destination))
        if (PUBLIC / 'samples').exists():
            shutil.rmtree(PUBLIC / 'samples')
        from pipeline.samples import prepare
        catalog['samples'] = prepare()
        save_json(catalog_path, catalog)
        save_json(artifact_root / 'import-report.json', {
            'galleryManifest': '/gallery/manifest.json', 'counts': manifest['counts'],
            'filmCounts': manifest['filmCounts'],
            'galleryBytes': sum(path.stat().st_size for path in (PUBLIC / 'gallery').rglob('*') if path.is_file()),
            'sampleBytes': sum(path.stat().st_size for path in (PUBLIC / 'samples').rglob('*') if path.is_file()),
            'sourceImagesModified': False,
            'previousSamplesArchive': 'artifacts/gallery-261104/previous-samples',
        })
        return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.jobs <= 16:
        parser.error('--jobs must be between 1 and 16')
    imported = import_gallery(args.source, args.jobs)
    print(json.dumps({'counts': imported['counts'], 'filmCounts': imported['filmCounts']}, indent=2))
