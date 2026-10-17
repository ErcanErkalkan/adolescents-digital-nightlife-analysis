# Isolated smoke test

The smoke test creates artificial data inside a temporary directory and validates the entire pipeline without touching `data_raw/` or any real results.

```bash
python tests/run_smoke_test.py
```

Synthetic outputs are deleted automatically and must never be reported as research findings.
