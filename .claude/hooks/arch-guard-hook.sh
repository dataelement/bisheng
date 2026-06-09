#!/bin/bash
# PostToolUse hook wrapper for arch-guard.
# Reads the hook JSON from stdin, extracts the edited file path, runs the
# architecture guard, and — if there are violations — surfaces them back to
# the agent via PostToolUse `additionalContext` so it can self-correct.
#
# Why a wrapper (not inline in settings.json):
#   - PostToolUse passes data as JSON on stdin (NOT $CLAUDE_FILE — that var
#     does not exist). We must parse .tool_input.file_path with jq.
#   - Plain stdout is NOT fed back to the agent; only JSON additionalContext is.
#
# Exit 0 always: arch-guard is advisory, it must never block edits.

FILE=$(jq -r '.tool_input.file_path // empty')
[ -z "$FILE" ] && exit 0

OUT=$(bash "$CLAUDE_PROJECT_DIR/scripts/arch-guard.sh" "$FILE" 2>&1)
[ -z "$OUT" ] && exit 0

jq -n --arg ctx "$OUT" \
  '{hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: $ctx}}'
exit 0
