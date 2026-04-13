# Dev Checks

This directory stores one-off and integration validation scripts that should not be part of the formal `tests/` suite.

## Purpose

- Keep formal tests focused and stable.
- Isolate heavy, environment-dependent, or manual verification scripts.
- Avoid polluting `tests/` with temporary validation utilities.

## Output policy

Generated artifacts must go to `scripts/dev_checks/_outputs/`.
This directory is ignored by git.

## Typical usage

- `python scripts/dev_checks/check_source_to_report_chain.py`
- `python scripts/dev_checks/check_harvest_dataflow.py`
- `python scripts/dev_checks/check_figure_injection_to_pdf.py`
- `python scripts/dev_checks/test_process_blocking.py`
