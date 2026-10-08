from app.schemas.enums import ClauseIssue, ClauseType, Confidence, FileType, WarningCode
from app.schemas.llm import ChunkExtraction, LLMClause
from app.services.alignment import AnchorIndex, align, check_coverage
from app.services.chunking import Chunk, SourceText, build_chunks
from app.services.parsing import ParsedDocument

ONE_CHUNK = 10**6


def _source(*pages: str) -> SourceText:
    return SourceText.from_document(ParsedDocument(FileType.PDF, list(pages), True))


def _clause(
    anchor: str,
    number: str | None = None,
    clause_type: ClauseType = ClauseType.OTHER,
    confidence: Confidence = Confidence.HIGH,
    title: str | None = None,
) -> LLMClause:
    return LLMClause(
        number=number,
        title=title,
        clause_type=clause_type,
        start_anchor=anchor,
        subsection_numbers=[],
        confidence=confidence,
    )


def _run(source: SourceText, *clauses: LLMClause):
    chunk = build_chunks(source, ONE_CHUNK)[0]
    placed = align(source, [(chunk, ChunkExtraction(clauses=list(clauses)))])
    return placed, check_coverage(placed, source, [chunk], [])


def _codes(warnings) -> list[WarningCode]:
    return [w.code for w in warnings]


# --- anchor matching -----------------------------------------------------------------------


def test_anchor_matches_despite_whitespace_case_and_quotes() -> None:
    text = "Intro.\n1.Definition  of\nConfidential “Information”. Means all info."
    index = AnchorIndex(text)
    assert index.find('1. DEFINITION of Confidential "Information"', 0, len(text)) == 7


def test_anchor_matches_broken_word_spacing() -> None:
    text = "Congress has limited the use of c onsumer reports to protect"
    assert AnchorIndex(text).find("limited the use of consumer reports", 0, len(text)) == 13


def test_anchor_search_is_limited_to_the_given_range() -> None:
    text = "ARTICLE 1. DEFINITIONS ....... 4\n" + "x" * 100 + "\nARTICLE 1. DEFINITIONS Whenever"
    index = AnchorIndex(text)
    toc_free_start = text.index("x")
    assert index.find("ARTICLE 1. DEFINITIONS", toc_free_start, len(text)) == text.rindex("ARTICLE")


def test_anchor_falls_back_to_a_prefix_when_the_tail_differs() -> None:
    text = "5. Term and Termination. This Agreement starts on the Effective Date"
    found = AnchorIndex(text).find(
        "5. Term and Termination. This Agreement begins on", 0, len(text)
    )
    assert found == 0


# --- alignment -----------------------------------------------------------------------------


def test_clause_text_is_verbatim_source_between_anchors_with_pages() -> None:
    source = _source("Preamble text.\n1. Scope. The scope", "continues here.\n2. Term. Ten years.")
    placed, _ = _run(
        source,
        _clause("Preamble text.", clause_type=ClauseType.PREAMBLE),
        _clause("1. Scope. The scope", "1"),
        _clause("2. Term. Ten years.", "2"),
    )
    clauses = [p.clause for p in placed]
    assert clauses[1].text == "1. Scope. The scope\ncontinues here."
    assert (clauses[1].start_page, clauses[1].end_page) == (1, 2)
    assert clauses[2].text == "2. Term. Ten years."
    assert all(not c.needs_review for c in clauses)


def test_overlapping_chunks_do_not_duplicate_clauses() -> None:
    pages = [f"{n}. Clause {n}. " + "body " * 30 for n in range(1, 5)]
    source = _source(*pages)
    chunks = build_chunks(source, max_chars=2 * len(pages[0]) + 10)
    assert len(chunks) > 1 and chunks[0].last_page == chunks[1].first_page  # overlap exists

    outputs = []
    for chunk in chunks:
        pages_in_chunk = range(chunk.first_page, chunk.last_page + 1)
        outputs.append(
            (
                chunk,
                ChunkExtraction(
                    clauses=[_clause(f"{n}. Clause {n}.", str(n)) for n in pages_in_chunk]
                ),
            )
        )
    placed = align(source, outputs)
    assert [p.clause.number for p in placed] == ["1", "2", "3", "4"]


def test_low_confidence_clause_needs_review() -> None:
    placed, _ = _run(
        _source("1. Scope. Some text here."), _clause("1. Scope.", "1", confidence=Confidence.LOW)
    )
    assert placed[0].clause.needs_review
    assert placed[0].clause.issues == [ClauseIssue.LOW_CONFIDENCE]


