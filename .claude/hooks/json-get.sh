#!/bin/bash
# Shared helper for the hooks: read one field from the hook's JSON input on stdin.
# Usage: VALUE=$(echo "$INPUT" | json_get '.tool_input.file_path')
# Uses jq when installed, otherwise python3. jq was not installed when this project started,
# so every hook silently saw an empty field and exited 0 (no prompt log, no file protection).
# Returns non-zero on invalid JSON (both jq and python3 do), so callers can fail closed.

json_get() {
  if command -v jq >/dev/null 2>&1; then
    jq -r "$1 // empty"
  else
    python3 -c '
import json, sys
value = json.load(sys.stdin)
for key in sys.argv[1].strip(".").split("."):
    value = value.get(key) if isinstance(value, dict) else None
print("" if value is None else value)
' "$1"
  fi
}
