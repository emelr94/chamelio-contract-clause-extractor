#!/bin/bash
# Runs ruff on every Python file Claude edits. Silent on success; never blocks.

source "$(dirname "$0")/json-get.sh"

INPUT=$(cat)
FILE=$(echo "$INPUT" | json_get '.tool_input.file_path')

case "$FILE" in
  *.py)
    RUFF="$CLAUDE_PROJECT_DIR/.venv/bin/ruff"  # ruff lives in the project venv, not on PATH
    [ -x "$RUFF" ] || RUFF=ruff
    "$RUFF" check --fix --quiet "$FILE" >/dev/null 2>&1
    "$RUFF" format --quiet "$FILE" >/dev/null 2>&1
    ;;
esac

exit 0
