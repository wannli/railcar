"""
Re-generate document files whose extract_version is older than the current version.

When a ``.raw.txt`` file exists (the original per-page PDF extraction), the full
pipeline is re-run from scratch so that every cleaning step—including footnote
reference conversion—works correctly.  When no raw file is available (legacy
documents), the already-cleaned body text is re-processed as a best-effort
fallback.

This ensures all files are reprocessed with the latest extraction logic
whenever EXTRACT_VERSION is bumped in extract.py.
"""

import logging
from pathlib import Path

from extract import EXTRACT_VERSION, clean_text, extract_from_raw, format_output, parse_document

log = logging.getLogger("railcar.regenerate")

DOCS_DIR = Path(__file__).resolve().parent.parent / "documents"
RAW_DIR = DOCS_DIR / ".raw"


def _raw_path_for(md_path: Path) -> Path:
    """Return the .raw.txt path corresponding to a document .md path."""
    # md_path:  documents/ga-res-80/A_RES_80_1.md
    # raw_path: documents/.raw/ga-res-80/A_RES_80_1.raw.txt
    rel = md_path.relative_to(DOCS_DIR)
    return RAW_DIR / rel.parent / f"{rel.stem}.raw.txt"


def needs_regeneration(file_version: str) -> bool:
    """Return True if file_version is older than the current EXTRACT_VERSION."""
    return file_version != EXTRACT_VERSION


def regenerate_file(path: Path) -> bool:
    """Re-generate a single document file if its schema version is outdated.

    Returns True if the file was regenerated, False if skipped.
    """
    content = path.read_text(encoding="utf-8")
    metadata, body = parse_document(content)

    if "symbol" not in metadata:
        return False

    file_version = metadata.get("extract_version", "")
    if not needs_regeneration(file_version):
        return False

    raw_file = _raw_path_for(path)
    if raw_file.exists():
        log.info(
            "Regenerating %s from raw source (version %s -> %s)",
            path.name, file_version, EXTRACT_VERSION,
        )
        raw_text = raw_file.read_text(encoding="utf-8")
        body = extract_from_raw(raw_text)
    else:
        log.info(
            "Regenerating %s from cleaned body (no raw file) (version %s -> %s)",
            path.name, file_version, EXTRACT_VERSION,
        )
        body = clean_text(body)

    output = format_output(body, metadata)
    path.write_text(output, encoding="utf-8")
    return True


def regenerate_all() -> int:
    """Scan all document directories and regenerate files with outdated versions.

    Returns the number of files regenerated.
    """
    if not DOCS_DIR.exists():
        log.info("No documents directory found, nothing to regenerate")
        return 0

    regenerated = 0
    for md_file in sorted(DOCS_DIR.rglob("*.md")):
        try:
            if regenerate_file(md_file):
                regenerated += 1
        except Exception as e:
            log.error("Failed to regenerate %s: %s", md_file, e)

    if regenerated:
        log.info("Regenerated %d file(s) to extract version %s", regenerated, EXTRACT_VERSION)
    else:
        log.info("All files already at extract version %s", EXTRACT_VERSION)

    return regenerated
