#!/bin/bash
# Blocks Claude from editing secrets, git internals, lock files and the prompt log.
# Exit 2 = block; stderr is fed back to Claude as the reason.

source "$(dirname "$0")/json-get.sh"

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | json_get '.tool_input.file_path') || {
  echo "Blocked: could not parse the hook input, refusing to guess the target file" >&2
  exit 2
}

# Normalize Windows backslashes so the patterns below match
FILE_PATH="${FILE_PATH//\\//}"

PROTECTED_PATTERNS=(".env" ".git/" "uv.lock" "poetry.lock" "prompt-log.md")

for pattern in "${PROTECTED_PATTERNS[@]}"; do
  # .env.example is allowed
  if [[ "$FILE_PATH" == *".env.example" ]]; then
    continue
  fi
  if [[ "$FILE_PATH" == *"$pattern"* ]]; then
    echo "Blocked: $FILE_PATH matches protected pattern '$pattern'" >&2
    exit 2
  fi
done

exit 0
