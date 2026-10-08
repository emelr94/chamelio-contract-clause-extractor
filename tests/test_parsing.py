from pathlib import Path

import pymupdf
import pytest

from app.errors import AppError
from app.schemas.enums import ErrorCode, FileType
from app.services.parsing import detect_file_type, parse_document

SAMPLES = Path(__file__).parent.parent / ".samples"
NDA_PDF = SAMPLES / "DELACE (PTY) LTD-Sales - RoW Non-Disclosure Agreement (NDA) (091123).pdf"
DOCX_FILE = next(SAMPLES.glob("*.docx"), None)
LIMITS = {"max_pages": 300, "min_chars_per_page": 50}


def _pdf_bytes(pages: list[str]) -> bytes:
    pdf = pymupdf.open()
    for text in pages:
        page = pdf.new_page()
        if text:
            page.insert_text((72, 72), text)
    return pdf.tobytes()


def _error_code(exc_info: pytest.ExceptionInfo[AppError]) -> ErrorCode:
    return exc_info.value.code


def test_text_pdf_is_parsed_per_page() -> None:
    content = _pdf_bytes(["1. Definitions. " * 10, "2. Term. " * 10])
    parsed = parse_document(FileType.PDF, content, **LIMITS)
    assert parsed.page_count == 2
    assert parsed.pages[1].startswith("2. Term.")


@pytest.mark.skipif(not NDA_PDF.exists(), reason="sample contract not available")
def test_sample_nda_has_text_on_every_page() -> None:
    parsed = parse_document(FileType.PDF, NDA_PDF.read_bytes(), **LIMITS)
    assert parsed.page_count == 3
    assert "Definition of Confidential Information" in parsed.pages[0]


def test_blank_pdf_is_reported_as_scanned() -> None:
    with pytest.raises(AppError) as exc_info:
        parse_document(FileType.PDF, _pdf_bytes(["", ""]), **LIMITS)
    assert _error_code(exc_info) is ErrorCode.SCANNED_PDF_UNSUPPORTED


def test_corrupt_pdf_is_unreadable() -> None:
    with pytest.raises(AppError) as exc_info:
        parse_document(FileType.PDF, b"%PDF-1.7 garbage", **LIMITS)
    assert _error_code(exc_info) is ErrorCode.UNREADABLE_DOCUMENT


def test_page_limit_is_enforced() -> None:
    with pytest.raises(AppError) as exc_info:
        parse_document(FileType.PDF, _pdf_bytes(["x" * 100] * 3), max_pages=2, min_chars_per_page=1)
    assert _error_code(exc_info) is ErrorCode.DOCUMENT_TOO_LARGE


@pytest.mark.skipif(DOCX_FILE is None, reason="sample docx not available")
def test_docx_is_parsed_without_page_numbers() -> None:
    parsed = parse_document(FileType.DOCX, DOCX_FILE.read_bytes(), **LIMITS)
    assert parsed.page_count is None
    assert "1. Appointment." in parsed.pages[0]


@pytest.mark.parametrize(
    ("filename", "content", "expected"),
    [
        ("contract.pdf", b"%PDF-1.7 ...", FileType.PDF),
        ("Contract.DOCX", b"PK\x03\x04...", FileType.DOCX),
    ],
)
def test_detect_file_type_accepts_supported(
    filename: str, content: bytes, expected: FileType
) -> None:
    assert detect_file_type(filename, content) is expected


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("notes.txt", b"hello"),
        ("image.pdf", b"\x89PNG..."),  # extension says PDF, bytes say PNG
        ("contract", b"%PDF-1.7"),
    ],
)
def test_detect_file_type_rejects_unsupported(filename: str, content: bytes) -> None:
    with pytest.raises(AppError) as exc_info:
        detect_file_type(filename, content)
    assert _error_code(exc_info) is ErrorCode.UNSUPPORTED_FILE_TYPE
