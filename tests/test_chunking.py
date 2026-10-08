from itertools import pairwise

from app.schemas.enums import FileType
from app.services.chunking import SourceText, build_chunks
from app.services.parsing import ParsedDocument


def _source(pages: list[str], has_pages: bool = True) -> SourceText:
    return SourceText.from_document(ParsedDocument(FileType.PDF, pages, has_pages))


def test_small_document_is_one_chunk_with_page_markers() -> None:
    source = _source(["page one", "page two"])
    [chunk] = build_chunks(source, max_chars=1000)
    assert chunk.text == "[[PAGE 1]]\npage one\n[[PAGE 2]]\npage two\n"
    assert (chunk.first_page, chunk.last_page) == (1, 2)
    assert source.text[chunk.start : chunk.end] == "page one\npage two"


def test_chunks_overlap_by_one_page_and_cover_everything() -> None:
    source = _source([f"page {n} " + "x" * 90 for n in range(1, 8)])
    chunks = build_chunks(source, max_chars=300)
    assert len(chunks) > 2
    for before, after in pairwise(chunks):
        assert after.first_page == before.last_page
    assert chunks[0].first_page == 1 and chunks[-1].last_page == 7


def test_oversized_page_is_split_at_line_breaks() -> None:
    page = "\n".join(f"line {n} " + "y" * 40 for n in range(50))
    chunks = build_chunks(_source([page]), max_chars=500)
    assert len(chunks) > 1
    assert all(c.first_page == c.last_page == 1 for c in chunks)
    assert all(len(c.text) < 700 for c in chunks)


def test_page_at_maps_offsets_to_pages() -> None:
    source = _source(["aaa", "bbb", "ccc"])
    assert [source.page_at(source.text.index(c)) for c in "abc"] == [1, 2, 3]
    assert _source(["aaa"], has_pages=False).page_at(0) is None
