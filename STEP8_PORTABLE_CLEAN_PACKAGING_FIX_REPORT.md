# Step 8 — Portable Clean Packaging Fix Report

## Resolved blocker

The uploaded archive previously contained a Windows-specific virtual environment, Python caches, compiled bytecode, platform-specific binaries, raw data, processed participant-level data, generated results, and stale logs. This made the archive large, nonportable, and unsuitable as a clean reproducibility or submission artifact.

## Corrections implemented

1. Removed `.venv`, repository-local tool state, caches, bytecode, operating-system artifacts, generated outputs, processed data, and stale logs from the clean release workspace.
2. Added a root `.gitignore` and `.gitattributes`.
3. Replaced negative-filter packaging with `DISTRIBUTION_ALLOWLIST.json`, an explicit release allowlist.
4. Added `src/audit_portability.py`, which blocks:
   - virtual environments and caches;
   - `.pyc`, `.pyo`, `.exe`, `.dll`, `.pyd`, `.so`, `.dylib`, `.msi`, `.dmg`, and `.whl` artifacts;
   - symlinks;
   - files larger than 25 MiB;
   - generated/processed data and result artifacts in release archives;
   - leaked absolute local paths.
5. Updated `src/build_distribution.py` so releases are assembled only from allowlisted files and are validated before and after ZIP extraction.
6. Defined two release modes:
   - code-only: source, tests, documentation, environment definitions, and no participant data/results;
   - data-inclusive: code-only contents plus exactly five verified official CSV files and `download_manifest.json`; no processed data/results/models/logs.
7. Added `bootstrap_environment.py` so a local environment is created on the target computer rather than redistributed.
8. Added `run_unix.sh` and retained `run_windows.bat` as text launchers.
9. Added a Linux/Windows/macOS GitHub Actions matrix for Python 3.11–3.13.
10. Added `DEPENDENCY_INVENTORY.json` and documented that dependencies are installed, not redistributed as binaries.
11. Added portability and archive-cleanliness automated tests.

## Verification results

- Python compilation: passed.
- Automated tests: 70 passed.
- Workspace portability audit: passed with 0 errors and 0 warnings after cleanup.
- Code-only archive:
  - size: 96,123 bytes;
  - file count: 52;
  - official CSV files: 0;
  - generated results: 0;
  - processed participant data: 0;
  - virtual environment/binaries: 0;
  - pre- and post-extraction validation: passed.
- Official-data-inclusive archive:
  - size: 229,361 bytes;
  - file count: 58;
  - official CSV files: exactly 5;
  - generated results: 0;
  - processed participant data: 0;
  - virtual environment/binaries: 0;
  - source hashes, license checks, portability checks, and post-extraction checks: passed.
- Original uploaded archive for comparison: approximately 104 MB compressed and approximately 314 MB extracted in the prior audit.

## Scope boundary

This correction closes the package pollution and nonportability blocker. It does not claim that the top-level dependency pins are a complete hash-locked transitive environment; that remains a separate dependency-locking improvement.
