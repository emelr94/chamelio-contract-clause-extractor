# Code review: second pass (pre-submission)

Done by the `code-reviewer` subagent (read-only) over the whole working tree, focused on what had changed since the first pass. It reproduced its findings with scratch scripts, then each one was fixed with a regression test or documented. Result: **73 tests pass, ruff clean.**

## Must fix (all fixed)

| # | Finding | Fix | Test |
|---|---|---|---|
| 1 | **A clause was dropped without a warning.** Unnumbered clauses compared only type + title, so "Exhibit A" and "Exhibit B" (no title) had the same identity. An unlocated Exhibit B was then treated as already located by the overlapping chunk. | Identity of unnumbered clauses includes the normalized label (`Exhibit B`, `ARTICLE VI`). | `test_unlocated_exhibit_is_not_mistaken_for_another_exhibit` |
| 2 | **Text was relabelled.** Cross-chunk dedup took the *first* clause within 50 chars and ignored identity. With `12. [Reserved].` / `13. [Reserved].` seen by both chunks, clause 12's text was stored as 13, there were two "14"s, and a false `NUMBERING_GAP` appeared. | Merge only at the same offset, or within 50 chars with the same identity, and take the nearest match. | `test_short_neighbouring_clauses_from_two_chunks_keep_their_own_text` |
| 3 | README linked this file before it existed. | This file. | n/a |
| 4 | Stale docs: DECISIONS still described the preamble exemption and the old dedup rule. | Append-only correction entry in `docs/DECISIONS.md`. | n/a |
| 5 | `docs/prompt-log.md` has a `test` entry. | Left as is: it is a real prompt submission and the log is never edited by hand. | n/a |

## Should fix (fixed)

| # | Finding | Fix |
|---|---|---|
| 6 | The subsection fold discarded the child's metadata, and could fold across an unlocated heading ("5. Term" → unfound "SCHEDULE B" → "5.1 Fees" ended up inside clause 5 with no flag). | No fold when an unlocated clause sits in between; the parent keeps the lower confidence. Tests: `test_subsection_after_an_unlocated_heading_is_not_folded`, `test_folded_low_confidence_subsection_keeps_the_parent_in_review`. |
| 7 | The clause before a `CHUNK_FAILED` range absorbed that text without a flag. | Flagged `MAY_CONTAIN_MISSING_CLAUSE` + `needs_review`. Test: `test_clause_running_over_a_failed_range_is_flagged`. |
| 9 | `stop_reason="model_context_window_exceeded"` fell through to validation, a pointless repair call and a misleading error. | Treated like `max_tokens` (fails the chunk at once). Test: parametrized `test_truncated_output_fails_immediately`. |
| 10 | Hooks: `protect-files.sh` allowed the edit on unparseable input; `log-prompt.sh` logged a prompt of `-n` as blank. | Fail closed on invalid JSON; `printf '%s\n'`. Also found while checking: background-task notifications were logged as prompts, now skipped. |
| 11 | `jq` is now installed, so "jq is not installed" reads as false. | Wording changed to "was not installed when this project started". |

## Documented, not changed

- **8. A timed-out chunk reports 0 tokens.** The cancelled attempt's usage is unknown. Noted in code and in README known limits.
- Bash writes bypass the `Edit|Write` matcher of `protect-files.sh` (a Claude Code hook-matcher limitation, not a bug in the script).

## Confirmed fine

The SDK 1.12 signatures match our usage (`beta.messages.create` with `output_config.format` + `effort`, `fallbacks="default"`, the beta header literal, `anthropic.transform_schema`). `.env.example` matches `app/config.py`. README counts, enums and status codes match the code. No secrets outside `.env`; no debug prints or TODOs in `app/`.
