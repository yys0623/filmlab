"""Import user-supplied, already rendered S1II Standard LUTs without recolouring.

Run from the project root:
    .venv/bin/python -m pipeline.import_supplied_fuji --source /path/to/ALL_FUJI_LUT
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil

from .common import PUBLIC, ROOT, save_json


METHOD_ID = "supplied-fuji-std-v1"
CAMERA_ID = "S1II"
ARCHIVE = ROOT / "artifacts/sosang-update/retired-fuji"
LOOKS = [
    ("astia", "ASTIA", "ASTIA - STD.cube"),
    ("classic_chrome", "CLASSIC CHROME", "CLASSIC CHROME - STD.cube"),
    ("classic_neg", "CLASSIC Neg", "CLASSIC Neg - STD.cube"),
    ("eterna", "ETERNA", "ETERNA - STD v2.cube"),
    ("eterna_bleach_bypass", "ETERNA Bleach Bypass", "ETERNA BB - STD v2.cube"),
    ("pro_neg", "PRO Neg", "PRO Neg - STD.cube"),
    ("provia", "PROVIA", "PROVIA - STD.cube"),
    ("reala_ace", "REALA ACE", "REALA-ACE - STD v2.cube"),
    ("velvia", "VELVIA", "VELVIA - STD v2.cube"),
]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inspect_cube(data: bytes) -> dict:
    """Read the cube independently; omitted DOMAIN defaults to 0..1 per format.

    numericRowsSha256 hashes decimal tokens in row order, with a single ASCII
    space between tokens and a final LF per row. No float reserialization is
    involved, so original numeric precision is also checked.
    """
    lines = data.decode("utf-8-sig").splitlines()
    size = None
    domains = {"DOMAIN_MIN": [0., 0., 0.], "DOMAIN_MAX": [1., 1., 1.]}
    explicit_domains = set()
    rows = []
    numeric_min, numeric_max = math.inf, -math.inf
    for line in lines:
        line = line.strip()
        if not line or line.startswith(("#", "TITLE")):
            continue
        tokens = line.split()
        if tokens[0] == "LUT_3D_SIZE":
            if size is not None or len(tokens) != 2:
                raise ValueError("Ambiguous LUT_3D_SIZE")
            size = int(tokens[1])
        elif tokens[0] in domains:
            if len(tokens) != 4 or tokens[0] in explicit_domains:
                raise ValueError("Invalid or repeated domain")
            domains[tokens[0]] = list(map(float, tokens[1:]))
            explicit_domains.add(tokens[0])
        else:
            if len(tokens) != 3:
                raise ValueError("Expected three numeric channels")
            values = list(map(float, tokens))
            if not all(math.isfinite(value) and 0 <= value <= 1 for value in values):
                raise ValueError("Cube output must be finite and in 0..1")
            numeric_min = min(numeric_min, *values)
            numeric_max = max(numeric_max, *values)
            rows.append(" ".join(tokens) + "\n")
    if size != 33 or len(rows) != 33 ** 3:
        raise ValueError("Expected a 33³ cube with exactly 35,937 RGB rows")
    if domains != {"DOMAIN_MIN": [0., 0., 0.], "DOMAIN_MAX": [1., 1., 1.]}:
        raise ValueError("Only full-range 0..1 input is supported")
    if not lines or not lines[0].startswith('TITLE "'):
        raise ValueError("A cube TITLE must be the first line")
    style = [line.strip().split(maxsplit=1)[1] for line in lines if line.strip().startswith("#LUMIXPHOTOSTYLE ")]
    if style and style != ["STD"]:
        raise ValueError("Source must have no style tag or one STD tag")
    return {
        "resolution": size, "rows": len(rows), "domainMin": domains["DOMAIN_MIN"],
        "domainMax": domains["DOMAIN_MAX"], "minimum": numeric_min, "maximum": numeric_max,
        "numericRowsSha256": digest("".join(rows).encode("ascii")),
        "explicitDomains": sorted(explicit_domains), "styleTagPresent": bool(style),
    }


def prepare_cube(source: bytes, info: dict) -> tuple[bytes, list[str]]:
    # Keep every original line, decimal token, comment and title byte-for-byte.
    # Adding metadata does not constitute a LUT composition or numeric edit.
    lines = source.splitlines(keepends=True)
    additions = []
    if not info["styleTagPresent"]:
        additions.append(b"#LUMIXPHOTOSTYLE STD\n")
    for key, line in [
        ("DOMAIN_MIN", b"DOMAIN_MIN 0.0 0.0 0.0\n"),
        ("DOMAIN_MAX", b"DOMAIN_MAX 1.0 1.0 1.0\n"),
    ]:
        if key not in info["explicitDomains"]:
            additions.append(line)
    prepared = lines[0] + b"".join(additions) + b"".join(lines[1:])
    return prepared, [line.decode("ascii").strip() for line in additions]


def asset(path: Path) -> dict:
    data = path.read_bytes()
    return {"path": "/" + path.relative_to(PUBLIC).as_posix(), "name": path.name,
            "bytes": len(data), "sha256": digest(data)}


def archive_path(source: Path, relative: Path) -> None:
    if not source.exists():
        return
    target = ARCHIVE / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        # Do not overwrite a prior archive. A regenerated historical tree gets
        # a separate, content-identified recovery directory.
        if source.is_file() and target.read_bytes() == source.read_bytes():
            source.unlink()
            return
        suffix = 2
        while target.with_name(f"{target.name}-{suffix}").exists():
            suffix += 1
        target = target.with_name(f"{target.name}-{suffix}")
    shutil.move(str(source), str(target))


def import_supplied(source_directory: Path) -> dict:
    source_directory = source_directory.resolve(strict=True)
    expected = {name for _, _, name in LOOKS}
    actual = {path.name for path in source_directory.iterdir() if path.is_file() and path.suffix.lower() == ".cube"}
    if actual != expected:
        raise ValueError(f"Unexpected cube inventory: missing={sorted(expected - actual)}, extra={sorted(actual - expected)}")
    # Validate all nine before mutating catalog or active assets.
    prepared_looks = []
    for slug, name, filename in LOOKS:
        source = (source_directory / filename).read_bytes()
        source_info = inspect_cube(source)
        prepared, additions = prepare_cube(source, source_info)
        prepared_info = inspect_cube(prepared)
        if prepared_info["numericRowsSha256"] != source_info["numericRowsSha256"]:
            raise ValueError(f"Numeric rows changed: {filename}")
        prepared_looks.append((slug, name, filename, source, prepared, source_info, additions))
    catalog_path = PUBLIC / "catalog.json"
    original_catalog_bytes = catalog_path.read_bytes()
    catalog = json.loads(original_catalog_bytes)
    retired_ids = {film["id"] for film in catalog["films"] if film["type"] == "official"}
    retired_combos = [combo for combo in catalog["combinations"]
                      if combo["film"] in retired_ids or combo.get("processMode") in ("official_direct", "official_print")]
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    if retired_combos and not (ARCHIVE / "catalog-before.json").exists():
        (ARCHIVE / "catalog-before.json").write_bytes(original_catalog_bytes)
    for combo in retired_combos:
        archive_path(PUBLIC / "luts" / combo["id"], Path("public/luts") / combo["id"])
    # Catch historical directories even if the import was interrupted between
    # updating the manifest and retiring files.
    for directory in (PUBLIC / "luts").glob("gfx_*"):
        archive_path(directory, Path("public/luts") / directory.name)
    archive_path(PUBLIC / "research/fujifilm-official.json", Path("public/research/fujifilm-official.json"))
    catalog["films"] = [film for film in catalog["films"] if film["id"] not in retired_ids]
    catalog["combinations"] = [combo for combo in catalog["combinations"]
                               if combo["film"] not in retired_ids and combo.get("processMode") not in ("official_direct", "official_print")]
    catalog.pop("fujiStudy", None)
    catalog["counts"] = {status: sum(combo["status"] == status for combo in catalog["combinations"])
                         for status in ["ready", "failed", "unsupported", "not-generated"]}
    if len(catalog["combinations"]) != 148:
        raise ValueError("Expected exactly 148 existing engine combinations after retirement")
    output = PUBLIC / "supplied-fuji"
    output.mkdir(exist_ok=True)
    looks, records = [], []
    for slug, name, filename, source, prepared, info, additions in prepared_looks:
        destination = output / f"fuji-{slug.replace('_', '-')}-s1ii-std.cube"
        destination.write_bytes(prepared)
        std_asset = asset(destination)
        looks.append({
            "stock": {"id": f"fuji_sim_{slug}", "name": f"FUJIFILM {name}",
                      "type": "supplied", "stage": "digital", "brand": "Fujifilm",
                      "use": "digital_simulation", "recommendedPrint": None,
                      "sha256": digest(source)},
            "std": std_asset, "sourceFile": filename, "sourceSha256": digest(source),
        })
        records.append({
            "id": f"fuji_sim_{slug}", "name": name, "sourceFile": filename,
            "sourceSha256": digest(source), "sourceBytes": len(source),
            "distributed": std_asset, "metadataAdded": additions,
            "resolution": info["resolution"], "rows": info["rows"],
            "domainMin": info["domainMin"], "domainMax": info["domainMax"],
            "minimum": info["minimum"], "maximum": info["maximum"],
            "numericRowsSha256": info["numericRowsSha256"], "numericRowsUnchanged": True,
        })
    notice = """sosang — supplied FUJIFILM simulation LUTs
