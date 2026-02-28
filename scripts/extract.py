"""
Versioned text extraction for UN PDF documents.

The EXTRACT_VERSION is embedded in every output file's YAML front matter.
Bump this version whenever the extraction or cleanup logic changes, so
we can identify which files need re-processing.
"""

from datetime import datetime, timezone

import fitz  # PyMuPDF

EXTRACT_VERSION = "1.0.0"


def get_version() -> str:
    return EXTRACT_VERSION


def extract_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes using PyMuPDF.

    Returns cleaned plaintext with pages separated by double newlines.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = []
    for page in doc:
        text = page.get_text("text")
        if text.strip():
            pages.append(text.strip())
    doc.close()
    return "\n\n".join(pages)


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
