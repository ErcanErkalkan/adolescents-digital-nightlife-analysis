from __future__ import annotations

import argparse
import fnmatch
import json
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
import shutil

from audit_portability import audit as audit_portability
from validate_license_scope import check_source_hashes, sha256, validate


def load_allowlist(source: Path) -> dict:
    path = source / "DISTRIBUTION_ALLOWLIST.json"
    if not path.exists():
        raise RuntimeError(f"explicit distribution allowlist is missing: {path}")
    policy = json.loads(path.read_text(encoding="utf-8"))
    if not policy.get("common_patterns"):
        raise RuntimeError("distribution allowlist has no common_patterns")
    return policy


def matches_any(rel: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(rel, pattern) for pattern in patterns)


def should_include(rel: Path, mode: str, policy: dict) -> bool:
    rel_text = rel.as_posix()
    patterns = list(policy["common_patterns"])
    if mode == "data-inclusive":
        patterns.extend(policy.get("data_inclusive_patterns", []))
    return matches_any(rel_text, patterns)


def copy_allowlisted_tree(source: Path, staging: Path, mode: str, policy: dict) -> list[str]:
    copied: list[str] = []
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(source)
        if not should_include(rel, mode, policy):
            continue
        target = staging / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied.append(rel.as_posix())
    return copied


def required_patterns_satisfied(staging: Path, mode: str, policy: dict) -> list[str]:
    existing = [p.relative_to(staging).as_posix() for p in staging.rglob("*") if p.is_file()]
    errors: list[str] = []
    patterns = list(policy["common_patterns"])
    if mode == "data-inclusive":
        patterns.extend(policy.get("data_inclusive_patterns", []))
    for pattern in patterns:
        if not any(fnmatch.fnmatchcase(rel, pattern) for rel in existing):
            errors.append(f"allowlisted required pattern did not match a source file: {pattern}")
    return errors


def build_contents(staging: Path, mode: str, source_root: Path, copied: list[str]) -> dict:
    source_hash_records = []
    if mode == "data-inclusive":
        errors, manifest = check_source_hashes(staging)
        if errors:
            raise RuntimeError("; ".join(errors))
        for logical, rec in manifest.get("files", {}).items():
            source_hash_records.append({
                "logical_name": logical,
                "path": f"data_raw/{rec['path']}",
                "sha256": rec["sha256"],
                "status": "unmodified_official_source_file",
                "license": "CC BY 4.0",
            })
    return {
        "schema_version": 2,
        "distribution_mode": mode,
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "software_license": "MIT",
        "dataset_license": "CC BY 4.0",
        "dataset_doi": "10.21942/uva.26395903.v2",
        "dataset_creators": ["Teun Siebers", "Ine Beyens", "Susanne E. Baumgartner", "Patti M. Valkenburg"],
        "source_files": source_hash_records,
        "data_included": mode == "data-inclusive",
        "generated_results_included": False,
        "processed_participant_data_included": False,
        "virtual_environment_included": False,
        "platform_specific_binaries_included": False,
        "allowlist_file": "DISTRIBUTION_ALLOWLIST.json",
        "copied_source_file_count": len(copied),
        "source_workspace": source_root.name,
    }


def write_manifest(root: Path) -> None:
    rows = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != "PACKAGE_MANIFEST.sha256":
            rows.append(f"{sha256(p)}  {p.relative_to(root).as_posix()}")
    (root / "PACKAGE_MANIFEST.sha256").write_text("\n".join(rows) + "\n", encoding="utf-8")


def verify_manifest(root: Path) -> list[str]:
    errors = []
    path = root / "PACKAGE_MANIFEST.sha256"
    if not path.exists():
        return ["PACKAGE_MANIFEST.sha256 is missing"]
    expected: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if "  " not in line:
            errors.append(f"malformed manifest line {line_number}")
            continue
        digest, rel = line.split("  ", 1)
        if rel in expected:
            errors.append(f"duplicate manifest path: {rel}")
        if rel.startswith("/") or ".." in Path(rel).parts:
            errors.append(f"unsafe manifest path: {rel}")
        expected[rel] = digest
    actual_files = {
        p.relative_to(root).as_posix(): p
        for p in root.rglob("*")
        if p.is_file() and p.name != "PACKAGE_MANIFEST.sha256"
    }
    if set(expected) != set(actual_files):
        missing = sorted(set(expected) - set(actual_files))
        extra = sorted(set(actual_files) - set(expected))
        errors.append(f"manifest file set mismatch; missing={missing}, extra={extra}")
    for rel, digest in expected.items():
        p = actual_files.get(rel)
        if p and sha256(p) != digest:
            errors.append(f"manifest hash mismatch: {rel}")
    return errors


