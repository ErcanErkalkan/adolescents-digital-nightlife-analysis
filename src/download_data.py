from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from common import (
    RAW,
    detect_dataset_files,
    ensure_directories,
    file_md5,
    file_sha256,
    json_dump,
    load_config,
    missing_dataset_stems,
    setup_logging,
)

LOGGER = setup_logging("download", "download.log")


def build_session() -> requests.Session:
    retry = Retry(
        total=2,
        connect=1,
        read=2,
        backoff_factor=0.3,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({
        "User-Agent": "AdolescentsDigitalNightlife-ReproducibilityPipeline/3.0",
        "Accept": "application/json, application/zip, text/csv, */*",
    })
    token = os.getenv("FIGSHARE_TOKEN", "").strip()
    if token:
        session.headers.update({"Authorization": f"token {token}"})
    return session


def atomic_download(session: requests.Session, url: str, destination: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, dir=destination.parent, suffix=".part") as handle:
        temp = Path(handle.name)
    try:
        with session.get(url, stream=True, timeout=(10, 120), allow_redirects=True) as response:
            response.raise_for_status()
            content_type = (response.headers.get("content-type") or "").lower()
            total = 0
            with temp.open("wb") as out:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        out.write(chunk)
                        total += len(chunk)
            if total == 0:
                raise RuntimeError(f"Empty response from {url}")
            # Prevent saving a portal error page as a data file.
            if "text/html" in content_type:
                preview = temp.read_bytes()[:500].lower()
                if b"<html" in preview or b"<!doctype" in preview:
                    raise RuntimeError(f"Received HTML instead of data from {url}")
        os.replace(temp, destination)
        return {
            "url": url,
            "final_path": str(destination),
            "size_bytes": destination.stat().st_size,
            "sha256": file_sha256(destination),
            "content_type": content_type,
        }
    finally:
        if temp.exists():
            temp.unlink(missing_ok=True)


def safe_extract_zip(archive: Path, destination: Path) -> None:
    destination_resolved = destination.resolve()
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            target = (destination / member.filename).resolve()
            if destination_resolved not in target.parents and target != destination_resolved:
                raise RuntimeError(f"Unsafe ZIP member path: {member.filename}")
        zf.extractall(destination)


def metadata_endpoints(config: dict[str, Any]) -> list[str]:
    article = config["article_id"]
    version = config["figshare_version"]
    return [
        f"https://api.figshare.com/v2/articles/{article}/versions/{version}",
        f"https://api.figshare.com/v2/articles/{article}",
        f"https://api.figshare.com/v2/articles/{article}/versions/{version}/files",
        f"https://api.figshare.com/v2/articles/{article}/files",
    ]


def extract_file_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        records = payload.get("files", [])
    elif isinstance(payload, list):
        records = payload
    else:
        records = []
    return [record for record in records if isinstance(record, dict) and record.get("name")]


def download_from_metadata(session: requests.Session, config: dict[str, Any], force: bool) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    endpoint_used = None
    errors = []
    for endpoint in metadata_endpoints(config):
        try:
            response = session.get(endpoint, timeout=(8, 30))
            response.raise_for_status()
            candidate = extract_file_records(response.json())
            if candidate:
                records = candidate
                endpoint_used = endpoint
                break
        except Exception as exc:  # noqa: BLE001 - errors are logged and fallback is intentional.
            errors.append(f"{endpoint}: {exc}")
    if not records:
        LOGGER.warning("No file metadata retrieved. %s", " | ".join(errors))
        return []

    results = []
    for record in records:
        name = Path(str(record["name"])).name
        destination = RAW / name
        expected_md5 = record.get("computed_md5") or record.get("supplied_md5")
        if destination.exists() and not force:
            if expected_md5 and file_md5(destination).lower() != str(expected_md5).lower():
                LOGGER.warning("Existing %s failed MD5 and will be replaced.", name)
            else:
                LOGGER.info("Keeping existing file %s", name)
                results.append({"name": name, "status": "existing", "endpoint": endpoint_used})
                continue
        url = record.get("download_url")
        if not url and record.get("id"):
            url = f"https://ndownloader.figshare.com/files/{record['id']}"
        if not url:
            LOGGER.warning("No download URL for %s", name)
            continue
        try:
            LOGGER.info("Downloading %s", name)
            details = atomic_download(session, str(url), destination)
            if expected_md5 and file_md5(destination).lower() != str(expected_md5).lower():
                destination.unlink(missing_ok=True)
                raise RuntimeError(f"MD5 mismatch for {name}")
            details.update({"name": name, "status": "downloaded", "endpoint": endpoint_used})
            results.append(details)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Could not download %s: %s", name, exc)
    return results


def archive_endpoints(config: dict[str, Any]) -> list[str]:
    article = config["article_id"]
    version = config["figshare_version"]
    # Use documented public API endpoints only. Institutional portal DNS resolution can
    # block indefinitely on restricted networks; the manual-record fallback is safer.
    return [
        f"https://api.figshare.com/v2/articles/{article}/versions/{version}/download",
        f"https://api.figshare.com/v2/articles/{article}/download",
    ]


def download_archive_fallback(session: requests.Session, config: dict[str, Any]) -> list[dict[str, Any]]:
    results = []
    for index, url in enumerate(archive_endpoints(config), start=1):
        archive = RAW / f"figshare_article_{config['article_id']}_attempt{index}.zip"
        try:
            LOGGER.info("Trying archive endpoint %s", url)
            details = atomic_download(session, url, archive)
            if not zipfile.is_zipfile(archive):
                archive.unlink(missing_ok=True)
                raise RuntimeError("Response is not a ZIP archive")
            safe_extract_zip(archive, RAW)
            details.update({"name": archive.name, "status": "archive_extracted"})
            results.append(details)
            archive.unlink(missing_ok=True)
            break
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Archive endpoint failed: %s", exc)
            archive.unlink(missing_ok=True)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Download the official public Figshare files.")
    parser.add_argument("--force", action="store_true", help="Replace existing files.")
    parser.add_argument("--allow-partial", action="store_true", help="Return success with only phone data.")
    parser.add_argument("--offline", action="store_true", help="Do not access the network; verify local files only.")
    args = parser.parse_args()

    ensure_directories()
    config = load_config()
    before = detect_dataset_files(config)
    missing_before = missing_dataset_stems(config, before)
    events: list[dict[str, Any]] = [{"checked_at_epoch": time.time(), "missing_before": missing_before}]

    if missing_before and not args.offline:
        session = build_session()
        events.extend(download_from_metadata(session, config, args.force))
        after_metadata = detect_dataset_files(config)
        if missing_dataset_stems(config, after_metadata):
            events.extend(download_archive_fallback(session, config))

    files = detect_dataset_files(config)
    missing = missing_dataset_stems(config, files)
    manifest = {
        "article_id": config["article_id"],
        "version": config["figshare_version"],
        "dataset_doi": config["dataset_doi"],
        "files": {
            key: {
                "path": str(path.relative_to(RAW)),
                "size_bytes": path.stat().st_size,
                "sha256": file_sha256(path),
            }
            for key, path in files.items()
        },
        "missing": missing,
        "events": events,
    }
    json_dump(RAW / "download_manifest.json", manifest)

    if missing:
        LOGGER.error("Missing official files: %s", ", ".join(missing))
        LOGGER.error("Open %s and place the five files in %s", config["official_record_url"], RAW)
        if args.allow_partial and "phone" in files:
            LOGGER.warning("Continuing in partial mode; app-specific and timeframe analyses will be incomplete.")
            return 0
        return 2
    LOGGER.info("All five official dataset files are present and recorded in download_manifest.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
