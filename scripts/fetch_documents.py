#!/usr/bin/env python3
"""
Railcar - UN Document Fetch Pipeline

Discovers UN documents by pattern, downloads English PDFs, converts to
plaintext using versioned extraction logic, and saves to the documents/ directory.

Environment variables:
    PATTERN_ID   - Specific pattern ID to run (blank = all enabled)
    MAX_DOCS     - Max documents to attempt per pattern per run (default 10)
"""

import json
import logging
import os
import sys
import time
from datetime import date
from pathlib import Path

import requests
from lxml import etree

from extract import extract_text, format_output, get_version
from regenerate import regenerate_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("railcar")

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "patterns.json"
STATE_PATH = ROOT / "state" / "progress.json"
DOCS_DIR = ROOT / "documents"

MARC_NS = {"marc": "http://www.loc.gov/MARC21/slim"}
SEARCH_BASE = "https://digitallibrary.un.org/search"
UNDOCS_BASE = "https://undocs.org/en"

SESSION = requests.Session()


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_state() -> dict:
    if STATE_PATH.exists():
        with open(STATE_PATH) as f:
            content = f.read().strip()
            return json.loads(content) if content else {}
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def search_document(symbol: str, language: str) -> dict | None:
    """Query the Invenio Search API for a document symbol.

    Returns metadata dict with pdf_url, record_id, title, date or None if not found.
    """
    # Search by document symbol in MARC field 191 subfield a
    params = {
        "p": f'191__a:"{symbol}"',
        "of": "xm",
        "rg": "200",
    }
    try:
        resp = SESSION.get(SEARCH_BASE, params=params, timeout=60)
        resp.raise_for_status()
    except requests.RequestException as e:
        log.error("Search API error for %s: %s", symbol, e)
        return None

    if resp.status_code == 202 or len(resp.content) == 0:
        log.warning("Search API returned empty response for %s (status %d)",
                     symbol, resp.status_code)
        return None

    return _parse_marcxml(resp.content, symbol, language)


def _parse_marcxml(xml_bytes: bytes, symbol: str, language: str) -> dict | None:
    """Parse MARCXML response and extract metadata for the given symbol."""
    try:
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError:
        # Response may have HTML wrapper; try to extract the MARC collection
        try:
            tree = etree.HTML(xml_bytes)
            # Look for the collection element
            collections = tree.xpath("//marc:collection", namespaces=MARC_NS)
            if not collections:
                return None
            root = collections[0]
        except Exception:
            return None

    records = root.findall(".//marc:record", MARC_NS)
    if not records:
        return None

    lang_names = {
        "EN": "English",
        "FR": "Français",
        "ES": "Español",
        "AR": "العربية",
        "ZH": "中文",
        "RU": "Русский",
    }
    target_lang = lang_names.get(language, "English")

    for record in records:
        # Get record ID from controlfield 001
        cf001 = record.find("marc:controlfield[@tag='001']", MARC_NS)
        record_id = cf001.text.strip() if cf001 is not None and cf001.text else ""

        # Get document symbol from field 191
        rec_symbol = _get_subfield(record, "191", "a")
        if rec_symbol and rec_symbol.strip().upper() != symbol.strip().upper():
            continue

        # Get title from field 245
        title = _get_subfield(record, "245", "a") or ""

        # Get date from field 269
        date = _get_subfield(record, "269", "a") or ""

        # Get PDF URL from field 856 matching the target language
        pdf_url = None
        for f856 in record.findall("marc:datafield[@tag='856']", MARC_NS):
            lang_sub = f856.find("marc:subfield[@code='y']", MARC_NS)
            url_sub = f856.find("marc:subfield[@code='u']", MARC_NS)
            if lang_sub is not None and url_sub is not None:
                if lang_sub.text and target_lang.lower() in lang_sub.text.lower():
                    pdf_url = url_sub.text.strip()
                    break

        if pdf_url:
            return {
                "record_id": record_id,
                "symbol": symbol,
                "title": title.strip(),
                "date": date.strip(),
                "source_pdf": pdf_url,
                "language": language,
            }

    return None


def _get_subfield(record, tag: str, code: str) -> str | None:
    """Get the text of a MARC subfield."""
    df = record.find(f"marc:datafield[@tag='{tag}']", MARC_NS)
    if df is None:
        return None
    sf = df.find(f"marc:subfield[@code='{code}']", MARC_NS)
    if sf is None or sf.text is None:
        return None
    return sf.text


def download_pdf(url: str, max_retries: int = 3) -> bytes | None:
    """Download a PDF, returning its bytes. Retries on server errors."""
    for attempt in range(max_retries):
        try:
            resp = SESSION.get(url, timeout=120, stream=True)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as e:
            if attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                log.warning("Download attempt %d failed for %s: %s. Retrying in %ds...",
                            attempt + 1, url, e, wait)
                time.sleep(wait)
            else:
                log.error("Download failed after %d attempts for %s: %s",
                          max_retries, url, e)
                return None
    return None


