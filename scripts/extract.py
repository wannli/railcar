"""
Versioned text extraction for UN PDF documents.

The EXTRACT_VERSION is embedded in every output file's YAML front matter.
Bump this version whenever the extraction or cleanup logic changes, so
we can identify which files need re-processing.
"""

import re
from datetime import datetime, timezone

import fitz  # PyMuPDF

EXTRACT_VERSION = "1.3.0"

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

# Matches a footnote definition line: starts with digit(s), space, then text
_RE_FOOTNOTE_DEF = re.compile(r"^\d+\s+\S")

# Captures footnote number and text separately
_RE_FOOTNOTE_DEF_PARTS = re.compile(r"^(\d+)\s+(.*)")

# Matches a UN document symbol in a page header line
_RE_PAGE_HEADER = re.compile(r"[A-Z]/RES/\d+/\d+")


def get_version() -> str:
    return EXTRACT_VERSION


def _format_footnote_defs(text: str) -> str:
    """Convert footnote definitions to GitHub markdown format.

    Transforms ``1 See resolution 169 (II).`` into
    ``[^1]: See resolution 169 (II).``.  Continuation lines of multi-line
    footnotes are indented with four spaces so GitHub treats them as part of
    the same footnote.
    """
    lines = text.split("\n")
    result: list[str] = []
    in_footnote = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            result.append("")
            in_footnote = False
            continue
        m = _RE_FOOTNOTE_DEF_PARTS.match(stripped)
        if m:
            result.append(f"[^{m.group(1)}]: {m.group(2)}")
            in_footnote = True
        elif in_footnote:
            result.append(f"    {stripped}")
        else:
            result.append(stripped)
    return "\n".join(result)


def _collect_footnote_nums(text: str) -> set[str]:
    """Extract all footnote numbers from a block of footnote definitions."""
    nums: set[str] = set()
    for line in text.split("\n"):
        m = _RE_FOOTNOTE_DEF_PARTS.match(line.strip())
        if m:
            nums.add(m.group(1))
    return nums


def _convert_footnote_refs(body: str, footnote_nums: set[str]) -> str:
    """Convert inline footnote references to GitHub markdown format.

    Transforms ``word1`` into ``word[^1]`` where ``1`` is a known footnote
    number (a letter immediately followed by digits with no space).
    """
    if not footnote_nums:
        return body

    def _replace_ref(m: re.Match) -> str:
        num = m.group(2)
        if num in footnote_nums:
            return f"{m.group(1)}[^{num}]"
        return m.group(0)

    return re.sub(r"([a-zA-Z])(\d+)(?=[\s,;.!?\)\]]|$)", _replace_ref, body)


def clean_text(text: str) -> str:
    """Re-apply the cleaning pipeline to already-extracted text.

    Use this when the extraction logic has changed and existing documents
    need to be reprocessed without re-downloading their PDFs.  Header
    detection is skipped because page boundaries are no longer available.
    Inline footnote blocks are relocated to the end of the document.
    """
    body, footnotes = _relocate_inline_footnotes(text)
    cleaned = _clean_text(body, header_lines=set())
    if footnotes:
        footnote_nums = _collect_footnote_nums(footnotes)
        cleaned = _convert_footnote_refs(cleaned, footnote_nums)
        footnotes = _format_footnote_defs(footnotes)
        return cleaned + "\n\n---\n\n" + footnotes
    return cleaned


RAW_PAGE_SEP = "\f"
"""Form-feed character used to separate pages in .raw.txt files."""