def deterministic_zip(source: Path, destination: Path, top_name: str) -> None:
    epoch = (2026, 7, 18, 0, 0, 0)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in sorted(source.rglob("*")):
            if not p.is_file():
                continue
            rel = Path(top_name) / p.relative_to(source)
            info = zipfile.ZipInfo(rel.as_posix(), epoch)
            info.compress_type = zipfile.ZIP_DEFLATED
            mode = 0o755 if p.name == "run_unix.sh" else 0o644
            info.external_attr = (mode & 0xFFFF) << 16
            zf.writestr(info, p.read_bytes())


def validate_release_tree(staging: Path, mode: str) -> dict:
    license_report = validate(staging, mode)
    portability_report = audit_portability(staging, mode)
    manifest_errors = verify_manifest(staging)
    errors = []
    errors.extend(license_report.get("errors", []))
    errors.extend(portability_report.get("errors", []))
    errors.extend(manifest_errors)
    return {
        "status": "passed" if not errors else "failed",
        "license_validation": license_report,
        "portability_validation": portability_report,
        "manifest_errors": manifest_errors,
        "errors": errors,
    }


def build(source: Path, mode: str, out_dir: Path) -> tuple[Path, dict]:
    source = source.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    policy = load_allowlist(source)
    suffix = "Code_Only" if mode == "code-only" else "With_Official_Data_CC_BY_4.0"
    archive_name = f"Adolescents_Digital_Nightlife_Analysis_{suffix}.zip"
    archive = out_dir / archive_name

    with tempfile.TemporaryDirectory(prefix="adn_dist_") as tmp:
        staging = Path(tmp) / f"Adolescents_Digital_Nightlife_Analysis_{suffix}"
        staging.mkdir()
        copied = copy_allowlisted_tree(source, staging, mode, policy)
        pattern_errors = required_patterns_satisfied(staging, mode, policy)
        if pattern_errors:
            raise RuntimeError("allowlist source validation failed: " + "; ".join(pattern_errors))

        contents = build_contents(staging, mode, source, copied)
        (staging / "DISTRIBUTION_CONTENTS.json").write_text(
            json.dumps(contents, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        write_manifest(staging)
        validation = validate_release_tree(staging, mode)
        if validation["status"] != "passed":
            raise RuntimeError("release validation failed: " + "; ".join(validation["errors"]))

        deterministic_zip(staging, archive, staging.name)
        extract_root = Path(tmp) / "extract"
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(extract_root)
        extracted = extract_root / staging.name
        post_validation = validate_release_tree(extracted, mode)
        if post_validation["status"] != "passed":
            raise RuntimeError("post-extraction release validation failed: " + "; ".join(post_validation["errors"]))

        build_report = {
            "status": "passed",
            "mode": mode,
            "archive": archive.name,
            "archive_sha256": sha256(archive),
            "archive_size_bytes": archive.stat().st_size,
            "file_count": sum(1 for p in staging.rglob("*") if p.is_file()),
            "virtual_environment_included": False,
            "generated_results_included": False,
            "processed_participant_data_included": False,
            "platform_specific_binaries_included": False,
            "allowlist_source_file_count": len(copied),
            "validation": validation,
            "post_extraction_validation": post_validation,
        }

    archive.with_suffix(archive.suffix + ".sha256").write_text(
        f"{sha256(archive)}  {archive.name}\n", encoding="utf-8"
    )
    archive.with_suffix(archive.suffix + ".build.json").write_text(
        json.dumps(build_report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return archive, build_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build clean, explicit-allowlist reproducibility archives.")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--mode", choices=["code-only", "data-inclusive"], required=True)
    parser.add_argument("--output-dir", default="dist")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    out = Path(args.output_dir)
    if not out.is_absolute():
        out = root / out
    archive, report = build(root, args.mode, out)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"Built: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