# --- coverage: no silent text loss ---------------------------------------------------------


def test_clean_document_has_no_warnings() -> None:
    source = _source("Preamble. 1. Scope. Text. 2. Term. Text. 3. Law. Text.")
    _, warnings = _run(
        source,
        _clause("Preamble.", clause_type=ClauseType.PREAMBLE),
        _clause("1. Scope.", "1"),
        _clause("2. Term.", "2"),
        _clause("3. Law.", "3"),
    )
    assert warnings == []


def test_numbering_gap_is_reported() -> None:
    source = _source("ARTICLE 4. Fees. Text.\nARTICLE 6. Term. Text.")
    _, warnings = _run(
        source, _clause("ARTICLE 4. Fees.", "ARTICLE 4"), _clause("ARTICLE 6. Term.", "ARTICLE 6")
    )
    assert _codes(warnings) == [WarningCode.NUMBERING_GAP]
    assert warnings[0].details == {"after": "ARTICLE 4", "next": "ARTICLE 6"}


def test_numbering_restart_is_not_a_gap() -> None:
    source = _source("1. Scope. x\n2. Term. x\nSchedule A\n1. Services. x\n2. Fees. x")
    _, warnings = _run(
        source,
        _clause("1. Scope.", "1"),
        _clause("2. Term.", "2"),
        _clause("Schedule A", clause_type=ClauseType.EXHIBIT),
        _clause("1. Services.", "1"),
        _clause("2. Fees.", "2"),
    )
    assert WarningCode.NUMBERING_GAP not in _codes(warnings)


def test_text_before_first_clause_without_preamble_is_uncovered() -> None:
    source = _source("Lorem ipsum " * 50 + "\n1. Scope. Text.")
    _, warnings = _run(source, _clause("1. Scope.", "1"))
    assert _codes(warnings) == [WarningCode.UNCOVERED_TEXT]
    assert warnings[0].details["chars"] >= 500


def test_unlocated_clause_is_kept_and_flags_its_likely_container() -> None:
    source = _source("1. Scope. Text.\n2. Term. Text.\n3. Law. Text.")
    placed, warnings = _run(
        source,
        _clause("1. Scope.", "1"),
        _clause("2. Duration of this agreement", "2"),  # hallucinated anchor
        _clause("3. Law.", "3"),
    )
    numbers = [p.clause.number for p in placed]
    assert numbers == ["1", "2", "3"]  # kept, in order, nothing dropped

    missing = placed[1].clause
    assert missing.text == "" and missing.needs_review
    assert ClauseIssue.ANCHOR_NOT_FOUND in missing.issues

    container = placed[0].clause
    assert ClauseIssue.MAY_CONTAIN_MISSING_CLAUSE in container.issues and container.needs_review
    assert "2. Term." in container.text  # the text is still there, inside clause 1

    assert _codes(warnings) == [WarningCode.ANCHOR_NOT_FOUND]
    assert warnings[0].details == {"clause": "2", "likely_inside": "1"}


def test_pages_only_covered_by_a_failed_chunk_are_reported() -> None:
    source = _source(*[f"{n}. Clause. " + "x " * 20 for n in range(1, 7)])
    chunks = build_chunks(source, max_chars=3 * 60)
    ok, failed = chunks[:1], chunks[1:]
    placed = align(source, [(ok[0], ChunkExtraction(clauses=[_clause("1. Clause.", "1")]))])

    warnings = check_coverage(placed, source, ok, failed)

    lost = [w for w in warnings if w.code is WarningCode.CHUNK_FAILED]
    assert len(lost) == 1
    assert lost[0].start_page == ok[0].last_page + 1  # the overlap page was processed
    assert lost[0].end_page == 6


def test_chunk_failure_on_docx_is_reported_without_pages() -> None:
    source = SourceText.from_document(ParsedDocument(FileType.DOCX, ["1. Scope. Text."], False))
    failed = [Chunk(index=0, start=0, end=15, text="", first_page=None, last_page=None)]
    warnings = check_coverage([], source, [], failed)
    assert _codes(warnings) == [WarningCode.CHUNK_FAILED]
    assert warnings[0].start_page is None


# --- regressions from code review -------------------------------------------------------------


def test_no_located_anchor_does_not_crash() -> None:
    source = _source("Some contract text that the model could not segment at all.")
    placed, _ = _run(source)  # empty extraction
    assert placed == []
    placed, warnings = _run(source, _clause("1. Nonexistent heading text", "1"))
    assert [p.offset for p in placed] == [None]
    assert WarningCode.ANCHOR_NOT_FOUND in _codes(warnings)


