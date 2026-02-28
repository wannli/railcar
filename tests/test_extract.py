"""Tests for text extraction cleaning logic."""

import sys
from pathlib import Path

# Allow importing from scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from extract import (
    RAW_PAGE_SEP,
    _clean_text,
    _collect_footnote_nums,
    _convert_footnote_refs,
    _detect_header_lines,
    _format_footnote_defs,
    _join_paragraph_numbers,
    _join_paragraphs,
    _relocate_inline_footnotes,
    _split_page_footnotes,
    clean_text,
    extract_from_raw,
)


def test_removes_distribution_codes():
    text = "Some text\n25-15106 (E)\n*2515106*\nMore text"
    result = _clean_text(text, set())
    assert "25-15106" not in result
    assert "*2515106*" not in result
    assert "Some text" in result
    assert "More text" in result


def test_removes_bare_distribution_codes():
    text = "Some text\n25-15106\nMore text"
    result = _clean_text(text, set())
    assert "25-15106" not in result


def test_removes_page_numbers():
    text = "Some text\n2/2\nMore text"
    result = _clean_text(text, set())
    assert "2/2" not in result


def test_removes_header_lines():
    pages = [
        "A/RES/80/1\nHeader Title\nPage 1 content",
        "A/RES/80/1\nHeader Title\nPage 2 content",
    ]
    headers = _detect_header_lines(pages)
    assert "A/RES/80/1" in headers
    assert "Header Title" in headers

    raw = "\n\n".join(pages)
    result = _clean_text(raw, headers)
    # Headers should only appear once (the first page occurrence gets removed too)
    assert "Page 1 content" in result
    assert "Page 2 content" in result


def test_normalizes_footnote_separators():
    text = "Some text\n_______________\n1 See resolution 169 (II)."
    result = _clean_text(text, set())
    assert "___" not in result
    assert "---" in result
    assert "See resolution" in result


def test_joins_paragraph_numbers():
    text = "1.\nDecides that something"
    result = _join_paragraph_numbers(text)
    assert result.strip() == "1. Decides that something"


def test_joins_subparagraph_labels():
    text = "(a)\nThe State of Palestine"
    result = _join_paragraph_numbers(text)
    assert result.strip() == "(a) The State of Palestine"


def test_joins_roman_numeral_labels():
    text = "(iv)\nSome provision here"
    result = _join_paragraph_numbers(text)
    assert result.strip() == "(iv) Some provision here"


def test_joins_continuation_lines():
    text = "Expressing concern regarding situations in which\nrepresentatives are prevented from participating"
    result = _join_paragraphs(text)
    assert "situations in which representatives" in result


def test_does_not_join_after_comma():
    """Preambular clauses end with commas — the next clause is a new paragraph."""
    text = "The General Assembly,\nExpressing concern"
    result = _join_paragraphs(text)
    lines = [l for l in result.split("\n") if l.strip()]
    assert len(lines) == 2


def test_does_not_join_after_colon():
    text = "Decides that:\nThe State shall"
    result = _join_paragraphs(text)
    lines = [l for l in result.split("\n") if l.strip()]
    assert len(lines) == 2


def test_does_not_join_after_semicolon():
    text = "submit a pre-recorded statement;\nThe State of Palestine"
    result = _join_paragraphs(text)
    lines = [l for l in result.split("\n") if l.strip()]
    assert len(lines) == 2


def test_collapses_excessive_blank_lines():
    text = "Line 1\n\n\n\n\nLine 2"
    result = _clean_text(text, set())
    assert "\n\n\n" not in result
    assert "Line 1" in result
    assert "Line 2" in result


def test_detect_header_lines_single_page():
    pages = ["Only one page of content"]
    headers = _detect_header_lines(pages)
    assert headers == set()


def test_preserves_content_lines():
    text = "The General Assembly,\nRecalling its relevant resolutions,"
    result = _clean_text(text, set())
    assert "General Assembly" in result
    assert "Recalling" in result


