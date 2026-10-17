#!/usr/bin/env sh
set -eu
PYTHON_BIN="${PYTHON_BIN:-python3}"
exec "$PYTHON_BIN" run_all.py "$@"
