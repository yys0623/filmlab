from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".cache/matplotlib"))
os.environ.setdefault("NUMBA_NUM_THREADS", "4")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np

CONFIG = json.loads((ROOT / "pipeline/config/default.json").read_text())
UPSTREAM = ROOT / "vendor/spektrafilm"
PROFILES = UPSTREAM / "src/spektrafilm/data/profiles"
PUBLIC = ROOT / "public"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    tmp.replace(path)


# Recommended print overrides on top of spektrafilm's `target_print`.
# Kodak's consumer films (Gold, MAX/Ultramax) are minilab films; Kodak's
# EKTACOLOR EDGE Generations data names them as the films that paper was tuned
# for, while upstream pairs them with the professional portrait paper.
RECOMMENDED_PRINT = {
    "kodak_gold_200": "kodak_ektacolor_edge",
    "kodak_ultramax_400": "kodak_ektacolor_edge",
}


def profiles():
    result = []
    for path in sorted(PROFILES.glob("*.json")):
        info = json.loads(path.read_text())["info"]
        result.append({"id": path.stem, "name": info["name"], "type": info["type"],
                       "stage": info["stage"], "brand": info["name"].split()[0],
                       "use": info.get("use"), "recommendedPrint": RECOMMENDED_PRINT.get(path.stem, info.get("target_print")),
                       "sha256": sha256(path)})
    return result


# Panasonic's published V-Gamut -> BT.709 matrix. Column vectors in the
# reference; RGB arrays here are row vectors, hence the transpose below.
VGAMUT_TO_SRGB = np.array([[1.806576, -0.695697, -0.110879],
                          [-0.170090, 1.305955, -0.135865],
                          [-0.025206, -0.154468, 1.179674]], dtype=np.float64)
SRGB_TO_VGAMUT = np.linalg.inv(VGAMUT_TO_SRGB)


def srgb_decode(rgb):
    rgb = np.asarray(rgb, dtype=np.float64)
    return np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)


def vlog_encode(linear):
    linear = np.asarray(linear, dtype=np.float64)
    return np.where(linear < 0.01, 5.6 * linear + 0.125,
                    0.241514 * np.log10(np.maximum(linear + 0.00873, 1e-12)) + 0.598206)


def std_to_vlog(rgb):
    """Analytic working model, NOT an inverse of Panasonic's proprietary style."""
    return vlog_encode(srgb_decode(rgb) @ SRGB_TO_VGAMUT.T)


def read_cube(path: Path, expected_tag=None):
    lines = path.read_text().splitlines()
    if not lines or not lines[0].startswith('TITLE "'):
        raise ValueError(f"Missing title: {path}")
    if expected_tag and lines[1] != f"#LUMIXPHOTOSTYLE {expected_tag}":
        raise ValueError(f"Wrong photo style: {path}")
    size = None
    domains = {}
    rows = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith(("#", "TITLE")):
            continue
        parts = line.split()
        if parts[0] == "LUT_3D_SIZE":
            size = int(parts[1])
        elif parts[0].startswith("DOMAIN_"):
            domains[parts[0]] = list(map(float, parts[1:]))
        else:
            if len(parts) != 3:
                raise ValueError("Expected exactly three channels")
            rows.append(list(map(float, parts)))
    if not size or len(rows) != size ** 3:
        raise ValueError(f"Invalid cube row count: {path}")
    if expected_tag and (size != 33 or domains != {"DOMAIN_MIN": [0., 0., 0.], "DOMAIN_MAX": [1., 1., 1.]}):
        raise ValueError("Unexpected domain or resolution")
    table = np.array(rows, dtype=np.float64).reshape(size, size, size, 3)
    if not np.isfinite(table).all():
        raise ValueError("Non-finite LUT")
    if expected_tag and (table.min() < 0 or table.max() > 1):
        raise ValueError("Out-of-range LUT")
    return table


def metrics(a, b):
    error = np.max(np.abs(np.asarray(a) - np.asarray(b)), axis=-1)
    return {"mean": float(error.mean()), "p95": float(np.percentile(error, 95)),
            "p99": float(np.percentile(error, 99)), "max": float(error.max()),
            "samples": int(error.size), "metric": "max absolute RGB channel error", "space": "encoded sRGB 0–1"}
