import pytest
from fastapi.testclient import TestClient

from app.schemas.enums import DocumentStatus
from app.schemas.extraction import ExtractionResult
from tests.conftest import FakeExtractor, make_pdf

PDF = make_pdf(["1. Confidentiality. " * 10, "2. Governing Law. " * 10])


def _upload(client: TestClient, content: bytes = PDF, filename: str = "contract.pdf"):
    return client.post("/api/extract", files={"file": (filename, content, "application/pdf")})


def _assert_error(response, status_code: int, code: str) -> None:
    assert response.status_code == status_code, response.text
    body = response.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert body["error"]["message"]


def test_extract_returns_201_and_persists(client: TestClient) -> None:
    response = _upload(client)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["file_type"] == "pdf"
    assert body["page_count"] == 2
    assert body["clause_count"] == 2
    assert [c["clause_type"] for c in body["clauses"]] == ["confidentiality", "governing_law"]
    assert [c["position"] for c in body["clauses"]] == [0, 1]
    assert response.headers["Location"] == f"/api/extractions/{body['document_id']}"

    fetched = client.get(response.headers["Location"])
    assert fetched.status_code == 200
    assert fetched.json() == body


def test_get_unknown_extraction_is_404(client: TestClient) -> None:
    response = client.get("/api/extractions/00000000-0000-0000-0000-000000000000")
    _assert_error(response, 404, "EXTRACTION_NOT_FOUND")


@pytest.mark.parametrize("bad_id", ["not-a-uuid", "-" * 36])
def test_get_malformed_id_is_422(client: TestClient, bad_id: str) -> None:
    _assert_error(client.get(f"/api/extractions/{bad_id}"), 422, "VALIDATION_ERROR")


def test_list_is_paginated_newest_first(client: TestClient) -> None:
    ids = [_upload(client).json()["document_id"] for _ in range(3)]

    first = client.get("/api/extractions", params={"page": 1, "page_size": 2}).json()
    second = client.get("/api/extractions", params={"page": 2, "page_size": 2}).json()

    assert first["total"] == 3
    assert first["page_size"] == 2
    assert [d["document_id"] for d in first["items"] + second["items"]] == ids[::-1]
    assert "clauses" not in first["items"][0]


def test_list_filters_by_clause_type(client: TestClient, fake_extractor: FakeExtractor) -> None:
    _upload(client)
    fake_extractor.result = fake_extractor.result.model_copy(
        update={"clauses": fake_extractor.result.clauses[:1]}  # confidentiality only
    )
    _upload(client)

    governing = client.get("/api/extractions", params={"clause_type": "governing_law"}).json()
    confidentiality = client.get("/api/extractions", params={"clause_type": "confidentiality"})

    assert governing["total"] == 1
    assert confidentiality.json()["total"] == 2


@pytest.mark.parametrize("params", [{"page": 0}, {"page_size": 101}, {"clause_type": "not_a_type"}])
def test_list_rejects_bad_params(client: TestClient, params: dict[str, object]) -> None:
    _assert_error(client.get("/api/extractions", params=params), 422, "VALIDATION_ERROR")


def test_missing_file_is_400(client: TestClient) -> None:
    _assert_error(client.post("/api/extract"), 400, "MISSING_FILE")


def test_empty_file_is_400(client: TestClient) -> None:
    _assert_error(_upload(client, content=b""), 400, "EMPTY_FILE")


def test_unsupported_type_is_415(client: TestClient) -> None:
    _assert_error(_upload(client, b"just text", "notes.txt"), 415, "UNSUPPORTED_FILE_TYPE")


def test_oversized_file_is_413(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_upload_mb", 0)
    _assert_error(_upload(client), 413, "FILE_TOO_LARGE")


def test_scanned_pdf_is_422(client: TestClient, fake_extractor: FakeExtractor) -> None:
    _assert_error(_upload(client, make_pdf(["", ""])), 422, "SCANNED_PDF_UNSUPPORTED")
    assert fake_extractor.calls == []  # rejected before any LLM work


def test_total_llm_failure_is_502_and_stored(
    client: TestClient, fake_extractor: FakeExtractor
) -> None:
    fake_extractor.result = ExtractionResult(
        status=DocumentStatus.FAILED,
        clauses=[],
        model="fake-model",
        prompt_version="test",
        error="LLM unavailable",
    )
    response = _upload(client)

    _assert_error(response, 502, "LLM_ERROR")
    document_id = response.json()["error"]["details"]["document_id"]
    stored = client.get(f"/api/extractions/{document_id}").json()
    assert stored["status"] == "failed"
    assert stored["error"] == "LLM unavailable"


def test_unknown_route_uses_error_schema(client: TestClient) -> None:
    _assert_error(client.get("/api/nope"), 404, "HTTP_ERROR")


def test_wrong_method_keeps_allow_header(client: TestClient) -> None:
    response = client.delete("/api/extractions")
    _assert_error(response, 405, "HTTP_ERROR")
    assert "GET" in response.headers["allow"]
