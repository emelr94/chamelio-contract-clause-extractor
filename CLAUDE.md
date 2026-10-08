# Chamelio take-home: Contract Clause Extractor

## Task
FastAPI service that extracts and structures clauses from legal contracts.
- `POST /api/extract`: accepts a PDF, returns JSON with all clauses + metadata, stores the result in a DB
- `GET /api/extractions/{document_id}`: one extraction
- `GET /api/extractions`: list, paginated
- Required: FastAPI, Pydantic validation, a DB (SQLite is fine), Dockerfile
- Bonus: DOCX support, basic tests, LLM usage
- Deliverables: repo, README (setup, design decisions + tradeoffs, what I'd improve, assumptions), e2e demo script, diagram of the final solution

Grading: code quality 25%, AI usage 30%, API design 20%, data modeling 15%, docs 10%.
"The discussion > the code." Do not over-engineer. Budget is 3-4h (max 4-5h). Core first, bonus later.

## Proposed defaults (change freely, but log the decision)
- Python 3.12, FastAPI, Pydantic v2, SQLite via SQLAlchemy 2.0, pytest, ruff
- Layout: `app/{main.py,api/,schemas/,services/,db/}`, `tests/`, `scripts/demo.py`, `docs/`
- All LLM calls live behind one service class so they can be mocked
- LLM output is validated with Pydantic; every clause keeps its source text and page number
- Uncertain or malformed LLM results are flagged, never silently dropped

## Rules
- Plan first for anything that touches more than one file. Work in small steps and run tests after each.
- Type hints everywhere, no magic strings, consistent error schema with proper HTTP status codes.
- Tests never call the real LLM; they mock it.
- Never commit `.env` or API keys. Keep `.env.example` up to date.
- Record every non-trivial decision with `/decision-log` (writes to `docs/DECISIONS.md`).
- Prompts are logged automatically to `docs/prompt-log.md` by a hook. Do not edit that file.
- Before finishing, run `/submit-check`.

## Commands
- Run: `uvicorn app.main:app --reload`
- Test: `pytest -q`
- Lint/format: `ruff check . && ruff format .`
- Docker: `docker build -t clause-extractor . && docker run -p 8000:8000 --env-file .env clause-extractor`
