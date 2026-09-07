#!/bin/bash

# 根据目标类型库下所有有效主文件给原始上传人批量增加指定积分
#
# 使用方法 (在 src/backend 目录下执行):
#   bash scripts/backfill_space_file_points.sh --space-level public --score-per-file 3 --dry-run
#   bash scripts/backfill_space_file_points.sh --space-level department --score-per-file 2
#   bash scripts/backfill_space_file_points.sh --space-level team_ks --score-per-file 1 --ignore-accounts "admin,system"

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

"${PYTHON_BIN}" scripts/backfill_space_file_points.py "$@"
