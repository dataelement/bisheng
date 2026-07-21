#!/bin/bash
# Backfill LibreOffice-rendered PDF previews for existing Word files.
# Run from src/backend/. Dry-run by default; pass --apply to convert and write.
#   bash scripts/backfill_word_pdf_preview.sh            # dry-run
#   bash scripts/backfill_word_pdf_preview.sh --apply --limit 50
set -e
export PYTHONPATH="./"

if [ -x ".venv/bin/python" ]; then
    PYTHON_BIN=".venv/bin/python"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
else
    echo "Python interpreter not found." >&2
    exit 1
fi

"${PYTHON_BIN}" scripts/backfill_word_pdf_preview.py "$@"