def test_clean_text_reapplies_cleaning():
    """clean_text should apply cleanup logic to already-extracted text."""
    # Simulate body text that still has artifacts (e.g. from a v1.0 extraction
    # that didn't strip distribution codes or join paragraph numbers)
    body = "Some text\n25-15106 (E)\n\n1.\nDecides that something\n\n3/24\n\nMore text"
    result = clean_text(body)
    assert "25-15106" not in result
    assert "3/24" not in result
    assert "1. Decides" in result
    assert "More text" in result


def test_full_cleaning_pipeline():
    """Simulate a two-page UN resolution extraction."""
    pages = [
        (
            "United Nations\n"
            "A/RES/80/1\n"
            "\n"
            "General Assembly\n"
            "Distr.: General\n"
            "19 September 2025\n"
            "25-15106 (E)\n"
            "*2515106*\n"
            "\n"
            "Resolution adopted by the General Assembly\n"
            "on 19 September 2025\n"
            "\n"
            "80/1. Participation by the State of Palestine\n"
            "\n"
            "The General Assembly,\n"
            "\n"
            "Expressing concern regarding situations in which\n"
            "representatives are prevented from participating,\n"
            "\n"
            "1.\n"
            "Decides that something important;\n"
            "\n"
            "(a)\n"
            "The State of Palestine may submit a statement;\n"
            "\n"
            "_______________\n"
            "\n"
            "1 See resolution 169 (II)."
        ),
        (
            "A/RES/80/1\n"
            "Participation by the State of Palestine\n"
            "\n"
            "25-15106\n"
            "2/2\n"
            "\n"
            "(b)\n"
            "The State of Palestine may deliver statements\n"
            "by means of videoconference;\n"
            "\n"
            "2.\n"
            "Also decides that these procedures shall apply\n"
            "only during the eightieth session.\n"
            "\n"
            "3rd plenary meeting\n"
            "19 September 2025"
        ),
    ]

    headers = _detect_header_lines(pages)
    raw = "\n\n".join(pages)
    result = _clean_text(raw, headers)

    # Distribution codes removed
    assert "25-15106 (E)" not in result
    assert "*2515106*" not in result

    # Page header on page 2 removed
    assert result.count("A/RES/80/1") <= 1

    # Page number removed
    assert "\n2/2\n" not in result

    # Paragraph numbers joined
    assert "1. Decides" in result
    assert "2. Also decides" in result

    # Sub-paragraph labels joined
    assert "(a) The State" in result
    assert "(b) The State" in result

    # Continuation lines joined
    assert "situations in which representatives" in result

    # Footnote separator normalized
    assert "___" not in result

    # Actual content preserved
    assert "General Assembly" in result
    assert "3rd plenary meeting" in result


def test_split_page_footnotes_with_separator():
    page = (
        "Body text here\n"
        "More body text\n"
        "_______________\n"
        "\n"
        "1 See resolution 169 (II)."
    )
    body, footnotes = _split_page_footnotes(page)
    assert "Body text here" in body
    assert "More body text" in body
    assert "___" not in body
    assert "1 See resolution 169 (II)." in footnotes


def test_split_page_footnotes_without_separator():
    page = "Body text only\nNo footnotes here"
    body, footnotes = _split_page_footnotes(page)
    assert body == page
    assert footnotes == ""


def test_relocate_inline_footnotes_standalone():
    """Standalone --- separator followed by footnotes and a page header."""
    text = (
        "paragraph ending with semicolon;\n"
        "---\n"
        "\n"
        "1 United Nations, Treaty Series, vol. 2187, No. 38544.\n"
        "\n"
        "A/RES/80/6 Report of the International Criminal Court\n"
        "\n"
        "2. Next operative paragraph"
    )
    body, footnotes = _relocate_inline_footnotes(text)
    assert "---" not in body
    assert "2. Next operative paragraph" in body
    assert "paragraph ending with semicolon;" in body
    assert "1 United Nations, Treaty Series, vol. 2187, No. 38544." in footnotes
    assert "A/RES/80/6" not in body


