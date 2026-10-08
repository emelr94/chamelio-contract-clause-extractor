# Architecture

## Request flow: `POST /api/extract`

```mermaid
flowchart TD
    C([Client]) -->|multipart file| R["FastAPI route<br/>app/api/routes.py"]
    R -->|"empty → 400, &gt;20 MB → 413,<br/>wrong type → 415"| V{Validate upload<br/>size + extension + magic bytes}
    V --> P["Parse<br/>PyMuPDF per page / python-docx<br/>app/services/parsing.py"]
    P -->|"encrypted / corrupt / scanned / too many pages → 422"| E1([ErrorResponse])
    P --> CH["Chunk<br/>page-aligned, ≤40k chars,<br/>1-page overlap<br/>app/services/chunking.py"]
    CH --> L1["ClauseLLM.extract_chunk"]
    CH --> L2["ClauseLLM.extract_chunk"]
    CH --> L3["… N chunks,<br/>Semaphore(4), 300 s each"]
    subgraph LLM ["app/services/llm.py: the only module that calls Claude"]
        L1 & L2 & L3 --> API[["Claude Sonnet 5.5<br/>structured output (JSON schema)<br/>cached system prompt<br/>refusal fallback"]]
        API --> CHK{"stop_reason?<br/>Pydantic valid?"}
        CHK -->|invalid| RETRY["1 repair retry<br/>(answer + errors appended)"] --> API
        CHK -->|"refusal / truncated / API error"| FAIL["LLMError<br/>(chunk failed, tokens kept)"]
    end
    CHK -->|"valid: number, title, type,<br/>start_anchor, confidence"| A["Align<br/>find anchors in source,<br/>dedupe overlap, fold leaked subsections,<br/>slice verbatim text, derive pages<br/>app/services/alignment.py"]
    FAIL --> COV
    A --> COV["Coverage check<br/>NUMBERING_GAP · UNCOVERED_TEXT ·<br/>ANCHOR_NOT_FOUND · CHUNK_FAILED"]
    COV --> DB[("SQLite<br/>documents + clauses<br/>one transaction")]
    DB -->|"completed / partial"| OK([201 ExtractionResponse<br/>+ Location header])
    DB -->|"all chunks failed: row stored"| E2([502 LLM_ERROR<br/>+ document_id])
```

Read endpoints: `GET /api/extractions/{id}` and `GET /api/extractions?page&page_size&clause_type` go straight to the repository (`app/db/repository.py`).

## Data model

```mermaid
erDiagram
    documents ||--o{ clauses : contains
    documents {
        string id PK "UUID4"
        string filename
        string file_type "pdf | docx"
        int size_bytes
        string sha256 "indexed, not unique"
        int page_count "null for DOCX"
        string status "completed | partial | failed"
        string model "model(s) that answered"
        string prompt_version
        int input_tokens
        int output_tokens
        int processing_ms
        int clause_count
        json warnings "coverage warnings"
        string error
        datetime created_at "indexed"
    }
    clauses {
        int id PK
        string document_id FK "indexed, cascade"
        int position "unique per document"
        string number
        string title
        string clause_type "indexed, 22-value enum"
        text text "verbatim source slice"
        int start_page
        int end_page
        json subsection_numbers
        string confidence "high | medium | low"
        bool needs_review
        json issues
    }
```

## Module layering

```
app/api        routes, error handlers, dependencies (HTTP only)
app/services   parsing → chunking → llm → alignment, orchestrated by extractor
app/db         SQLAlchemy models, session, repository
app/schemas    Pydantic models and enums shared by all layers
app/errors.py  AppError + ErrorCode → HTTP status (raised anywhere, rendered by app/api)
```
