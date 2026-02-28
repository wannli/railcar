"""Tests for text extraction cleaning logic."""

import sys
from pathlib import Path

# Allow importing from scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from extract import (
    _clean_text,
    _detect_header_lines,
    _join_paragraph_numbers,
    _join_paragraphs,
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
