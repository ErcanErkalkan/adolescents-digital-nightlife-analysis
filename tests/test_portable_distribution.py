from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
import sys
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from audit_portability import audit
from build_distribution import build


def extract(archive: Path, destination: Path) -> Path:
    shutil.unpack_archive(str(archive), str(destination))
    entries = [p for p in destination.iterdir() if p.is_dir()]
    assert len(entries) == 1
    return entries[0]


def test_workspace_has_no_shipped_environment_or_cache_artifacts():
    report = audit(ROOT, "workspace")
    assert report["status"] == "passed", report["errors"]


def test_code_only_archive_is_allowlisted_and_contains_no_data_or_results(tmp_path: Path):
    archive, report = build(ROOT, "code-only", tmp_path)
    assert report["status"] == "passed"
    package = extract(archive, tmp_path / "unpack_code")
    assert not list((package / "data_raw").glob("*.csv"))
    assert not list((package / "data_processed").glob("*.csv"))
    assert not (package / "outputs" / "ANALYSIS_REPORT.md").exists()
    assert audit(package, "code-only")["status"] == "passed"
    metadata = json.loads((package / "DISTRIBUTION_CONTENTS.json").read_text(encoding="utf-8"))
    assert metadata["virtual_environment_included"] is False
    assert metadata["generated_results_included"] is False
    assert metadata["processed_participant_data_included"] is False


def test_data_inclusive_archive_contains_only_official_raw_data(tmp_path: Path):
    if not list((ROOT / "data_raw").glob("*.csv")):
        pytest.skip("Official dataset CSV files are intentionally excluded from code-only distribution")
    archive, report = build(ROOT, "data-inclusive", tmp_path)
    assert report["status"] == "passed"
    package = extract(archive, tmp_path / "unpack_data")
    assert {p.name for p in (package / "data_raw").glob("*.csv")} == {
        "phone.csv", "game.csv", "social.csv", "video.csv", "timeframes.csv"
    }
    assert not list((package / "data_processed").glob("*.csv"))
    assert not any(p.is_file() and p.name != ".gitkeep" for p in (package / "outputs").rglob("*"))
    assert audit(package, "data-inclusive")["status"] == "passed"


def test_unlisted_file_is_not_copied(tmp_path: Path):
    clone = tmp_path / "clone"
    shutil.copytree(ROOT, clone, ignore=shutil.ignore_patterns(".git", ".venv", "dist"))
    (clone / "SECRET_LOCAL_NOTE.txt").write_text("not for release", encoding="utf-8")
    archive, _ = build(clone, "code-only", tmp_path / "dist")
    package = extract(archive, tmp_path / "unpack")
    assert not (package / "SECRET_LOCAL_NOTE.txt").exists()


@pytest.mark.parametrize("relative", [".venv/bin/python", "src/bad.pyc", "native/tool.exe", "native/lib.so"])
def test_forbidden_environment_or_binary_is_rejected(relative: str, tmp_path: Path):
    root = tmp_path / "package"
    shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(".git", "dist"))
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"artifact")
    report = audit(root, "code-only", scan_local_paths=False)
    assert report["status"] == "failed"
    assert report["errors"]


def test_large_file_is_rejected(tmp_path: Path):
    root = tmp_path / "package"
    shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns(".git", "dist"))
    big = root / "oversized.bin"
    big.write_bytes(b"0" * (26 * 1024 * 1024))
    report = audit(root, "code-only", scan_local_paths=False)
    assert report["status"] == "failed"
    assert any("size limit" in error for error in report["errors"])
