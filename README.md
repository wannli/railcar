# Railcar

A pipeline that downloads UN documents and converts them to plaintext.

## How it works

1. **Patterns** defined in `config/patterns.json` describe document series (e.g., `A/RES/80/{X}`)
2. A daily GitHub Actions workflow increments X, discovers each document via the UN Digital Library Search API, downloads the English PDF, and extracts plaintext using PyMuPDF
3. Plaintext files are committed to `documents/` with YAML front matter containing metadata and the extraction version
4. Progress is tracked in `state/progress.json` so each run picks up where the last left off

## Adding a new pattern

Edit `config/patterns.json`:

```json
{
  "id": "sc-res-2025",
  "pattern": "S/RES/{X}",
  "start": 2700,
  "description": "Security Council Resolutions from 2700 onward",
  "enabled": true
}
```

## Manual trigger

Run the workflow from the Actions tab with optional inputs:
- **pattern_id**: Run only a specific pattern
- **max_docs**: Cap documents per pattern (default 10)

## Extraction versioning

Every output file includes `extract_version` in its front matter. When extraction logic in `scripts/extract.py` is improved, bump `EXTRACT_VERSION` there. Files produced by older versions can be identified and re-processed.

## Running locally

```bash
pip install -r scripts/requirements.txt
cd scripts && python fetch_documents.py
```

Set `MAX_DOCS=2` to test with a small batch.
