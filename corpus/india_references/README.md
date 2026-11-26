# Government of India travel references

26 travel-allowance and air-travel orders from the Department of Expenditure (Ministry of Finance), chosen from
its 62 published orders for relevance to business-tour travel. `sources.json` lists each one: its number, date,
official URL, the SPARKS rule it relates to, and attribution.
`fetch_report.json` records what was downloaded: size, SHA-256, pages and whether a text layer exists.

Re-download or verify with `.venv\Scripts\python.exe -m scripts.fetch_india_references`. Files already present are skipped.

## Status (2026-11-18): text-only corpus

| | Count | IDs |
|---|---|---|
| **Kept (text layer)** | **8** | R01 (7th CPC TA rules; from the Government of Puducherry's official copy, because dot.gov.in refuses automated downloads), R02, R03 (claim time limit), R09 (air booking), R12 (authorised agents), R15 (sponsored travel), R21 (6th CPC rules, superseded), R26 |
| **Excluded (scans, no text layer)** | **18** | R04–R08, R10, R11, R13, R14, R16–R20, R22–R25. Marked `excluded` in `sources.json`; their PDFs were moved to `runtime/corpus_excluded/`, which is not shipped. |

User decision: use only documents that contain text. Scans cannot be ingested, because the upload pipeline rejects PDFs
without text and OCR is not permitted. Run the fetch script with `--include-excluded` to download the scans again.

## Rules for using these documents

- They are **references** for Central Government employees, not SPARKS policy. Ingest them with `authority: reference`,
  never as policy. They must never change a SPARKS cap; caps come only from `policy_sources/rule_registry.json`.
- **Not ingested yet.** The corpus route (`docs/DECISIONS.json`, decision `corpus`) needs course/Pair A approval first.
- Licence: Government of India orders, used for a non-commercial academic capstone with attribution (see `licence_note`
  in `sources.json`). Not legal advice.
