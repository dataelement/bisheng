#!/bin/bash

# Delete one Expert QA question and dependent rows.
#
# Usage:
#   bash scripts/delete_qa_expert_question.sh <question_id>
#   bash scripts/delete_qa_expert_question.sh <question_id> --apply

set -e

if [ -z "$1" ]; then
    echo "Usage: $0 <question_id> [--apply]" >&2
    exit 1
fi

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

"${PYTHON_BIN}" scripts/delete_qa_expert_question.py "$@"
