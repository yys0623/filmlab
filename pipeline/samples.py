"""Verified LUT-OFF S1M2 Standard captures and a synthetic sRGB chart."""
from pipeline.common import ROOT, PUBLIC, save_json, sha256
import json
import shutil
import numpy as np
from PIL import Image, ImageCms

SAMPLE_ROOT = ROOT / 'assets/samples'


def sample_definitions():
    return json.loads((SAMPLE_ROOT / 'manifest.json').read_text()) + [
        {"id": "chart", "name": "컬러 테스트", "category": "그레이 램프 · 색 패치", "credit": "Film Lab · generated technical test pattern · CC0", "source": None, "inputKind": "synthetic-srgb"},
    ]


def chart():
    result = np.zeros((400, 600, 3), dtype=np.uint8)
    colors = [(180,130,110),(115,80,65),(120,150,190),(80,120,70),(160,90,140),(50,160,175),
              (230,120,45),(80,85,170),(190,60,70),(130,80,140),(170,190,65),(235,170,45),
              (30,60,190),(40,155,70),(200,35,40),(230,210,40),(200,60,165),(35,170,195)]
    result[:300] = 32
    for i,c in enumerate(colors):
        y,x=divmod(i,6)
        result[y*100+8:(y+1)*100-8,x*100+8:(x+1)*100-8]=c
    result[310:] = np.round(np.linspace(0,255,600))[None,:,None].astype(np.uint8)
    return result


def save_image(rgb, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    Image.fromarray(np.round(np.clip(rgb,0,1)*255).astype(np.uint8)).save(path, quality=90, icc_profile=profile)


def prepare():
    samples = sample_definitions()
    (PUBLIC / 'samples').mkdir(parents=True, exist_ok=True)
    for sample in samples:
        sample["path"] = f"/samples/{sample['id']}.webp"
        destination = PUBLIC / sample['path'].lstrip('/')
        if sample['inputKind'] == 'camera-std':
            source = SAMPLE_ROOT / f"{sample['id']}.webp"
            if sha256(source) != sample['preparedSha256']:
                raise ValueError(f"Prepared sample hash mismatch: {sample['id']}")
            metadata = sample['cameraMetadata']
            if metadata['PhotoStyle'] != 'Standard or Custom' or metadata['LUT1Opacity'] != 0 or metadata['LUT2Opacity'] != 0:
                raise ValueError('Sample must be Standard with both camera LUTs disabled')
            shutil.copyfile(source, destination)
            if sample.get('thumbnailPath'):
                thumbnail_source = SAMPLE_ROOT / 'thumbs' / f"{sample['id']}.webp"
                if sha256(thumbnail_source) != sample['thumbnailSha256']:
                    raise ValueError(f"Prepared thumbnail hash mismatch: {sample['id']}")
                thumbnail_destination = PUBLIC / sample['thumbnailPath'].lstrip('/')
                thumbnail_destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(thumbnail_source, thumbnail_destination)
        else:
            save_image(chart()/255., destination)
        with Image.open(destination) as im:
            sample['width'], sample['height'] = im.size
        sample['input'] = 'Encoded sRGB / Standard pixels -> exported STD LUT directly (tetrahedral) -> sRGB'
        sample['previewLut'] = 'std'
    save_json(PUBLIC / 'samples/manifest.json', samples)
    return samples


if __name__ == "__main__":
    prepare()
