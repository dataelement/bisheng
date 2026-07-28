#!/bin/bash
# Cursor postToolUse hook wrapper for arch-guard.
# Reads hook JSON from stdin, extracts the edited file path, runs
# scripts/arch-guard.sh, and surfaces violations via additional_context
# so the agent can self-correct.
#
# Exit 0 always: arch-guard is advisory, it must never block edits.

INPUT=$(cat)

FILE=$(echo "$INPUT" | jq -r '
  .file_path //
  .tool_input.file_path //
  .tool_input.path //
  .tool_input.filePath //
  empty
')
[ -z "$FILE" ] && exit 0

PROJECT_DIR="${CURSOR_PROJECT_DIR:-${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}}"

OUT=$(bash "$PROJECT_DIR/scripts/arch-guard.sh" "$FILE" 2>&1)
[ -z "$OUT" ] && exit 0

jq -n --arg ctx "$OUT" '{additional_context: $ctx}'
exit 0
