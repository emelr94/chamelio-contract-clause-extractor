# Contract Clause Extractor

A FastAPI service that takes a contract (PDF or DOCX), splits it into clauses with Claude, and stores the result in SQLite. Every clause keeps its **verbatim source text**, page range, type, number, title and a confidence flag. Any source text that may not be covered by a clause is reported as a document-level warning instead of being silently dropped.

- `POST /api/extract`: upload a contract, get all clauses and metadata (201)
- `GET /api/extractions/{document_id}`: one extraction with its clauses
- `GET /api/extractions?page=1&page_size=20&clause_type=governing_law`: paginated list, newest first

Architecture and data model diagrams: [docs/architecture.md](docs/architecture.md). Every non-trivial decision: [docs/DECISIONS.md](docs/DECISIONS.md).

---

## Setup

You need an Anthropic API key.

```bash
cp .env.example .env        # then set ANTHROPIC_API_KEY in .env
```

### Docker (primary)

```bash
docker build -t clause-extractor .
docker run -p 8000:8000 --env-file .env clause-extractor
# API docs: http://localhost:8000/docs
```

The SQLite file lives inside the container (`./data/app.db`) and is lost when the container is removed. Mount a volume (`-v $PWD/data:/app/data`) to keep it.

### uv (alternative, for development)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # if uv is not installed
uv sync
uv run uvicorn app.main:app --reload
uv run pytest -q                                  # 73 tests, the LLM is always mocked
uv run ruff check . && uv run ruff format --check .
```

### Demo

`scripts/demo.py` runs against a running server (Docker or uv). It uploads every contract, prints status, clause count, timing, tokens and warnings, shows the first clauses, then calls GET by id, the paginated list, the `clause_type` filter and one error case.

```bash
uv run python scripts/demo.py                          # all .pdf/.docx in .samples/
uv run python scripts/demo.py --samples-dir contracts/ # another directory
uv run python scripts/demo.py path/to/contract.pdf     # specific files
uv run python scripts/demo.py --base-url http://localhost:8000
```

**`.samples/` is gitignored**: the sample contracts are not in the repository. Put your own `.pdf`/`.docx` files there or pass `--samples-dir`. The script exits with a clear message if the directory is missing or empty. Parsing tests that use a sample are skipped when it is absent.

Configuration (all optional except the key) is documented in [.env.example](.env.example): model, effort, timeouts, concurrency, chunk size, upload and page limits.

---

## API

| Method & path | Success | Errors |
|---|---|---|
| `POST /api/extract` (multipart `file`) | **201** `ExtractionResponse` + `Location` header; `status` is `completed` or `partial` | 400 `MISSING_FILE` / `EMPTY_FILE`, 413 `FILE_TOO_LARGE`, 415 `UNSUPPORTED_FILE_TYPE`, 422 `UNREADABLE_DOCUMENT` / `SCANNED_PDF_UNSUPPORTED` / `DOCUMENT_TOO_LARGE`, 502 `LLM_ERROR` |
| `GET /api/extractions/{document_id}` | 200 `ExtractionResponse` | 404 `EXTRACTION_NOT_FOUND`, 422 invalid UUID |
| `GET /api/extractions?page&page_size&clause_type` | 200 `{items, total, page, page_size}` (summaries, no clauses) | 422 `VALIDATION_ERROR` |
| `GET /health` | 200 `{"status": "ok"}` | n/a |

Every error has one shape, and clients branch on `code`, never on `message`:

```json
{"error": {"code": "UNSUPPORTED_FILE_TYPE", "message": "Only PDF (.pdf) and Word (.docx) files are supported.", "details": {"filename": "notes.txt"}}}
```

A clause in the response:

```json
{
  "position": 3, "number": "3.", "title": "TERM AND TERMINATION", "clause_type": "term_termination",
  "text": "3. TERM AND TERMINATION. Except as set forth herein, this Agreement will ...",
  "start_page": 2, "end_page": 2, "subsection_numbers": [],
  "confidence": "high", "needs_review": false, "issues": []
}
```

`clause_type` is one of 22 values (`definitions`, `confidentiality`, `term_termination`, `payment`, `warranties`, `liability_limitation`, `indemnification`, `intellectual_property`, `data_protection`, `compliance`, `governing_law`, `dispute_resolution`, `assignment`, `notices`, `force_majeure`, `non_solicitation`, `insurance`, `general_provisions`, `preamble`, `signature_block`, `exhibit`, `other`). Document `warnings` codes: `NUMBERING_GAP`, `UNCOVERED_TEXT`, `ANCHOR_NOT_FOUND`, `CHUNK_FAILED`. Clause `issues`: `ANCHOR_NOT_FOUND`, `LOW_CONFIDENCE`, `MAY_CONTAIN_MISSING_CLAUSE`.

---

## How extraction works

1. **Parse.** PyMuPDF extracts text per page. DOCX is joined paragraphs with no page numbers. Encrypted, corrupt or scanned (under 50 chars/page) files are rejected with 422 before any LLM call.
2. **Chunk.** Whole pages are packed into chunks of up to 40k characters. The last page of each chunk is repeated at the start of the next one, so a clause cut at a boundary is seen whole at least once. The 176-page sample becomes 7 chunks.
3. **LLM, one call per chunk, 4 in parallel.** Claude Sonnet 5.5 returns **where each top-level clause starts** (a verbatim `start_anchor`), plus number, title, type, subsection numbers and confidence, as structured output validated by Pydantic. **It never returns clause text.**
4. **Align (deterministic code).** Each anchor is located in the source, ignoring whitespace, case and quote style. Clause text is the source slice from one anchor to the next, so it is **verbatim by construction** and cannot be hallucinated. Pages come from offsets, not from the model. Duplicates from the overlap are merged. A subsection that leaked out as a clause (`5.13` right after `ARTICLE 5`) is folded back into its parent.
5. **Coverage check.** Possible text loss becomes document `warnings`: numbering gaps, text before the first clause, clauses the model reported but whose start can't be found (kept with empty text and flagged, never dropped), and pages that only a failed chunk covered.
6. **Store** the document and its clauses in one transaction. If at least one chunk failed the status is `partial`; if all failed it is `failed` (the row is stored and the API returns 502 with its `document_id`).

## Design decisions and tradeoffs

Full entries, with the alternatives considered, are in [docs/DECISIONS.md](docs/DECISIONS.md). The short version:

- **The LLM segments, code verifies.** Regex segmentation was rejected: the samples use at least three numbering styles (`1.Definition`, ALL-CAPS run-in headings with the number in a separate text run, `ARTICLE N` with a table of contents). Asking the model to copy clause text was rejected because it costs about 10x the output tokens and can hallucinate.
- **Structured outputs, not a forced tool call.** Claude Sonnet 5.5 rejects forced `tool_choice` (400). We check `stop_reason` and count usage *before* validating, so refusals and truncation fail the chunk cleanly and the tokens they used are still reported.
- **Synchronous endpoint, concurrent chunks.** The spec says POST "returns JSON with all clauses", and the measured 11–16 s for 176 pages makes that acceptable. A `status` column is already in place for a move to a job queue.
- **Two normalized tables** (`documents`, `clauses`). Clauses can be queried by type, and the model, prompt version and token columns make every result reproducible and its cost visible.
- **One error envelope** with a stable `ErrorCode` enum mapped to HTTP status in a single table.
- **Temperature is the API default (1.0).** `temperature=0` returns 400 on this model ("`temperature` is deprecated for this model", verified), and the installed SDK no longer has the parameter. Stability comes from the output schema and the deterministic alignment.
- **PyMuPDF** for text quality. It is **AGPL**, so a commercial deployment needs a license or a swap to pypdf (BSD) behind the same function.
- **Simplifications on purpose:** SQLite with `create_all` (no Alembic), offset pagination, no auth, no OCR.

## Assumptions

1. **"All clauses"** means every top-level numbered or headed section, plus the preamble, the signature block and each exhibit/appendix as one clause. Subsections stay inside their parent's text; their numbers are listed in `subsection_numbers`. Table-of-contents entries are not clauses.
2. **"Metadata"** means document and processing metadata (file, size, sha256, pages, status, model, prompt version, tokens, timing, warnings) and per-clause metadata. Contract-level fields (parties, dates) are out of scope.
3. The server generates `document_id`. One upload is one extraction: re-uploading creates a new record (sha256 is stored, but there is no dedup).
4. "Stores the result" means the structured result. The original file and the raw text are not stored.
5. Input is English digital PDFs and DOCX. Scanned PDFs are rejected. No auth (internal service).

---

## Performance (latest run)

Run through Docker with `scripts/demo.py` on the six samples. Settings: `claude-sonnet-5-5`, prompt **v3**, effort `medium`, 40k-char chunks, concurrency 4. Cost uses $2 / $10 per million input / output tokens.

| Sample | Pages | LLM calls | Clauses | Needs review | Server time | Tokens in / out | ≈ Cost |
|---|---|---|---|---|---|---|---|
| NYISO/NYSEG FERC agreement | **176** | 7 | 40 | 3 | **15.7 s** | 111,680 / 5,128 | $0.27 |
| ACUTRAQ service agreement | 23 | 2 | 39 | 1 | 21.8 s | 27,379 / 4,039 | $0.10 |
| RSE transfer-agent (DOCX) | n/a | 1 | 21 | 0 | 13.4 s | 9,582 / 1,844 | $0.04 |
| DELACE NDA | 3 | 1 | 11 | 0 | 8.7 s | 4,289 / 952 | $0.02 |
| Leumi NDA | 3 | 1 | 11 | 0 | 8.4 s | 4,456 / 959 | $0.02 |
| "Best case" NDA template | 3 | 1 | 11 | 0 | 7.8 s | 4,461 / 980 | $0.02 |

- **Sync vs async.** Time grows with ⌈chunks / 4⌉, not with page count: the 176-page contract (7 chunks) finished faster than the 23-page one, whose second chunk produced more output. Synchronous is fine at this size. A contract several times longer, or many concurrent uploads, would need a job queue.
- **Results vary between runs.** The same code and prompt gave ACUTRAQ 33 clauses in one run and 39 in this one: an appendix was split into its Roman-numeral sections or kept whole. FERC took 11.3 s in one run and 15.7 s in this one. No text was lost in any run, because clause text comes from the source. **An eval harness is the next step**: labelled clause boundaries and types for the samples, several runs per prompt version, precision/recall and run-to-run variance.
- **Prompt caching works.** The system prompt plus schema (about 1.8k tokens) is cached. In a full run, the first two concurrent calls write the cache and the remaining 11 calls read it (`cache_read_input_tokens=1745–1819`). Per-call usage is logged by `app/services/llm.py`.

## Prompt version history

The version is stored on every extraction (`documents.prompt_version`). Each change came from looking at real output.

| Version | Change | Why (observed on real runs) |
|---|---|---|
| v1 | Clause definition, TOC/header rules, verbatim anchors, 22 types | Baseline |
| v2 | "A slice can begin inside a long article; `5.13` without its parent heading is a continuation." Code also folds leaked `N.M` clauses into their parent `N`. | On the 176-page contract a chunk started inside ARTICLE 5 and ARTICLE 28, and the model returned `5.13`, `5.14`, `28.1.2–28.1.4` as top-level clauses. |
| v3 | Explicit confidence rubric: `high` = normal, `medium` = type is a judgment call, `low` = the clause *start* is doubtful | The Leumi NDA (same template and equally clean text as DELACE) had 9 of 11 clauses `low` in one run and 0 in another. With v3 it was 0 of 11 in 3 of 3 runs. |

The same review of the 176-page output found that the cover page and TOC (pages 1–9) were silently outside every clause. The code had exempted text before a preamble; that exemption was removed, so it now produces an `UNCOVERED_TEXT` warning.

## Known limits

- **Cover page / TOC is reported, not classified.** On the 176-page sample, 18k characters (pages 1–10) produce an `UNCOVERED_TEXT` warning. That is correct (the text is in no clause) but noisy: the warning doesn't know it is a table of contents.
- **One `clause_type` per clause.** A clause covering several topics gets its main one. The NDAs' governing-law sentence lives in `7. Miscellaneous` (`general_provisions`), so `?clause_type=governing_law` does not return those NDAs. ACUTRAQ's "Indemnification and Limitation of Liability" is one clause typed `indemnification`.
- **Model confidence is self-reported**, not calibrated against labels (see v3 above).
- **Roman-numeral sections can leak at chunk boundaries** (ACUTRAQ's FCRA exhibit `IX.`). The subsection fold and the numbering-gap check only handle Arabic numbers.
- **Numbering-gap warnings can be false positives**: in one run the model returned ACUTRAQ's `SERVICES.` clause without its number, which produced `NUMBERING_GAP 1. → 3.` (the clause was there, and flagged `LOW_CONFIDENCE`).
- **Clause text includes running page headers/footers** (e.g. the FERC docket header on every page), because text is sliced verbatim.
- **Pages with no text** inside an otherwise digital PDF are not warned about individually. **DOCX tables, headers and footers are not extracted**; DOCX clauses have no page numbers.
- A chunk whose answer exceeds the output limit fails (and is reported) instead of being split and retried. A chunk that times out reports 0 tokens (the cancelled attempt's usage is unknown).
- The same clause labelled with different digits by two overlapping chunks (e.g. `5` vs `5.0`) is kept twice rather than merged; it shows up as a near-empty clause, not as lost text.
- Results vary between runs (temperature cannot be lowered on this model).

## What I'd improve with more time

1. **Eval harness**: gold clause boundaries/types for the samples (or CUAD), several runs per prompt version, precision/recall and variance. This is the basis for every other prompt or model change.
2. **Multi-label clause types** (a primary type plus secondary topics), so governing law inside "Miscellaneous" is findable.
3. **Classify front matter**: detect the cover page and TOC as their own (non-clause) sections instead of a generic `UNCOVERED_TEXT` warning.
4. **Layout-aware parsing**: strip running headers/footers, handle tables and multi-column pages, OCR for scanned PDFs (Tesseract or a vision model), DOCX tables and real page mapping.
5. **Async jobs** (202 + polling, a worker queue) for very long documents and many concurrent uploads; Postgres + Alembic; auth and rate limiting on our own API.
6. **Contract-level metadata** (parties, effective date, term, governing law) and sha256 dedup / caching of results.
7. Split and retry a chunk that hits the output limit; handle Roman numbering in the subsection fold and gap check.

---

## Code review

The `code-reviewer` subagent reviewed the code twice: after the LLM pipeline (M3) and before submission (M6). Each finding was checked and either fixed (with a regression test) or deliberately deferred.

**First pass (after M3): 13 findings, 12 fixed.**
- **Fixed, serious:**
  - `align` crashed (500) when no anchor was found.
  - A failed piece of a split page lost text without a warning; lost ranges are now computed from character offsets.
  - `messages.parse()` validated inside the SDK, so the truncation/refusal handling never ran and the tokens of failed attempts were dropped. Replaced with `create()` + our own validation.
- **Fixed:**
  - Empty anchors matched anywhere.
  - A schedule clause reusing number "1" could be dropped as a duplicate.
  - `ARTICLE 5` vs `5` duplicates were not merged.
  - Out-of-order clauses were blamed on the wrong parent.
  - Our own bugs were reported as "chunk failed".
  - There was no overall time cap per chunk.
  - The stored model ignored refusal fallbacks.
  - The blocking DB write ran on the event loop.
  - A 36-dash string was accepted as a UUID.
  - 405 responses lost the `Allow` header.
  - Zero concurrency or chunk size hung the service.
- **Not adopted:** "the system prompt is too short to cache" was disproved by the measured cache reads.
- **Deferred:** the per-page empty-text warning and DOCX tables (listed under known limits).

**Second pass (before submission): 11 findings, 9 fixed, 2 documented.** Details in [docs/code-review-2.md](docs/code-review-2.md).
- **Fixed, serious:**
  - Cross-chunk dedup could relabel text: `12. [Reserved].` stored as clause 13, which also created a false numbering gap.
  - "Exhibit A" / "Exhibit B" without digits collided, so an unlocated Exhibit B was dropped without a warning.
- **Fixed:**
  - The subsection fold could cross an unfound heading and lost a low-confidence child's flag.
  - The clause absorbing a failed chunk's text was not flagged.
  - `model_context_window_exceeded` was not treated as truncation.
  - Hook edge cases: fail closed on bad input, `printf` for logging, background-task notifications were logged as prompts.
- **Documented:** a timed-out chunk reports 0 tokens; Bash writes bypass the file-protection hook's matcher.

## AI usage

This project was built with Claude Code (Claude Opus 5.5) as a pair programmer, under my direction. The point was to use the model for speed and for review, while keeping every decision visible and checked.

**How the work was structured**
- **Plan first.** Claude read the samples and the environment, then interviewed me on the design-changing choices. For each it gave a recommended option and the tradeoff: clause definition, provider/model, sync vs async, schema depth, segmentation strategy, bonus scope, packaging. I chose, and then **edited the plan before any code was written**:
  - add a coverage check for numbering gaps and unaccounted text;
  - list every enum explicitly;
  - measure the 176-page contract for the sync/async decision;
  - Docker as the primary setup;
  - decision log entries as we go;
  - a code-review subagent after M3 and M6.
- **Small milestones** (scaffold → parsing → API with a stub → LLM pipeline → demo/Docker → docs), each verified with `pytest` + `ruff` before moving on.
- **Evidence trail:** [docs/DECISIONS.md](docs/DECISIONS.md) (written when each decision was made) and [docs/prompt-log.md](docs/prompt-log.md). **The prompt log is incomplete:** the hook that writes it depended on `jq`, which was not installed when the project started, so it silently logged nothing (and the file-protection hook was silently disabled too). I noticed late, when `docs/prompt-log.md` had never appeared. The hooks now fall back to `python3`, and the log starts from that point. Earlier prompts were not reconstructed by hand. The log also contains one background-task notification from before the hook learned to skip them.

**Generated by AI:** essentially all application code, tests, the demo script, the diagrams and the first draft of this README and of the decision log.

**Checked, changed or rejected by me (or by running real checks), not taken on trust:**
- **API facts were verified, not recalled.**
  - Forced tool use was rejected because the model returns 400 for it; this was found by reading the current API docs before coding.
  - `temperature=0` was tested against the real API: 400. I had asked for 0; it is documented as not possible instead of being silently skipped.
- **The first LLM implementation was replaced** after review: `messages.parse()` hid truncation and lost token counts.
- **Real runs changed the design.** Leaked subsections, the silently missing cover/TOC and unstable confidence were all found by reading the 176-page output, not by tests, and led to prompts v2–v3.
- **Two review passes by a subagent found real bugs that 67 passing tests had missed** (text relabelled, clauses dropped without a warning, dead truncation handling). Each was reproduced, fixed and pinned with a regression test.
- **Process slip:** the decision log is meant to be append-only. Two entries were edited in place before this was noticed; later corrections are appended.
- **Things the model got wrong that tests or review caught:**
  - distance-only dedup merged neighbouring clauses;
  - a `min_length` schema constraint would have failed whole chunks on short clauses like "3. Reserved." (reverted);
  - first-integer identity treated `5.13` as a duplicate of `ARTICLE 5`;
  - an early scan gave wrong page counts (5 and 24 instead of 3 and 23). I questioned these; PyMuPDF and the PDFs' own page trees confirm 3 and 23.
- **Kept deliberately small at my request:** no new logic for TOC classification or multi-label types. They are documented as limits instead.
- **Tests never call the real LLM.** Only the demo and the measurement runs do.