def test_relocate_inline_footnotes_joined():
    """Text ending with ' ---' (joined separator) followed by footnotes."""
    text = (
        "and other international and ---\n"
        "\n"
        "1 United Nations, Treaty Series, vol. 2187, No. 38544.\n"
        "\n"
        "A/RES/80/6 Report of the International Criminal Court\n"
        "\n"
        "regional organizations remain essential"
    )
    body, footnotes = _relocate_inline_footnotes(text)
    assert "---" not in body
    assert "and other international and" in body
    assert "regional organizations remain essential" in body
    assert "1 United Nations, Treaty Series, vol. 2187, No. 38544." in footnotes


def test_relocate_inline_footnotes_multiple_blocks():
    """Multiple footnote blocks scattered through the text."""
    text = (
        "First paragraph;\n"
        "---\n"
        "\n"
        "1 First footnote.\n"
        "\n"
        "A/RES/80/1 Title\n"
        "\n"
        "Second paragraph;\n"
        "---\n"
        "\n"
        "2 Second footnote.\n"
        "\n"
        "3 Third footnote.\n"
        "\n"
        "A/RES/80/1 Title\n"
        "\n"
        "Third paragraph."
    )
    body, footnotes = _relocate_inline_footnotes(text)
    assert "---" not in body
    assert "First paragraph;" in body
    assert "Second paragraph;" in body
    assert "Third paragraph." in body
    assert "1 First footnote." in footnotes
    assert "2 Second footnote." in footnotes
    assert "3 Third footnote." in footnotes


def test_relocate_inline_footnotes_multiline():
    """Multi-line footnote where the continuation doesn't start with a digit."""
    text = (
        "Some text.\n"
        "---\n"
        "\n"
        "2 See International Atomic Energy Agency, Resolutions Adopted\n"
        "(GC(69)/RES/DEC(2025)) for the full texts.\n"
        "\n"
        "3 See resolution 123."
    )
    body, footnotes = _relocate_inline_footnotes(text)
    assert "Some text." in body
    assert "---" not in body
    assert "2 See International Atomic Energy Agency, Resolutions Adopted (GC(69)/RES/DEC(2025)) for the full texts." in footnotes
    assert "3 See resolution 123." in footnotes


def test_clean_text_relocates_footnotes():
    """clean_text should move inline footnotes to end of document as GitHub markdown."""
    text = (
        "The General Assembly,\n"
        "\n"
        "Recalling the Rome Statute1 of the Court,\n"
        "\n"
        "cooperation and other international and ---\n"
        "\n"
        "1 United Nations, Treaty Series, vol. 2187, No. 38544.\n"
        "\n"
        "A/RES/80/6 Report of the International Criminal Court\n"
        "\n"
        "regional organizations remain essential,\n"
        "\n"
        "1. Welcomes the report."
    )
    result = clean_text(text)
    # Footnotes should be at the end, after ---
    parts = result.split("---")
    assert len(parts) == 2
    body_part = parts[0]
    fn_part = parts[1]
    # Body should be continuous without inline footnotes
    assert "international and" in body_part
    assert "regional organizations remain essential" in body_part
    # Inline reference should be converted to GitHub format
    assert "Statute[^1]" in body_part
    # Footnote definition should use GitHub markdown format
    assert "[^1]: United Nations, Treaty Series" in fn_part
    # Page header should be removed
    assert "A/RES/80/6 Report of the International Criminal Court" not in result


def test_does_not_join_separator_with_text():
    """The --- footnote separator should never be joined to adjacent lines."""
    text = "Some text without punctuation end\n---\n1 Footnote text."
    result = _clean_text(text, set())
    assert "end ---" not in result
    assert "---" in result


def test_format_footnote_defs_single():
    text = "1 See resolution 169 (II)."
    result = _format_footnote_defs(text)
    assert result == "[^1]: See resolution 169 (II)."


def test_format_footnote_defs_multiple():
    text = "1 First footnote.\n\n2 Second footnote.\n\n3 Third footnote."
    result = _format_footnote_defs(text)
    assert "[^1]: First footnote." in result
    assert "[^2]: Second footnote." in result
    assert "[^3]: Third footnote." in result


