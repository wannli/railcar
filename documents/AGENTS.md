# AGENTS.md

The markdown files in this directory and its subdirectories are **auto-generated**
by the scripts in `scripts/`. Do not edit them directly. Any manual changes will
be overwritten the next time the pipeline runs or when `EXTRACT_VERSION` is bumped.

The `.raw/` subdirectory contains the original per-page PDF text extractions
(separated by form-feed characters). These are the source-of-truth for
regeneration — do not edit or delete them.

To modify document output, update the extraction logic in `scripts/extract.py`
and bump `EXTRACT_VERSION`, then run `scripts/regenerate.py`.
