import hashlib
import time
import uuid
from typing import Annotated

from fastapi import APIRouter, File, Path, Query, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool

from app.api.deps import ExtractorDep, SessionDep, SettingsDep
from app.db import repository
from app.errors import AppError
from app.schemas.api import ErrorResponse, ExtractionResponse, ExtractionSummary, Page
from app.schemas.enums import ClauseType, DocumentStatus, ErrorCode
from app.services.parsing import detect_file_type, parse_document

router = APIRouter(prefix="/api", tags=["extractions"])

MAX_PAGE_SIZE = 100


def _errors(*codes: int) -> dict[int | str, dict[str, object]]:
    return {code: {"model": ErrorResponse} for code in codes}


@router.post(
    "/extract",
    status_code=status.HTTP_201_CREATED,
    response_model=ExtractionResponse,
    responses=_errors(400, 413, 415, 422, 502),
    summary="Upload a contract (PDF or DOCX) and extract its clauses",
)
async def extract(
    file: Annotated[UploadFile, File(description="Contract file (.pdf or .docx)")],
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    extractor: ExtractorDep,
) -> ExtractionResponse:
    started = time.perf_counter()
    content = await file.read(settings.max_upload_bytes + 1)
    if not content:
        raise AppError(ErrorCode.EMPTY_FILE, "The uploaded file is empty.")
    if len(content) > settings.max_upload_bytes:
        raise AppError(
            ErrorCode.FILE_TOO_LARGE,
            f"The file exceeds the {settings.max_upload_mb} MB limit.",
            {"max_upload_mb": settings.max_upload_mb},
        )

    filename = file.filename or "upload"
    file_type = detect_file_type(filename, content)
    parsed = await run_in_threadpool(
        parse_document,
        file_type,
        content,
        max_pages=settings.max_pages,
        min_chars_per_page=settings.min_chars_per_page,
    )
    result = await extractor.extract(parsed)

    document = await run_in_threadpool(  # blocking SQLite commit: keep it off the event loop
        repository.save_extraction,
        session,
        filename=filename,
        file_type=file_type,
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        page_count=parsed.page_count,
        processing_ms=round((time.perf_counter() - started) * 1000),
        result=result,
    )
    if document.status == DocumentStatus.FAILED:
        raise AppError(
            ErrorCode.LLM_ERROR,
            "Clause extraction failed for every part of the document.",
            {"document_id": document.id, "reason": document.error},
        )
    response.headers["Location"] = f"{router.prefix}/extractions/{document.id}"
    return ExtractionResponse.model_validate(document)


@router.get(
    "/extractions/{document_id}",
    response_model=ExtractionResponse,
    responses=_errors(404, 422),
    summary="Get one extraction with all its clauses",
)
def get_extraction(
    document_id: Annotated[uuid.UUID, Path()], session: SessionDep
) -> ExtractionResponse:
    document = repository.get_document(session, str(document_id))
    if document is None:
        raise AppError(
            ErrorCode.EXTRACTION_NOT_FOUND,
            f"No extraction with id '{document_id}'.",
            {"document_id": str(document_id)},
        )
    return ExtractionResponse.model_validate(document)


@router.get(
    "/extractions",
    response_model=Page[ExtractionSummary],
    responses=_errors(422),
    summary="List extractions, newest first",
)
def list_extractions(
    session: SessionDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
    clause_type: Annotated[
        ClauseType | None, Query(description="Only documents containing this clause type")
    ] = None,
) -> Page[ExtractionSummary]:
    documents, total = repository.list_documents(
        session, page=page, page_size=page_size, clause_type=clause_type
    )
    return Page[ExtractionSummary](
        items=[ExtractionSummary.model_validate(d) for d in documents],
        total=total,
        page=page,
        page_size=page_size,
    )
