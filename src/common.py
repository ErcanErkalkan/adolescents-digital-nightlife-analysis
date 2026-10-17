from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data_raw"
PROCESSED = ROOT / "data_processed"
OUTPUTS = ROOT / "outputs"
TABLES = OUTPUTS / "tables"
FIGURES = OUTPUTS / "figures"
MODELS = OUTPUTS / "models"
LOGS = OUTPUTS / "logs"
CONFIG_PATH = ROOT / "analysis_config.json"


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def ensure_directories() -> None:
    for path in (RAW, PROCESSED, TABLES, FIGURES, MODELS, LOGS):
        path.mkdir(parents=True, exist_ok=True)


def setup_logging(name: str, filename: str | None = None) -> logging.Logger:
    ensure_directories()
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(stream)
    if filename:
        file_handler = logging.FileHandler(LOGS / filename, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    return logger


def normalize_name(value: object) -> str:
    text = str(value).strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_stem(path: Path) -> str:
    # Handles files such as phone.csv, phone.dat, phone.csv.gz and extensionless timeframes.
    stem = path.name
    for suffix in (".gz", ".zip", ".csv", ".tsv", ".txt", ".dat", ".xlsx", ".xls"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
    return normalize_name(stem)


def detect_dataset_files(config: dict[str, Any], search_root: Path = RAW) -> dict[str, Path]:
    aliases = {
        key: {normalize_name(v) for v in values}
        for key, values in config.get("file_aliases", {}).items()
    }
    found: dict[str, list[Path]] = {key: [] for key in config["expected_file_stems"]}
    for path in sorted(search_root.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        stem = canonical_stem(path)
        for canonical in found:
            accepted = aliases.get(canonical, {normalize_name(canonical)})
            if stem in accepted:
                found[canonical].append(path)
    resolved: dict[str, Path] = {}
    for canonical, matches in found.items():
        if len(matches) > 1:
            display = ", ".join(str(p.relative_to(search_root)) for p in matches)
            raise RuntimeError(f"Ambiguous files for '{canonical}': {display}")
        if matches:
            resolved[canonical] = matches[0]
    return resolved


def missing_dataset_stems(config: dict[str, Any], files: dict[str, Path]) -> list[str]:
    return [stem for stem in config["expected_file_stems"] if stem not in files]


def json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(temp, path)


def clean_output_files(paths: Iterable[Path]) -> None:
    for directory in paths:
        if not directory.exists():
            continue
        for path in directory.iterdir():
            if path.is_file() and path.name != ".gitkeep":
                path.unlink()
