from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run(script: str, *arguments: str) -> None:
    command = [sys.executable, str(ROOT / script), *arguments]
    print("\n===", " ".join(command[1:]), "===", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the complete reproducible secondary-analysis workflow.")
    parser.add_argument("--offline", action="store_true", help="Use files already present in data_raw/.")
    parser.add_argument("--allow-partial", action="store_true", help="Development only: tolerate missing optional source files.")
    parser.add_argument("--quick", action="store_true", help="Code validation only; reduced repetitions.")
    parser.add_argument("--skip-download", action="store_true", help="Alias for offline execution.")
    args = parser.parse_args()

    download_args = []
    if args.offline or args.skip_download:
        download_args.append("--offline")
    if args.allow_partial:
        download_args.append("--allow-partial")
    run("src/download_data.py", *download_args)

    # Mandatory raw-data gate: substantive preparation/modeling must never run
    # until exact files, mappings, units, and day alignment pass audit.
    run("src/audit_raw_data.py")

    prepare_args = ["--allow-partial"] if args.allow_partial else []
    run("src/inspect_and_prepare.py", *prepare_args)
    run("src/run_analysis.py", *(["--quick"] if args.quick else []))
    validation_args = []
    if args.allow_partial:
        validation_args.append("--allow-partial")
    if args.quick:
        validation_args.append("--allow-quick")
    run("src/validate_outputs.py", *validation_args)
    run("src/generate_report.py", *(["--allow-quick"] if args.quick else []))
    print("\nWorkflow completed and passed validation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