==========================================

These nine files were supplied by the site owner as already processed
Panasonic S1II Standard-input LUTs. They are edited digital simulation LUTs,
not unmodified official FUJIFILM LUT downloads or measured physical film.
FUJIFILM names identify the look; they do not indicate endorsement.

This import preserves all numeric RGB rows, original titles and source
comments. It adds only the Panasonic #LUMIXPHOTOSTYLE STD tag and, when
omitted, explicit default DOMAIN_MIN/DOMAIN_MAX metadata. No paper rendering,
V-Log Alchemy adapter, exposure change, colour correction or rebaking is
applied. The browser uses the resulting cube directly with tetrahedral
interpolation. No V-Log variant or other-camera adaptation is claimed.

The source author and license were not provided with these files. No new
license or third-party permission is asserted by this import. In particular,
the application's license and spektrafilm's license do not relicense them.
Original filenames, SHA-256 hashes, distributed hashes and the verification
of unchanged numeric rows are recorded in provenance.json.
"""
    (output / "NOTICE.txt").write_text(notice, encoding="utf-8")
    provenance = {
        "schemaVersion": 1, "methodId": METHOD_ID, "sourceKind": "user-supplied-edited-luts",
        "cameraId": CAMERA_ID, "cameraName": "LUMIX S1II", "input": "Panasonic S1II Standard",
        "cameraEvidence": "Site-owner supplied S1II Standard workflow; some source headers explicitly identify Panasonic S1M2. No independent multi-camera calibration.",
        "output": "Display RGB as encoded in the supplied cubes; interpreted as sRGB for browser previews.",
        "paper": None, "additionalTransform": None, "interpolation": "tetrahedral",
        "officialUnmodifiedProduct": False, "author": None, "license": None,
        "licenseStatus": "not-provided", "sourceFileInventory": "ALL_FUJI_LUT",
        "numericRowsHashFormat": "SHA-256 of original decimal tokens, single ASCII space between channels, LF after each row; headers and comments omitted; source row order preserved.",
        "looks": records,
    }
    save_json(output / "provenance.json", provenance)
    catalog["suppliedFuji"] = {
        "methodId": METHOD_ID, "cameraId": CAMERA_ID, "looks": looks,
        "provenance": asset(output / "provenance.json"), "notice": asset(output / "NOTICE.txt"),
    }
    save_json(catalog_path, catalog)
    report = {"methodId": METHOD_ID, "sourceDirectory": str(source_directory),
              "retiredCombinationsThisRun": len(retired_combos), "engineCombinations": len(catalog["combinations"]),
              "suppliedLooks": len(looks), "allNumericRowsUnchanged": True, "looks": records}
    save_json(ROOT / "artifacts/sosang-update/supplied-fuji-import.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Folder containing the nine supplied STD cubes")
    args = parser.parse_args()
    report = import_supplied(args.source)
    print(json.dumps({key: report[key] for key in ["methodId", "retiredCombinationsThisRun", "engineCombinations", "suppliedLooks", "allNumericRowsUnchanged"]}))


if __name__ == "__main__":
    main()
