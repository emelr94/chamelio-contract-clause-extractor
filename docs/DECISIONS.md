# Decisions

## Packaging: uv + pyproject.toml, non-packaged app
- **Decision:** uv with `pyproject.toml` + `uv.lock`, `package = false`, Docker image based on `ghcr.io/astral-sh/uv`.
- **Alternatives considered:** pip + requirements.txt (no lockfile); Poetry (slower, heavier).
- **Why:** reproducible lockfile and a short, cache-friendly Dockerfile (`uv sync --frozen`) within the time budget.
- **Tradeoff / what I'd do with more time:** reviewers need uv installed for the non-Docker path; Docker is documented as the primary path.

## PDF parsing with PyMuPDF (AGPL flagged)
- **Decision:** PyMuPDF `page.get_text()` per page, behind one parsing function.
- **Alternatives considered:** pypdf (BSD, weaker text quality); pdfplumber (MIT, slower); unstructured (heavy).
- **Why:** best text quality and speed on the samples (CID fonts, symbol bullets), page-level text for page attribution.
- **Tradeoff / what I'd do with more time:** AGPL license is a problem for closed-source commercial use; swap to pypdf behind the same function or buy a license.

## SQLite + SQLAlchemy 2.0 with create_all (no migrations)
- **Decision:** SQLite file DB, tables created on startup via `Base.metadata.create_all`.
- **Alternatives considered:** Postgres (needs another container); Alembic migrations.
- **Why:** the task allows SQLite; zero setup for reviewers; schema is small and new.
- **Tradeoff / what I'd do with more time:** no migration history and limited write concurrency; move to Postgres + Alembic before production.

## Data model: normalized documents + clauses tables
- **Decision:** `documents` (file metadata, sha256, status, model, prompt_version, tokens, timing, warnings JSON) and `clauses` (FK, position, number, title, clause_type, verbatim text, pages, flags), indexed on `clause_type` and `document_id`.
- **Alternatives considered:** one `extractions` row with a JSON blob; a third table with raw LLM responses per chunk.
- **Why:** clauses are queryable (powers `?clause_type=`), model + prompt version make results reproducible, token columns make cost visible; raw-output table was out of time budget.
- **Tradeoff / what I'd do with more time:** `warnings`/`issues` are JSON columns, not tables; `clause_count` is denormalized for cheap list queries. Add a raw LLM output table for debugging.

## API: one error envelope, 201 + Location, offset pagination
- **Decision:** every error is `{"error": {"code", "message", "details"}}` with a stable `ErrorCode` enum mapped to HTTP status in one table; `POST /api/extract` returns 201 + `Location`; list uses `page`/`page_size` (max 100), newest first, summaries without clauses.
- **Alternatives considered:** FastAPI's default `{"detail": ...}`; RFC 7807 problem+json; cursor pagination.
- **Why:** clients branch on `code`, not on message text; one mapping table keeps status codes consistent; offset pagination is enough for SQLite-scale data.
- **Tradeoff / what I'd do with more time:** offset pagination drifts under concurrent inserts; switch to a `created_at,id` cursor. Total LLM failure still stores a `failed` row and returns 502 with its `document_id`.

## LLM segments, code verifies: the model returns anchors, never clause text
- **Decision:** per chunk the LLM returns number, title, clause_type, a verbatim `start_anchor`, subsection numbers and confidence; code locates anchors (whitespace/case/quote-insensitive) and slices clause text from anchor to next anchor.
- **Alternatives considered:** regex heading segmentation + LLM classification; LLM copies full clause text; whole document in one call.
- **Why:** samples use 3+ numbering styles (`1.Definition`, ALL-CAPS run-ins, `ARTICLE N`) that regex handles badly; slicing from source makes text verbatim by construction (no hallucinated clause text) and cuts output tokens ~10x.
- **Tradeoff / what I'd do with more time:** a bad anchor means a clause without text (kept and flagged, never dropped); clause text includes running page headers. Add header/footer stripping and an eval set to tune the prompt.

## Structured outputs instead of a forced tool call (API constraint)
- **Decision:** `client.beta.messages.create` with `output_config.format` = JSON schema built by `anthropic.transform_schema(ChunkExtraction)`; check `stop_reason` (refusal / max_tokens fail the chunk) and count usage *before* validating with Pydantic ourselves; one repair retry that appends the model's answer + the validation error; system prompt cached; effort `medium`; server-side refusal `fallbacks="default"`; the model that actually answered is stored.
- **Alternatives considered:** forced `tool_choice` (original plan); `messages.parse(output_format=...)`; free-text JSON.
- **Why:** Claude Sonnet 5.5 rejects forced `tool_choice` (400). `parse()` validates inside the SDK, so truncation/refusal surfaced as `ValidationError` and the billed tokens of failed attempts were lost (found by the code-review subagent).
- **Tradeoff / what I'd do with more time:** relies on beta features (fallbacks); a truncated chunk fails instead of being split and retried; effort chosen by judgment, not by an eval.