def test_too_short_anchor_is_not_searched() -> None:
    text = "1. Scope. Text.\n2. Term. Text."
    assert AnchorIndex(text).find("  ", 0, len(text)) is None
    assert AnchorIndex(text).find("2.", 0, len(text)) is None


def test_unlocated_clause_reusing_a_number_is_kept() -> None:
    source = _source("1. Scope. Text.\nSCHEDULE A\n1. Fees. The fees are ...")
    placed, warnings = _run(
        source,
        _clause("1. Scope. Text.", "1"),
        _clause("SCHEDULE A", clause_type=ClauseType.EXHIBIT),
        _clause("1. Fees payable under this", "1", title="Fees"),  # anchor not in source
    )
    assert [p.clause.number for p in placed] == ["1", None, "1"]
    assert ClauseIssue.ANCHOR_NOT_FOUND in placed[2].clause.issues
    assert WarningCode.ANCHOR_NOT_FOUND in _codes(warnings)


def test_overlap_duplicates_merge_even_if_labelled_differently() -> None:
    pages = [f"ARTICLE {n}. Heading {n}. " + "body " * 15 for n in (4, 5, 6)]
    source = _source(*pages)
    first, second = build_chunks(source, max_chars=2 * len(pages[0]) + 10)
    assert first.last_page == second.first_page == 2  # page 2 (ARTICLE 5) is in both chunks
    outputs = [
        (first, ChunkExtraction(clauses=[_clause("ARTICLE 5. Heading 5.", "ARTICLE 5")])),
        (second, ChunkExtraction(clauses=[_clause("5. Heading 5. body body", "5")])),
    ]
    placed = align(source, outputs)
    assert len(placed) == 1
    assert placed[0].clause.text.startswith("ARTICLE 5.")


def test_out_of_order_listing_still_locates_every_clause() -> None:
    source = _source("1. Scope. Text.\n2. Term. Text.\n3. Law. Text.")
    placed, warnings = _run(
        source, _clause("1. Scope.", "1"), _clause("3. Law.", "3"), _clause("2. Term.", "2")
    )
    assert [p.clause.number for p in placed] == ["1", "2", "3"]
    assert warnings == []


def test_failed_piece_of_a_split_page_is_reported() -> None:
    long_page = "\n".join(f"{n}. Clause {n}. " + "x" * 80 for n in range(1, 13))
    source = _source(long_page)
    chunks = build_chunks(source, max_chars=400)
    assert len(chunks) >= 3 and all(c.first_page == 1 for c in chunks)
    ok = [chunks[0], *chunks[2:]]
    placed = align(source, [(c, ChunkExtraction(clauses=[])) for c in ok])

    warnings = check_coverage(placed, source, ok, [chunks[1]])

    lost = [w for w in warnings if w.code is WarningCode.CHUNK_FAILED]
    assert len(lost) == 1
    assert lost[0].details["start_char"] >= chunks[0].end - 1


# --- regressions from the real run on the 176-page sample ------------------------------------


def test_leaked_subsection_is_folded_into_its_parent() -> None:
    source = _source(
        "ARTICLE 5. Upgrades. 5.12 Costs. x\n5.13 Tax Status. y\nARTICLE 6. Testing. z"
    )
    placed, warnings = _run(
        source,
        _clause("ARTICLE 5. Upgrades.", "ARTICLE 5"),
        _clause("5.13 Tax Status.", "5.13"),  # chunk boundary made it look top-level
        _clause("ARTICLE 6. Testing.", "ARTICLE 6"),
    )
    assert [p.clause.number for p in placed] == ["ARTICLE 5", "ARTICLE 6"]
    assert "5.13 Tax Status." in placed[0].clause.text  # text kept inside the parent
    assert placed[0].clause.subsection_numbers == ["5.13"]
    assert warnings == []


def test_dotted_top_level_numbering_is_not_folded() -> None:
    source = _source("1.1 Scope. Text here.\n1.2 Term. Text here.")
    placed, _ = _run(source, _clause("1.1 Scope. Text", "1.1"), _clause("1.2 Term. Text", "1.2"))
    assert [p.clause.number for p in placed] == ["1.1", "1.2"]


