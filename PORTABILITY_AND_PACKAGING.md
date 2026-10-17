# Portability and Packaging Policy

## Release principle

Virtual environments, compiled bytecode, package caches, IDE metadata, operating-system files, temporary logs, generated test artifacts, and platform-specific binaries are never distributed.

Two clean archive types are supported:

1. **Code-only reproducibility archive** — source code, tests, documentation, environment specifications, and empty data/output directories.
2. **Official-data-inclusive archive** — the code-only contents plus exactly the five verified official CSV files and their download manifest. It does not contain processed participant-level data, generated results, fitted models, runtime logs, or stale report artifacts.

The ordinary workspace may contain generated files while an analysis is running. Release archives are never created by zipping the workspace directly. `src/build_distribution.py` copies files only when they match `DISTRIBUTION_ALLOWLIST.json`, then runs license, portability, and manifest checks before and after archive extraction.

## Supported execution model

The repository does not ship a prebuilt `.venv`. Create a local environment on the target computer:

```bash
python bootstrap_environment.py
```

Then run the complete workflow:

```bash
python run_all.py --offline
```

The package is designed for CPython 3.11–3.13. The CI workflow is configured to test Linux, Windows, and macOS with supported Python versions. A successful CI configuration is not a substitute for documenting the exact environment used for a publication run.

## Release audit

Before publishing an archive:

```bash
python src/audit_portability.py --root . --mode workspace
python src/build_distribution.py --mode code-only
python src/build_distribution.py --mode data-inclusive
```

The builder rejects:

- virtual environments and caches;
- Python bytecode;
- executables and native shared libraries;
- files outside the explicit allowlist;
- generated participant-level data and results in release archives;
- files larger than the configured limit;
- symlinks;
- absolute local paths such as `/mnt/data/...`, `/home/oai/...`, or `C:\Users\...` embedded in released text files.

## Dependency inventory

`DEPENDENCY_INVENTORY.json` lists direct Python dependencies and pinned versions used by the reference environment. Dependencies are installed on the target machine and are not redistributed as binaries. The top-level pins are not represented as a cryptographically complete transitive lock; that separate limitation remains documented until a platform-specific lock solution is adopted.
