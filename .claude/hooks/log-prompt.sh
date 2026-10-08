#!/bin/bash
# Appends every prompt you send to docs/prompt-log.md.
# Purpose: evidence of how you work with AI (30% of the grade, and part of the follow-up interview).
# Needs jq or python3. Never paste API keys into prompts: this file is meant to be committed.

source "$(dirname "$0")/json-get.sh"

INPUT=$(cat)
PROMPT=$(echo "$INPUT" | json_get '.prompt')
[ -z "$PROMPT" ] && exit 0
# Background-task completions arrive through this hook too; they are not prompts.
case "$PROMPT" in "<task-notification>"*) exit 0 ;; esac

LOG="$CLAUDE_PROJECT_DIR/docs/prompt-log.md"
mkdir -p "$(dirname "$LOG")"
{
  echo "### $(date '+%Y-%m-%d %H:%M')"
  echo
  printf '%s\n' "$PROMPT"
  echo
} >> "$LOG"

exit 0