def test_cover_and_toc_before_a_late_preamble_are_reported() -> None:
    source = _source(
        "COVER PAGE " * 30, "TABLE OF CONTENTS ..... 1 " * 20, "THIS AGREEMENT is made"
    )
    _, warnings = _run(source, _clause("THIS AGREEMENT is made", clause_type=ClauseType.PREAMBLE))
    assert _codes(warnings) == [WarningCode.UNCOVERED_TEXT]
    assert (warnings[0].start_page, warnings[0].end_page) == (1, 2)


# --- regressions from the second code review ---------------------------------------------------


def _overlapping_chunks(*pages: str) -> tuple[SourceText, Chunk, Chunk]:
    source = _source(*pages)
    first, second = build_chunks(source, max_chars=len(pages[0]) + len(pages[1]) + 5)[:2]
    assert first.last_page == second.first_page == 2
    return source, first, second


def test_unlocated_exhibit_is_not_mistaken_for_another_exhibit() -> None:
    source, first, second = _overlapping_chunks(
        "1. Scope. " + "x " * 40,
        "EXHIBIT A Price list " + "y " * 40,
        "EXHIBIT B Contacts " + "z " * 40,
    )
    exhibit = ClauseType.EXHIBIT
    outputs = [
        (first, ChunkExtraction(clauses=[_clause("EXHIBIT A Price list", "Exhibit A", exhibit)])),
        (
            second,
            ChunkExtraction(
                clauses=[
                    _clause("EXHIBIT A Price list", "Exhibit A", exhibit),
                    _clause("EXHIBIT B Contact persons", "Exhibit B", exhibit),  # not in source
                ]
            ),
        ),
    ]
    placed = align(source, outputs)
    assert [p.clause.number for p in placed] == ["Exhibit A", "Exhibit B"]
    assert ClauseIssue.ANCHOR_NOT_FOUND in placed[1].clause.issues


def test_short_neighbouring_clauses_from_two_chunks_keep_their_own_text() -> None:
    source, first, second = _overlapping_chunks(
        "11. Notices. " + "x " * 40,
        "12. [Reserved].\n13. [Reserved].\n14. Counterparts. " + "y " * 30,
        "15. Entire Agreement. " + "z " * 40,
    )
    numbers = ("12. [Reserved].", "13. [Reserved].", "14. Counterparts.")
    outputs = [
        (
            first,
            ChunkExtraction(
                clauses=[_clause(n, n.split()[0], confidence=Confidence.MEDIUM) for n in numbers]
            ),
        ),
        (second, ChunkExtraction(clauses=[_clause(n, n.split()[0]) for n in numbers])),
    ]
    placed = align(source, outputs)
    assert [(p.clause.number, p.clause.text[:4]) for p in placed] == [
        ("12.", "12. "),
        ("13.", "13. "),
        ("14.", "14. "),
    ]


def test_subsection_after_an_unlocated_heading_is_not_folded() -> None:
    source = _source("5. Term. Ten years.\nSCHEDULE B\n5.1 Fees. The fees are payable monthly.")
    placed, _ = _run(
        source,
        _clause("5. Term. Ten years.", "5"),
        _clause("SCHEDULE B - Pricing", "Schedule B", ClauseType.EXHIBIT),  # not found
        _clause("5.1 Fees. The fees", "5.1", ClauseType.PAYMENT, Confidence.LOW),
    )
    assert [p.clause.number for p in placed] == ["5", "Schedule B", "5.1"]


def test_folded_low_confidence_subsection_keeps_the_parent_in_review() -> None:
    source = _source("ARTICLE 5. Upgrades. text\n5.13 Tax Status. text\nARTICLE 6. Testing.")
    placed, _ = _run(
        source,
        _clause("ARTICLE 5. Upgrades.", "ARTICLE 5"),
        _clause("5.13 Tax Status.", "5.13", confidence=Confidence.LOW),
        _clause("ARTICLE 6. Testing.", "ARTICLE 6"),
    )
    assert placed[0].clause.subsection_numbers == ["5.13"]
    assert placed[0].clause.needs_review
    assert ClauseIssue.LOW_CONFIDENCE in placed[0].clause.issues


def test_clause_running_over_a_failed_range_is_flagged() -> None:
    source = _source(*[f"{n}. Clause. " + "x " * 20 for n in range(1, 7)])
    chunks = build_chunks(source, max_chars=3 * 60)
    ok, failed = chunks[:1], chunks[1:]
    placed = align(source, [(ok[0], ChunkExtraction(clauses=[_clause("1. Clause.", "1")]))])

    check_coverage(placed, source, ok, failed)

    assert ClauseIssue.MAY_CONTAIN_MISSING_CLAUSE in placed[0].clause.issues
    assert placed[0].clause.needs_review
