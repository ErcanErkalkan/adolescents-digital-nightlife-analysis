from __future__ import annotations

import argparse
import fnmatch
import json
import re
from pathlib import Path

TEXT_SUFFIXES = {
    ".bat", ".cff", ".csv", ".gitignore", ".gitattributes", ".json", ".md",
    ".py", ".rst", ".sh", ".toml", ".txt", ".yml", ".yaml",
}
LOCAL_PATH_SCAN_EXEMPT = {"src/audit_portability.py", "PORTABILITY_AND_PACKAGING.md"}
LOCAL_PATH_PATTERNS = {
    "windows_user_path": re.compile(r"(?i)[A-Z]:\\Users\\[^\\\s]+\\"),
    "sandbox_path": re.compile(r"/mnt/data/"),
    "oai_home_path": re.compile(r"/home/oai/"),
    "mac_user_path": re.compile(r"/Users/[^/\s]+/"),
}


def load_policy(root: Path) -> dict:
    path = root / "DISTRIBUTION_ALLOWLIST.json"
    if not path.exists():
        raise FileNotFoundError(f"distribution policy missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def is_text_candidate(path: Path) -> bool:
    return path.name in {".gitignore", ".gitattributes"} or path.suffix.lower() in TEXT_SUFFIXES


def generated_data_violation(rel: Path, mode: str) -> bool:
    if mode not in {"code-only", "data-inclusive"}:
        return False
    if rel.parts and rel.parts[0] == "data_processed" and rel.name != ".gitkeep":
        return True
    if rel.parts and rel.parts[0] == "outputs" and rel.name != ".gitkeep":
        return True
    if mode == "code-only" and rel.parts and rel.parts[0] == "data_raw" and rel.name != ".gitkeep":
        return True
    if mode == "data-inclusive" and rel.parts and rel.parts[0] == "data_raw":
        allowed = {".gitkeep", "download_manifest.json", "phone.csv", "game.csv", "social.csv", "video.csv", "timeframes.csv"}
        return rel.name not in allowed
    return False


def audit(root: Path, mode: str = "workspace", *, scan_local_paths: bool = True) -> dict:
    root = root.resolve()
    policy = load_policy(root)
    forbidden_dirs = set(policy["forbidden_directory_names"])
    forbidden_suffixes = {s.lower() for s in policy["forbidden_suffixes"]}
    max_size = int(policy["maximum_file_size_bytes"])

    errors: list[str] = []
    warnings: list[str] = []
    file_rows: list[dict] = []
    local_path_hits: list[dict] = []

    if not root.exists():
        return {"status": "failed", "mode": mode, "errors": [f"root does not exist: {root}"], "warnings": []}

    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        rel_text = rel.as_posix()
        if path.is_symlink():
            errors.append(f"symlink is not allowed in a release tree: {rel_text}")
            continue
        if any(part in forbidden_dirs for part in rel.parts):
            message = f"forbidden directory artifact: {rel_text}"
            if mode == "workspace":
                warnings.append(message)
            else:
                errors.append(message)
            continue
        if not path.is_file():
            continue

        size = path.stat().st_size
        suffix = path.suffix.lower()
        row = {"path": rel_text, "size_bytes": size, "suffix": suffix}
        file_rows.append(row)

        if suffix in forbidden_suffixes:
            errors.append(f"forbidden binary/compiled suffix: {rel_text}")
        if path.name in {".DS_Store", "Thumbs.db", "desktop.ini"}:
            errors.append(f"operating-system artifact: {rel_text}")
        if size > max_size:
            errors.append(f"file exceeds release size limit ({max_size} bytes): {rel_text} ({size} bytes)")
        if generated_data_violation(rel, mode):
            errors.append(f"generated or disallowed data artifact in {mode} distribution: {rel_text}")

        if scan_local_paths and rel_text not in LOCAL_PATH_SCAN_EXEMPT and is_text_candidate(path) and size <= 2_000_000:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                text = ""
            for label, pattern in LOCAL_PATH_PATTERNS.items():
                if pattern.search(text):
                    hit = {"path": rel_text, "pattern": label}
                    local_path_hits.append(hit)
                    errors.append(f"absolute local path leaked into release text ({label}): {rel_text}")

    report = {
        "schema_version": 1,
        "status": "passed" if not errors else "failed",
        "mode": mode,
        "root": str(root),
        "file_count": len(file_rows),
        "total_size_bytes": sum(r["size_bytes"] for r in file_rows),
        "maximum_file_size_bytes": max_size,
        "local_path_hits": local_path_hits,
        "errors": errors,
        "warnings": warnings,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a workspace or distribution tree for portability and release cleanliness.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--mode", choices=["workspace", "code-only", "data-inclusive"], default="workspace")
    parser.add_argument("--report")
    parser.add_argument("--skip-local-path-scan", action="store_true")
    args = parser.parse_args()
    report = audit(Path(args.root), args.mode, scan_local_paths=not args.skip_local_path_scan)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    print(text)
    if args.report:
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