def extract_text(pdf_bytes: bytes) -> tuple[str, str]:
    """Extract text from PDF bytes using PyMuPDF.

    Returns ``(cleaned_text, raw_text)`` where *cleaned_text* is the final
    markdown and *raw_text* is the original per-page extraction joined by
    form-feed characters (``\\f``).  Save *raw_text* to a ``.raw.txt`` file
    so that future regeneration can start from the unprocessed source.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = []
    for page in doc:
        text = page.get_text("text")
        if text.strip():
            pages.append(text.strip())
    doc.close()

    raw_text = RAW_PAGE_SEP.join(pages)
    cleaned = _extract_from_pages(pages)
    return cleaned, raw_text


def extract_from_raw(raw_text: str) -> str:
    """Run the full extraction pipeline on raw page text.

    *raw_text* is the original per-page PDF extraction joined by form-feed
    characters, as produced by :func:`extract_text` and stored in ``.raw.txt``
    files.  This allows regeneration to start from the unprocessed source so
    that every cleaning step (including footnote-reference conversion) works
    correctly.
    """
    pages = raw_text.split(RAW_PAGE_SEP)
    return _extract_from_pages(pages)


def _extract_from_pages(pages: list[str]) -> str:
    """Shared implementation: clean a list of raw page strings."""
    # Separate footnotes from body text on each page
    body_parts = []
    all_footnotes = []
    for page_text in pages:
        body, footnotes = _split_page_footnotes(page_text)
        body_parts.append(body)
        if footnotes:
            all_footnotes.append(footnotes)

    raw = "\n\n".join(body_parts)
    text = _clean_text(raw, _detect_header_lines(body_parts))

    # Append collected footnotes at the end
    if all_footnotes:
        footnote_text = "\n\n".join(all_footnotes)
        footnote_nums = _collect_footnote_nums(footnote_text)
        text = _convert_footnote_refs(text, footnote_nums)
        footnote_text = _format_footnote_defs(footnote_text)
        text = text + "\n\n---\n\n" + footnote_text

    return text.strip()


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


def _split_page_footnotes(page_text: str) -> tuple[str, str]:
    """Split a single page's text into (body, footnotes) at the footnote separator.

    Returns (body_text, footnotes_text).  footnotes_text is empty if no
    separator was found on the page.
    """
    lines = page_text.split("\n")
    for i, line in enumerate(lines):
        if _RE_FOOTNOTE_SEP.match(line.strip()):
            body = "\n".join(lines[:i]).strip()
            footnotes = "\n".join(lines[i + 1 :]).strip()
            return body, footnotes
    return page_text, ""


def _relocate_inline_footnotes(text: str) -> tuple[str, str]:
    """Extract inline footnote blocks from already-processed text.

    Scans for ``---`` separators (standalone or joined to the end of a line)
    followed by footnote definitions.  Returns ``(body, footnotes)`` where
    *body* has the footnote blocks removed and *footnotes* is the collected
    footnote text ready to be appended at the end.
    """
    lines = text.split("\n")
    body_lines: list[str] = []
    footnote_defs: list[str] = []
    i = 0

    while i < len(lines):
        stripped = lines[i].strip()

        is_standalone_sep = stripped == "---"
        is_joined_sep = not is_standalone_sep and stripped.endswith(" ---")

        if is_standalone_sep or is_joined_sep:
            # Look ahead past blank lines for footnote definitions
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1

            if j < len(lines) and _RE_FOOTNOTE_DEF.match(lines[j].strip()):
                # Found a footnote block
                if is_joined_sep:
                    body_lines.append(stripped[:-4].rstrip())

                # Collect lines until a page header or end of text
                fn_block: list[str] = []
                while j < len(lines):
                    fn_line = lines[j].strip()
                    if not fn_line:
                        j += 1
                        continue
                    if (
                        _RE_PAGE_HEADER.search(fn_line)
                        and not _RE_FOOTNOTE_DEF.match(fn_line)
                    ):
                        break
                    fn_block.append(fn_line)
                    j += 1

                # Parse block into individual footnote definitions
                for fn_line in fn_block:
                    if _RE_FOOTNOTE_DEF.match(fn_line):
                        footnote_defs.append(fn_line)
                    elif footnote_defs:
                        # Continuation of previous multi-line footnote
                        footnote_defs[-1] += " " + fn_line

                # Skip page header line if present
                if j < len(lines) and _RE_PAGE_HEADER.search(
                    lines[j].strip()
                ):
                    j += 1

                # For joined separators, skip blank lines so the
                # continuation text is adjacent for paragraph joining.
                if is_joined_sep:
                    while j < len(lines) and not lines[j].strip():
                        j += 1

                i = j
                continue

        body_lines.append(lines[i])
        i += 1

    body = "\n".join(body_lines)
    footnotes = "\n\n".join(footnote_defs)
    return body, footnotes


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
    # Never join across footnote separators
    if prev == "---" or curr == "---":
        return False
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
    """Parse a markdown file with YAML front matter into (metadata_dict, body_text).

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
