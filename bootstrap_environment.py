from __future__ import annotations

import argparse
import subprocess
import sys
import venv
from pathlib import Path

SUPPORTED = (3, 11), (3, 12), (3, 13)


def venv_python(folder: Path) -> Path:
    if sys.platform == "win32":
        return folder / "Scripts" / "python.exe"
    return folder / "bin" / "python"


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a local portable virtual environment and install project dependencies.")
    parser.add_argument("--venv", default=".venv", help="Environment directory created locally; never included in release archives.")
    parser.add_argument("--requirements", default="requirements-lock.txt")
    parser.add_argument("--no-upgrade-pip", action="store_true")
    args = parser.parse_args()

    version = sys.version_info[:2]
    if version not in SUPPORTED:
        supported = ", ".join(f"{a}.{b}" for a, b in SUPPORTED)
        raise SystemExit(f"Unsupported Python {version[0]}.{version[1]}; use one of: {supported}")

    root = Path(__file__).resolve().parent
    env_dir = (root / args.venv).resolve()
    req = (root / args.requirements).resolve()
    if not req.exists():
        raise SystemExit(f"Requirements file not found: {req}")

    venv.EnvBuilder(with_pip=True, clear=False).create(env_dir)
    py = venv_python(env_dir)
    if not args.no_upgrade_pip:
        subprocess.run([str(py), "-m", "pip", "install", "--upgrade", "pip"], check=True)
    subprocess.run([str(py), "-m", "pip", "install", "-r", str(req)], check=True)
    subprocess.run([str(py), "-m", "pip", "check"], check=True)
    print(f"Environment ready: {env_dir}")
    print(f"Run analysis with: {py} run_all.py --offline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
