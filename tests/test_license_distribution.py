from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile

import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from build_distribution import build
from validate_license_scope import validate


def test_workspace_license_scope_is_explicit():
    report = validate(ROOT, "workspace")
    assert report["status"] == "passed", report["errors"]


def test_code_only_distribution_excludes_data_and_outputs(tmp_path: Path):
    archive, report = build(ROOT, "code-only", tmp_path)
    assert report["status"] == "passed"
    unpack = tmp_path / "unpack"
    shutil.unpack_archive(str(archive), str(unpack))
    package = next(unpack.iterdir())
    assert not list((package / "data_raw").glob("*.csv"))
    assert not list((package / "data_processed").glob("*.csv"))
    assert not (package / "outputs").exists()
    assert validate(package, "code-only")["status"] == "passed"


def test_data_inclusive_distribution_requires_hash_matching_sources(tmp_path: Path):
    if not (ROOT / "data_raw" / "download_manifest.json").exists():
        pytest.skip("Official raw dataset is deliberately absent from code-only source release")
    archive, report = build(ROOT, "data-inclusive", tmp_path)
    assert report["status"] == "passed"
    unpack = tmp_path / "unpack_data"
    shutil.unpack_archive(str(archive), str(unpack))
    package = next(unpack.iterdir())
    assert {p.name for p in (package / "data_raw").glob("*.csv")} == {
        "phone.csv", "game.csv", "social.csv", "video.csv", "timeframes.csv"
    }
    metadata = json.loads((package / "DISTRIBUTION_CONTENTS.json").read_text(encoding="utf-8"))
    assert metadata["dataset_license"] == "CC BY 4.0"
    assert len(metadata["source_files"]) == 5
    assert validate(package, "data-inclusive")["status"] == "passed"


def test_tampered_official_source_is_rejected(tmp_path: Path):
    if not (ROOT / "data_raw" / "download_manifest.json").exists():
        pytest.skip("Official raw dataset is deliberately absent from code-only source release")
    clone = tmp_path / "clone"
    shutil.copytree(ROOT, clone, ignore=shutil.ignore_patterns(".venv", ".pytest_cache", "__pycache__", "dist"))
    with (clone / "data_raw" / "phone.csv").open("ab") as f:
        f.write(b"\nTAMPER")
    report = validate(clone, "workspace")
    # Workspace validation checks scope, while data-inclusive build must reject hash mismatch.
    try:
        build(clone, "data-inclusive", tmp_path / "dist")
    except RuntimeError as exc:
        assert "hash mismatch" in str(exc)
    else:
        raise AssertionError("tampered source data were accepted")


def test_contradictory_no_data_claim_is_rejected_when_data_present(tmp_path: Path):
    if not list((ROOT / "data_raw").glob("*.csv")):
        pytest.skip("Only applies to data-inclusive bundles; raw data intentionally absent")
    clone = tmp_path / "clone_claim"
    shutil.copytree(ROOT, clone, ignore=shutil.ignore_patterns(".venv", ".pytest_cache", "__pycache__", "dist"))
    (clone / "BAD_NOTICE.md").write_text("Bu yazılım paketi veri dosyalarını yeniden dağıtmaz.", encoding="utf-8")
    report = validate(clone, "workspace")
    assert report["status"] == "failed"
    assert any("contradictory" in e for e in report["errors"])
