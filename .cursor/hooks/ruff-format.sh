#!/bin/bash
# Auto-format Python files after edit (mirrors .claude PostToolUse ruff hook)
set -euo pipefail

input=$(cat)
FILE=$(echo "$input" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('file_path','') or d.get('path','') or '')" 2>/dev/null || true)

[ -z "$FILE" ] && exit 0
[ ! -f "$FILE" ] && exit 0
echo "$FILE" | grep -q '\.py$' || exit 0

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BACKEND="$ROOT/src/backend"

cd "$BACKEND"

if [ -f .venv/bin/ruff ]; then
  .venv/bin/ruff format "$FILE" 2>/dev/null || true
  .venv/bin/ruff check --fix "$FILE" 2>/dev/null || true
elif command -v uv >/dev/null 2>&1; then
  uv run ruff format "$FILE" 2>/dev/null || true
  uv run ruff check --fix "$FILE" 2>/dev/null || true
fi

exit 0
