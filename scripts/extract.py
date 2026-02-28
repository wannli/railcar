"""
Versioned text extraction for UN PDF documents.

The EXTRACT_VERSION is embedded in every output file's YAML front matter.
Bump this version whenever the extraction or cleanup logic changes, so
we can identify which files need re-processing.
"""

import re
from datetime import datetime, timezone

import fitz  # PyMuPDF

EXTRACT_VERSION = "1.1.0"

# Matches UN distribution codes like "25-15106 (E)", "25-15106", or "*2515106*"
_RE_DIST_CODE = re.compile(r"^\d{2}-\d{5}(\s*\([A-Z]\))?\s*$")
_RE_DIST_STAR = re.compile(r"^\*\d+\*\s*$")

# Matches page numbers like "2/2", "3/24"
_RE_PAGE_NUM = re.compile(r"^\d+/\d+\s*$")

# Matches footnote separator lines (sequences of underscores)
_RE_FOOTNOTE_SEP = re.compile(r"^[_]{4,}\s*$")

# Matches standalone paragraph numbers like "1." or "23." on their own line
_RE_PARA_NUM = re.compile(r"^(\d+)\.\s*$")

# Matches standalone sub-paragraph labels like "(a)" or "(iv)" on their own line
_RE_SUBPARA = re.compile(r"^(\([a-z]+\)|\([ivxlc]+\))\s*$")


def get_version() -> str:
    return EXTRACT_VERSION


def extract_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes using PyMuPDF.

    Returns cleaned plaintext with headers/footers removed, paragraphs joined,
    and common PDF artifacts cleaned up.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = []
    for page in doc:
        text = page.get_text("text")
        if text.strip():
            pages.append(text.strip())
    doc.close()

    raw = "\n\n".join(pages)
    return _clean_text(raw, _detect_header_lines(pages))


def _detect_header_lines(pages: list[str]) -> set[str]:
    """Detect repeated header/footer lines across pages.

    Lines appearing on more than one page (after stripping) are likely
    running headers or footers.
    """
    if len(pages) < 2:
        return set()

    line_page_count: dict[str, int] = {}
    for page_text in pages:
        seen_on_page: set[str] = set()
        for line in page_text.splitlines():
            stripped = line.strip()
            if stripped and stripped not in seen_on_page:
                seen_on_page.add(stripped)
                line_page_count[stripped] = line_page_count.get(stripped, 0) + 1

    return {line for line, count in line_page_count.items() if count > 1}


def _clean_text(text: str, header_lines: set[str]) -> str:
    """Apply all cleaning passes to extracted text."""
    lines = text.splitlines()
    cleaned: list[str] = []

    for line in lines:
        stripped = line.strip()

        # Remove distribution codes
        if _RE_DIST_CODE.match(stripped) or _RE_DIST_STAR.match(stripped):
            continue

        # Remove page numbers
        if _RE_PAGE_NUM.match(stripped):
            continue

        # Remove repeated header/footer lines
        if stripped in header_lines and _is_likely_header(stripped):
            continue

        # Normalize footnote separators
        if _RE_FOOTNOTE_SEP.match(stripped):
            cleaned.append("---")
            continue

        cleaned.append(stripped)

    text = "\n".join(cleaned)

    # Join standalone paragraph numbers with their following text
    text = _join_paragraph_numbers(text)

    # Join broken paragraph lines
    text = _join_paragraphs(text)

    # Collapse runs of 3+ blank lines down to 2
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def _is_likely_header(line: str) -> bool:
    """Heuristic: a repeated line is a header/footer if it looks like a
    document symbol, short title, or distribution code."""
    # Document symbols like A/RES/80/1
    if re.match(r"^[A-Z]/", line):
        return True
    # Short lines (< 80 chars) that appear on multiple pages are likely headers
    if len(line) < 80:
        return True
    return False


def _join_paragraph_numbers(text: str) -> str:
    """Join standalone paragraph numbers and sub-paragraph labels with the
    following line.  e.g. '1.\\nDecides that...' -> '1. Decides that...'"""
    lines = text.split("\n")
    result: list[str] = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if i + 1 < len(lines) and (
            _RE_PARA_NUM.match(stripped) or _RE_SUBPARA.match(stripped)
        ):
            next_line = lines[i + 1].strip()
            if next_line:
                result.append(f"{stripped} {next_line}")
                i += 2
                continue
        result.append(lines[i])
        i += 1
    return "\n".join(result)


def _join_paragraphs(text: str) -> str:
    """Join lines that are continuations of the same paragraph.

    A line is considered a continuation if:
    - The previous line is non-empty and does not end with a paragraph break
      signal (colon, semicolon, period followed by a blank line)
    - The current line is non-empty and starts with a lowercase letter
    """
    lines = text.split("\n")
    result: list[str] = []

    for line in lines:
        stripped = line.strip()
        if (
            result
            and stripped
            and result[-1]
            and not result[-1].endswith(":")
            and _continues_previous(result[-1], stripped)
        ):
            result[-1] = result[-1] + " " + stripped
        else:
            result.append(stripped if stripped else "")

    return "\n".join(result)


def _continues_previous(prev: str, curr: str) -> bool:
    """Determine whether curr is a continuation of prev."""
    # Current line starts with lowercase -> continuation
    if curr[0].islower():
        return True
    # Previous line ends mid-sentence (no terminal punctuation) and current
    # starts with uppercase could be a proper noun continuation
    if prev and prev[-1] not in ".;:,!?\"'" and not curr.startswith("("):
        return True
    return False


def format_output(text: str, metadata: dict) -> str:
    """Wrap extracted text with YAML front matter containing metadata and version info."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "---",
        f"symbol: {metadata.get('symbol', '')}",
        f"record_id: \"{metadata.get('record_id', '')}\"",
        f"title: \"{_escape_yaml(metadata.get('title', ''))}\"",
        f"date: \"{metadata.get('date', '')}\"",
        f"language: {metadata.get('language', 'EN')}",
        f"source_pdf: {metadata.get('source_pdf', '')}",
        f"extract_version: \"{EXTRACT_VERSION}\"",
        f"extracted_at: \"{now}\"",
        "---",
        "",
        text,
    ]
    return "\n".join(lines)


def parse_document(content: str) -> tuple[dict, str]:
    """Parse a txt file with YAML front matter into (metadata_dict, body_text).

    Expects the file to start with '---' delimiters around YAML front matter,
    followed by the extracted text body.
    """
    if not content.startswith("---"):
        return {}, content

    # Find the closing '---'
    end = content.index("---", 3)
    front_matter = content[3:end].strip()
    body = content[end + 3:].lstrip("\n")

    metadata = {}
    for line in front_matter.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip().strip('"')
        # Unescape YAML double-quoted values
        value = value.replace('\\"', '"').replace("\\\\", "\\")
        metadata[key.strip()] = value

    return metadata, body


def _escape_yaml(s: str) -> str:
    """Escape characters that would break YAML double-quoted strings."""
    return s.replace("\\", "\\\\").replace('"', '\\"')
