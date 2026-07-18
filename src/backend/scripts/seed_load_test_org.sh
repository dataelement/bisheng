#!/bin/bash
# 压测数据脚本包装器：批量生成部门树 + 用户。详见 scripts/seed_load_test_org.py 模块文档。
# 必须在 src/backend 目录下运行，且 config 需与线上服务一致。
#
#   cd src/backend
#   config=config.yaml bash scripts/seed_load_test_org.sh --departments 200 --users 50000 --apply
#
set -e

export config="${config:-config.yaml}"
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

"${PYTHON_BIN}" scripts/seed_load_test_org.py "$@"