## Page-aligned chunks with one page of overlap, merged by offset + identity
- **Decision:** pack whole pages up to `CHUNK_CHARS` (40k chars), repeat the last page in the next chunk, search anchors only inside the chunk's own range, merge clauses from different chunks that start within 50 chars (even if labelled `ARTICLE 5` vs `5`); an unlocated clause is dropped as a duplicate only if another chunk located the same clause inside its range.
- **Alternatives considered:** fixed token windows; no overlap; distance-only dedup.
- **Why:** pages give exact page attribution; overlap keeps a clause cut at a boundary visible whole once; distance-only dedup within one chunk merged short adjacent clauses, and number-only dedup dropped schedule clauses that restart at 1 (both caught by tests / code review).
- **Tradeoff / what I'd do with more time:** a clause longer than a chunk is only seen in pieces (fine for segmentation, since only its start matters).

## Synchronous endpoint with concurrent chunk calls
- **Decision:** `POST /api/extract` waits for the result; chunks run with `asyncio.gather` under a semaphore (`LLM_CONCURRENCY=4`); a failed chunk makes the document `partial`, all failed makes it `failed` (stored, 502).
- **Alternatives considered:** 202 Accepted + background job + polling.
- **Why:** the spec says POST "returns JSON with all clauses"; less code and fewer states to test in a 4h budget. Measured timing for the 176-page sample is in the README.
- **Tradeoff / what I'd do with more time:** long documents hold an HTTP request open; move to a job queue (the `status` column already supports it).

## Coverage check: surface possible text loss as document warnings
- **Decision:** after alignment, report `NUMBERING_GAP` (e.g. ARTICLE 4 -> 6), `UNCOVERED_TEXT` (text before the first clause without a preamble), `ANCHOR_NOT_FOUND` (and flag the clause that probably contains it), `CHUNK_FAILED` (pages only a failed chunk covered).
- **Alternatives considered:** trust the LLM's segmentation; fail the request on any gap.
- **Why:** "never silently drop" needs a check that is independent of the model; real contracts do skip numbers, so this warns rather than fails.
- **Tradeoff / what I'd do with more time:** heuristics (first integer of the number, 200-char threshold) can produce false positives on unusual numbering.

## Prompt iterations driven by real runs (v1 -> v3)
- **Decision:** v2 tells the model a slice can start inside a long article (subsections like `5.13` without their parent heading are continuations), backed by a deterministic merge of leaked `N.M` clauses into their parent `N`; v3 adds an explicit confidence rubric (`low` only when the clause *start* is doubtful). The first-clause prefix is now always checked, so cover/TOC pages surface as `UNCOVERED_TEXT`.
- **Alternatives considered:** trust the model's own confidence as is; fix leaks only in the prompt, or only in code.
- **Why:** on the 176-page sample v1 reported `5.13`, `5.14`, `28.1.2-4` as top-level clauses, and pages 1-9 vanished without a warning. The Leumi NDA (same template as DELACE) got 9/11 clauses `low` in one run and 0 in another; with the v3 rubric it was 0/11 in 3 of 3 runs.
- **Tradeoff / what I'd do with more time:** model confidence is still self-reported, not calibrated against labels; roman-numeral sections in exhibits can still leak at chunk boundaries (ACUTRAQ `IX.`). Build a small labelled eval set and track precision/recall per prompt version.

## Temperature: model default (1.0), because 0 is rejected
- **Decision:** send no sampling parameters; calls run at the API default temperature 1.0. Documented next to the LLM call in `app/services/llm.py`.
- **Alternatives considered:** `temperature=0` for determinism (requested); switching to a model that still accepts sampling parameters (Claude Sonnet 4.6 / Haiku 4.5).
- **Why:** verified against the API: `temperature=0` on `claude-sonnet-5-5` returns 400 "`temperature` is deprecated for this model" (req_011CfoZH63b7fifgpWRn9grv), 1.0 is accepted; the installed SDK (anthropic 1.12) no longer exposes the parameter. Downgrading the model only to get temperature 0 would trade quality for a determinism we don't have anyway (overlapping chunks, effort-based thinking).
- **Tradeoff / what I'd do with more time:** results vary between runs (e.g. ACUTRAQ 39 vs 33 clauses, Leumi confidence before the v3 rubric). Next step is an eval harness: labelled clause boundaries/types for the samples, N runs per prompt version, report precision/recall and run-to-run variance.

## Correction: overlap dedup by identity, guarded subsection fold, no preamble exemption
- **Decision:** supersedes parts of the chunking and coverage entries above. Two located clauses are one only at the same offset, or within 50 chars *with the same identity* (digits of the number; for unnumbered clauses the label + type + title), and the nearest match wins. A leaked `N.M` clause is folded into `N` only if no unlocated clause sits between them, and the parent keeps the lower confidence. `UNCOVERED_TEXT` now covers all text before the first located clause (the preamble exemption is gone). The clause whose slice runs over a failed chunk's range is flagged `MAY_CONTAIN_MISSING_CLAUSE`.
- **Alternatives considered:** keep "any cross-chunk clause within 50 chars is a duplicate" (previous behaviour); fold every `N.M` after `N`.
- **Why:** second code review reproduced two silent failures: `12. [Reserved].` / `13. [Reserved].` seen by both chunks were relabelled (text of 12 stored as 13, duplicate 14, false gap), and "Exhibit A" / "Exhibit B" without digits collided so an unlocated Exhibit B was dropped without a warning. Regression tests added for both, for the guarded fold and for the failed-range flag.
- **Tradeoff / what I'd do with more time:** the same clause labelled with different digits by two chunks (e.g. "5" vs "5.0") is now kept twice instead of merged; it shows up as a near-empty clause rather than being lost. Note: two earlier entries in this file were edited in place before this append-only correction.
