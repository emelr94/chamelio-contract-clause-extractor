import os

# Tests never call the real LLM; a dummy key only satisfies settings validation.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")

from collections.abc import Iterator
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_extractor
from app.db.session import build_engine, get_session
from app.main import app
from app.schemas.enums import ClauseType, Confidence, DocumentStatus
from app.schemas.extraction import ExtractedClause, ExtractionResult
from app.services.parsing import ParsedDocument


def make_pdf(pages: list[str]) -> bytes:
    pdf = pymupdf.open()
    for text in pages:
        page = pdf.new_page()
        if text:
            page.insert_text((72, 72), text)
    return pdf.tobytes()


class FakeExtractor:
    """Returns a canned result; records what it was called with."""

    def __init__(self, result: ExtractionResult | None = None) -> None:
        self.result = result or ExtractionResult(
            status=DocumentStatus.COMPLETED,
            clauses=[
                ExtractedClause(
                    number="1",
                    title="Confidentiality",
                    clause_type=ClauseType.CONFIDENTIALITY,
                    text="1. Confidentiality. The parties shall keep ...",
                    start_page=1,
                    end_page=1,
                    confidence=Confidence.HIGH,
                ),
                ExtractedClause(
                    number="2",
                    title="Governing Law",
                    clause_type=ClauseType.GOVERNING_LAW,
                    text="2. Governing Law. This Agreement is governed by ...",
                    start_page=1,
                    end_page=2,
                    confidence=Confidence.HIGH,
                ),
            ],
            model="fake-model",
            prompt_version="test",
            input_tokens=100,
            output_tokens=20,
        )
        self.calls: list[ParsedDocument] = []

    async def extract(self, document: ParsedDocument) -> ExtractionResult:
        self.calls.append(document)
        return self.result


@pytest.fixture
def session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = build_engine(f"sqlite:///{tmp_path / 'test.db'}")
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def fake_extractor() -> FakeExtractor:
    return FakeExtractor()


@pytest.fixture
def client(
    session_factory: sessionmaker[Session], fake_extractor: FakeExtractor
) -> Iterator[TestClient]:
    def _session() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_extractor] = lambda: fake_extractor
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