def fallback_download(symbol: str) -> bytes | None:
    """Try downloading directly from undocs.org as a fallback."""
    url = f"{UNDOCS_BASE}/{symbol}"
    log.info("Trying fallback URL: %s", url)
    try:
        resp = SESSION.get(url, timeout=120, allow_redirects=True)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "pdf" in content_type.lower():
            return resp.content
        # undocs.org may redirect to an HTML page
        return None
    except requests.RequestException as e:
        log.warning("Fallback download failed for %s: %s", symbol, e)
        return None


def sanitize_symbol(symbol: str) -> str:
    """Convert a document symbol to a safe filename component."""
    return symbol.replace("/", "_").replace(" ", "_")


def process_pattern(pattern_cfg: dict, state: dict, settings: dict, max_docs: int) -> dict:
    """Process a single pattern, fetching new documents.

    Returns updated state entry for this pattern.
    """
    pid = pattern_cfg["id"]
    template = pattern_cfg["pattern"]
    start = pattern_cfg.get("start", 1)
    language = settings.get("language", "EN")
    delay = settings.get("request_delay_seconds", 2)
    miss_threshold = settings.get("max_consecutive_misses", 3)

    pat_state = state.get(pid, {
        "last_fetched": start - 1,
        "last_run": "",
        "consecutive_misses": 0,
    })

    docs_processed = 0
    x = pat_state["last_fetched"] + 1
    consecutive_misses = pat_state.get("consecutive_misses", 0)

    out_dir = DOCS_DIR / pid
    out_dir.mkdir(parents=True, exist_ok=True)

    while docs_processed < max_docs and consecutive_misses < miss_threshold:
        symbol = template.replace("{X}", str(x))
        log.info("Processing %s (X=%d)", symbol, x)

        # Check if output already exists
        out_file = out_dir / f"{sanitize_symbol(symbol)}.md"
        if out_file.exists():
            log.info("Already exists: %s, skipping", out_file.name)
            pat_state["last_fetched"] = x
            consecutive_misses = 0
            x += 1
            continue

        # Discover document metadata via Search API
        time.sleep(delay)
        metadata = search_document(symbol, language)

        pdf_bytes = None
        if metadata and metadata.get("source_pdf"):
            log.info("Found via Search API: %s", metadata["source_pdf"])
            time.sleep(delay)
            pdf_bytes = download_pdf(metadata["source_pdf"])

        # Fallback: try undocs.org
        if pdf_bytes is None:
            time.sleep(delay)
            pdf_bytes = fallback_download(symbol)
            if pdf_bytes is not None and metadata is None:
                metadata = {
                    "record_id": "",
                    "symbol": symbol,
                    "title": "",
                    "date": "",
                    "source_pdf": f"{UNDOCS_BASE}/{symbol}",
                    "language": language,
                }

        if pdf_bytes is None:
            log.warning("Document not found: %s", symbol)
            consecutive_misses += 1
            x += 1
            continue

        # Extract text
        try:
            text = extract_text(pdf_bytes)
        except Exception as e:
            log.error("Extraction failed for %s: %s", symbol, e)
            consecutive_misses += 1
            x += 1
            continue

        if not text.strip():
            log.warning("Empty text extracted from %s (possibly scanned image)", symbol)

        # Write output with versioned metadata
        output = format_output(text, metadata)
        out_file.write_text(output, encoding="utf-8")
        log.info("Saved: %s (%d chars)", out_file.name, len(text))

        pat_state["last_fetched"] = x
        consecutive_misses = 0
        docs_processed += 1
        x += 1

    pat_state["last_run"] = date.today().isoformat()
    pat_state["consecutive_misses"] = consecutive_misses

    if consecutive_misses >= miss_threshold:
        log.info("Pattern %s: reached %d consecutive misses, stopping",
                 pid, consecutive_misses)

    log.info("Pattern %s: processed %d documents", pid, docs_processed)
    return pat_state


def main():
    config = load_config()
    state = load_state()
    settings = config.get("settings", {})

    target_pattern = os.environ.get("PATTERN_ID", "").strip()
    max_docs = int(os.environ.get("MAX_DOCS", "10"))

    log.info("Railcar v%s (extract v%s)", "1.0.0", get_version())
    log.info("Max docs per pattern: %d", max_docs)

    # Regenerate any files produced by an older extract version
    regenerate_all()

    patterns = config.get("patterns", [])
    if target_pattern:
        patterns = [p for p in patterns if p["id"] == target_pattern]
        if not patterns:
            log.error("Pattern ID '%s' not found in config", target_pattern)
            sys.exit(1)

    for pat in patterns:
        if not pat.get("enabled", True):
            log.info("Skipping disabled pattern: %s", pat["id"])
            continue

        state[pat["id"]] = process_pattern(pat, state, settings, max_docs)
        save_state(state)

    log.info("Done.")


if __name__ == "__main__":
    main()
