.PHONY: install bootstrap test smoke run offline validate clean license-check portability-check dist-code dist-data dist-all

install:
	python -m pip install -r requirements.txt

bootstrap:
	python bootstrap_environment.py

test:
	python -m pytest -q

smoke:
	python tests/run_smoke_test.py

run:
	python run_all.py

offline:
	python run_all.py --offline

validate:
	python src/validate_outputs.py

clean:
	python -c "from pathlib import Path; import shutil; [shutil.rmtree(p, ignore_errors=True) for p in [Path('.pytest_cache'), Path('.mypy_cache'), Path('.ruff_cache')]]; [shutil.rmtree(p, ignore_errors=True) for p in Path('.').rglob('__pycache__')]; [p.unlink() for p in Path('.').rglob('*.pyc') if p.is_file()]; [p.unlink() for d in ['data_processed','outputs/tables','outputs/figures','outputs/models','outputs/logs'] for p in Path(d).glob('*') if p.is_file() and p.name != '.gitkeep']"

license-check:
	python src/validate_license_scope.py --root . --mode workspace

portability-check:
	python src/audit_portability.py --root . --mode workspace

dist-code:
	python src/build_distribution.py --mode code-only

dist-data:
	python src/build_distribution.py --mode data-inclusive

dist-all: dist-code dist-data
