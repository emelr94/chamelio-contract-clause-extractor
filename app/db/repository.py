from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Clause, Document
from app.schemas.enums import ClauseType, FileType
from app.schemas.extraction import ExtractionResult


def save_extraction(
    session: Session,
    *,
    filename: str,
    file_type: FileType,
    size_bytes: int,
    sha256: str,
    page_count: int | None,
    processing_ms: int,
    result: ExtractionResult,
) -> Document:
    """Persist a document and its clauses in one transaction."""
    document = Document(
        filename=filename,
        file_type=file_type,
        size_bytes=size_bytes,
        sha256=sha256,
        page_count=page_count,
        status=result.status,
        model=result.model,
        prompt_version=result.prompt_version,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        processing_ms=processing_ms,
        clause_count=len(result.clauses),
        warnings=[w.model_dump(mode="json") for w in result.warnings],
        error=result.error,
        clauses=[
            Clause(position=position, **clause.model_dump(mode="json"))
            for position, clause in enumerate(result.clauses)
        ],
    )
    session.add(document)
    session.commit()
    return document


def get_document(session: Session, document_id: str) -> Document | None:
    query = (
        select(Document).where(Document.id == document_id).options(selectinload(Document.clauses))
    )
    return session.scalars(query).one_or_none()


def list_documents(
    session: Session, *, page: int, page_size: int, clause_type: ClauseType | None = None
) -> tuple[list[Document], int]:
    """Newest first. With clause_type, only documents containing at least one such clause."""
    query = select(Document)
    if clause_type is not None:
        has_type = exists().where(
            Clause.document_id == Document.id, Clause.clause_type == clause_type
        )
        query = query.where(has_type)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(
        query.order_by(Document.created_at.desc(), Document.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(rows), total
