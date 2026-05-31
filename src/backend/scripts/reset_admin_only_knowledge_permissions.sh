#!/bin/bash

# 重置用户管理授权和知识空间资源权限，只保留 admin 为 owner。
# 默认 dry-run；传入 --apply 才会写入。

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

"${PYTHON_BIN}" scripts/reset_admin_only_knowledge_permissions.py "$@"
