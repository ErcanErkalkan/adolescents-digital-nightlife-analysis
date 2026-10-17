from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Iterable

REQUIRED_NOTICE_FILES = {
    "DATA_LICENSE_AND_ATTRIBUTION.md",
    "DATASET_ATTRIBUTION.md",
    "DATA_CHANGES.md",
    "LICENSE_SCOPE.md",
    "THIRD_PARTY_NOTICES.md",
    "LICENSES/CC-BY-4.0-NOTICE.txt",
}
OFFICIAL_NAMES = {"phone.csv", "game.csv", "social.csv", "video.csv", "timeframes.csv"}
CACHE_PARTS = {".venv", ".pytest_cache", "__pycache__", ".mypy_cache", ".ruff_cache"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def all_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def relative_files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in all_files(root)}


def contains_cache_or_binary_artifact(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if any(part in CACHE_PARTS for part in rel.parts):
        return True
    return path.suffix.lower() in {".pyc", ".pyo"}


def official_source_paths(root: Path) -> list[Path]:
    return sorted(p for p in (root / "data_raw").glob("*.csv") if p.name in OFFICIAL_NAMES)


def derived_data_paths(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for folder in [root / "data_processed", root / "outputs"]:
        if folder.exists():
            candidates.extend(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in {".csv", ".parquet", ".feather", ".json"})
    return sorted(candidates)


def check_source_hashes(root: Path) -> tuple[list[str], dict]:
    errors: list[str] = []
    manifest_path = root / "data_raw" / "download_manifest.json"
    if not manifest_path.exists():
        return ["data_raw/download_manifest.json is missing"], {}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"download_manifest.json is invalid: {exc}"], {}
    records = manifest.get("files", {})
    for logical, rec in records.items():
        filename = rec.get("path")
        expected = rec.get("sha256")
        if not filename or not expected:
            errors.append(f"download manifest record {logical!r} lacks path or sha256")
            continue
        path = root / "data_raw" / filename
        if not path.exists():
            errors.append(f"official source file missing: data_raw/{filename}")
            continue
        actual = sha256(path)
        if actual.lower() != str(expected).lower():
            errors.append(f"official source hash mismatch: data_raw/{filename}")
    return errors, manifest


def validate(root: Path, mode: str) -> dict:
    root = root.resolve()
    errors: list[str] = []
    warnings: list[str] = []
    files = relative_files(root)
    official = official_source_paths(root)
    derived = derived_data_paths(root)

    missing_notices = sorted(REQUIRED_NOTICE_FILES - files)
    if missing_notices:
        errors.extend(f"required notice missing: {x}" for x in missing_notices)

    license_text = (root / "LICENSE").read_text(encoding="utf-8", errors="replace") if (root / "LICENSE").exists() else ""
    if "does not apply" not in license_text.lower() or "dataset" not in license_text.lower():
        errors.append("top-level LICENSE does not explicitly exclude dataset/data-derived artifacts")

    scope_text = (root / "LICENSE_SCOPE.md").read_text(encoding="utf-8", errors="replace") if (root / "LICENSE_SCOPE.md").exists() else ""
    if "CC BY 4.0" not in scope_text or "MIT" not in scope_text:
        errors.append("LICENSE_SCOPE.md does not identify both MIT and CC BY 4.0 scopes")

    data_notice = (root / "DATA_LICENSE_AND_ATTRIBUTION.md").read_text(encoding="utf-8", errors="replace") if (root / "DATA_LICENSE_AND_ATTRIBUTION.md").exists() else ""
    for token in ["10.21942/uva.26395903.v2", "Teun Siebers", "CC BY 4.0", "changes", "data-inclusive", "code-only"]:
        if token.lower() not in data_notice.lower():
            errors.append(f"data license notice missing required element: {token}")

    contradictory_patterns = [
        r"this software package does not redistribute data files",
        r"dağıtılan pakette resm[iî] csv verileri bulunmaz",
        r"bu yazılım paketi veri dosyalarını yeniden dağıtmaz",
    ]
    if official:
        for p in all_files(root):
            if p.suffix.lower() not in {".md", ".txt", ".rst"}:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore").lower()
            for pattern in contradictory_patterns:
                if re.search(pattern, text):
                    errors.append(f"contradictory no-data claim while data are present: {p.relative_to(root)}")

    if mode == "code-only":
        if official:
            errors.append("code-only distribution contains official source CSV files")
        if any((root / "data_processed").glob("*.csv")) if (root / "data_processed").exists() else False:
            errors.append("code-only distribution contains processed CSV files")
        if (root / "outputs").exists() and any(p.is_file() and p.name != ".gitkeep" for p in (root / "outputs").rglob("*")):
            errors.append("code-only distribution contains generated outputs")
    elif mode == "data-inclusive":
        if {p.name for p in official} != OFFICIAL_NAMES:
            errors.append(f"data-inclusive distribution must contain exactly the five official CSV files; found {sorted(p.name for p in official)}")
        hash_errors, _ = check_source_hashes(root)
        errors.extend(hash_errors)
        dist_meta = root / "DISTRIBUTION_CONTENTS.json"
        if not dist_meta.exists():
            errors.append("data-inclusive distribution lacks DISTRIBUTION_CONTENTS.json")
    elif mode != "workspace":
        errors.append(f"unsupported validation mode: {mode}")

    dirty = [p.relative_to(root).as_posix() for p in all_files(root) if contains_cache_or_binary_artifact(p, root)]
    if dirty:
        if mode == "workspace":
            warnings.append("workspace contains cache/compiled/environment artifacts; clean builders exclude them: " + ", ".join(dirty[:10]))
        else:
            errors.append("distribution contains cache/compiled/environment artifacts: " + ", ".join(dirty[:10]))

    report = {
        "status": "passed" if not errors else "failed",
        "mode": mode,
        "root": str(root),
        "official_source_files": [p.relative_to(root).as_posix() for p in official],
        "derived_data_file_count": len(derived),
        "required_notice_files_present": not missing_notices,
        "errors": errors,
        "warnings": warnings,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate software/data license scope and redistribution notices.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--mode", choices=["workspace", "code-only", "data-inclusive"], default="workspace")
    parser.add_argument("--report")
    args = parser.parse_args()
    report = validate(Path(args.root), args.mode)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    print(text)
    if args.report:
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
