#!/bin/bash
# Cursor afterFileEdit hook: auto-format Python files with ruff.
# Mirrors .claude/settings.json PostToolUse ruff hook (async side effect).

INPUT=$(cat)

FILE=$(echo "$INPUT" | jq -r '
  .file_path //
  .tool_input.file_path //
  .tool_input.path //
  .tool_input.filePath //
  empty
')
[ -z "$FILE" ] && exit 0
echo "$FILE" | grep -q '\.py$' || exit 0

PROJECT_DIR="${CURSOR_PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}}"
BACKEND_DIR="$PROJECT_DIR/src/backend"

if [ -f "$BACKEND_DIR/.venv/bin/ruff" ]; then
  "$BACKEND_DIR/.venv/bin/ruff" format "$FILE" 2>/dev/null
  "$BACKEND_DIR/.venv/bin/ruff" check --fix "$FILE" 2>/dev/null
fi

exit 0
