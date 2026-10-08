---
name: submit-check
description: Pre-submission checklist for the clause-extractor take-home. Verifies requirements, tests, Docker, README sections, diagram, demo script and that no secrets are committed.
disable-model-invocation: true
allowed-tools: Bash(pytest *) Bash(python -m pytest *) Bash(ruff *) Bash(docker build *) Bash(git ls-files *) Bash(git status *)
---

Run a read-only submission check. Do not fix anything; only report.

## Current state
!`git status --short`

## Checks
For each item answer PASS, FAIL or UNKNOWN with one line of evidence (file path, command output).

1. `POST /api/extract` accepts a PDF and returns clauses + metadata, and stores the result
2. `GET /api/extractions/{document_id}` and `GET /api/extractions` (paginated) exist
3. Pydantic models validate request and response; errors return proper status codes
4. Dockerfile exists and `docker build` succeeds (if Docker is unavailable, mark UNKNOWN)
5. `pytest -q` passes, LLM is mocked in tests
6. `ruff check .` is clean
7. Demo script exists (for example `scripts/demo.py`) and its usage is documented
8. README contains: setup instructions, design decisions and tradeoffs, what I'd improve with more time, assumptions
9. A diagram of the final solution exists and is referenced in the README
10. `docs/DECISIONS.md` and `docs/prompt-log.md` exist (AI usage evidence for the follow-up interview)
11. `.env` is not tracked (`git ls-files | grep -i '^\.env$'` must be empty); `.env.example` exists
12. Bonus status: DOCX support, tests, LLM usage

End with a prioritized list of what to fix before submitting, most important first.