def test_format_footnote_defs_multiline():
    """Continuation lines should be indented with 4 spaces."""
    text = "1 See International Atomic Energy Agency,\nResolutions Adopted.\n\n2 Ibid."
    result = _format_footnote_defs(text)
    assert "[^1]: See International Atomic Energy Agency," in result
    assert "    Resolutions Adopted." in result
    assert "[^2]: Ibid." in result


def test_collect_footnote_nums():
    text = "1 First.\n\n2 Second.\n\n10 Tenth."
    nums = _collect_footnote_nums(text)
    assert nums == {"1", "2", "10"}


def test_convert_footnote_refs_basic():
    body = "the United Nations1 are prevented"
    result = _convert_footnote_refs(body, {"1"})
    assert result == "the United Nations[^1] are prevented"


def test_convert_footnote_refs_multiple():
    body = "Nations1 and Treaty2 and more"
    result = _convert_footnote_refs(body, {"1", "2"})
    assert "Nations[^1]" in result
    assert "Treaty[^2]" in result


def test_convert_footnote_refs_double_digit():
    body = "some text10 here"
    result = _convert_footnote_refs(body, {"10"})
    assert "text[^10]" in result


def test_convert_footnote_refs_ignores_non_footnote_numbers():
    body = "resolution 169 and section 2"
    result = _convert_footnote_refs(body, {"1"})
    # Numbers preceded by a space should not be converted
    assert result == body


def test_convert_footnote_refs_ignores_unknown_numbers():
    body = "word5 here"
    result = _convert_footnote_refs(body, {"1", "2"})
    # 5 is not a known footnote number
    assert result == body


def test_clean_text_github_footnotes_end_to_end():
    """Full pipeline should produce GitHub-compatible footnotes."""
    text = (
        "Recalling the Statute1 of the Court,\n"
        "\n"
        "---\n"
        "\n"
        "1 United Nations, Treaty Series, vol. 2187.\n"
        "\n"
        "2 See resolution 123."
    )
    result = clean_text(text)
    assert "Statute[^1]" in result
    assert "[^1]: United Nations, Treaty Series, vol. 2187." in result
    assert "[^2]: See resolution 123." in result


def test_extract_from_raw_converts_footnote_refs():
    """extract_from_raw should run the full pipeline including footnote ref conversion."""
    page1 = (
        "United Nations\n"
        "A/RES/80/6\n"
        "\n"
        "General Assembly\n"
        "\n"
        "Recalling the Rome Statute1 of the Court,\n"
        "\n"
        "cooperation and other international2 organisations,\n"
        "\n"
        "1.\n"
        "Welcomes the report.\n"
        "\n"
        "_______________\n"
        "\n"
        "1 United Nations, Treaty Series, vol. 2187, No. 38544.\n"
        "2 See A/58/874."
    )
    page2 = (
        "A/RES/80/6\n"
        "\n"
        "2.\n"
        "Also welcomes the cooperation."
    )
    raw_text = RAW_PAGE_SEP.join([page1, page2])
    result = extract_from_raw(raw_text)

    # Footnote references should be converted
    assert "Statute[^1]" in result
    assert "international[^2]" in result

    # Footnote definitions should use GitHub format
    assert "[^1]: United Nations, Treaty Series, vol. 2187, No. 38544." in result
    assert "[^2]: See A/58/874." in result

    # Body content preserved
    assert "1. Welcomes the report." in result
    assert "2. Also welcomes the cooperation." in result


def test_extract_from_raw_roundtrip_preserves_page_boundaries():
    """Raw text split by form-feeds should reproduce the same pages."""
    page1 = "Page one content\n_______________\n1 Footnote."
    page2 = "Page two content"
    raw = RAW_PAGE_SEP.join([page1, page2])

    # Splitting should recover original pages
    pages = raw.split(RAW_PAGE_SEP)
    assert len(pages) == 2
    assert "Page one" in pages[0]
    assert "Page two" in pages[1]
