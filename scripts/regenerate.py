"""
Re-generate document files whose extract_version is older than the current version.

Reads each existing .txt file, parses the YAML front matter and body text,
then re-formats the output using the current schema version. The original
extracted text is preserved — no PDF re-download is needed.

This ensures all files stay in sync with the latest schema whenever
EXTRACT_VERSION is bumped in extract.py.
"""

import logging
from pathlib import Path

from extract import EXTRACT_VERSION, format_output, parse_document

log = logging.getLogger("railcar.regenerate")

DOCS_DIR = Path(__file__).resolve().parent.parent / "documents"


def needs_regeneration(file_version: str) -> bool:
    """Return True if file_version is older than the current EXTRACT_VERSION."""
    return file_version != EXTRACT_VERSION


def regenerate_file(path: Path) -> bool:
    """Re-generate a single document file if its schema version is outdated.

    Returns True if the file was regenerated, False if skipped.
    """
    content = path.read_text(encoding="utf-8")
    metadata, body = parse_document(content)

    file_version = metadata.get("extract_version", "")
    if not needs_regeneration(file_version):
        return False

    log.info("Regenerating %s (version %s -> %s)", path.name, file_version, EXTRACT_VERSION)

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
    for txt_file in sorted(DOCS_DIR.rglob("*.txt")):
        try:
            if regenerate_file(txt_file):
                regenerated += 1
        except Exception as e:
            log.error("Failed to regenerate %s: %s", txt_file, e)

    if regenerated:
        log.info("Regenerated %d file(s) to extract version %s", regenerated, EXTRACT_VERSION)
    else:
        log.info("All files already at extract version %s", EXTRACT_VERSION)

    return regenerated
