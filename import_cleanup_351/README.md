# WSBCO CRM — Import Cleanup 3.5.1

Prepared October 18, 2026. This updates the existing V3.5 import module; it does not downgrade the overall CRM version or replace other CRM features.

## Installation

1. Extract this ZIP into a separate folder, such as `import_cleanup_351`, inside your CRM project.
2. Stop the CRM server. From the CRM project root run:

   `python import_cleanup_351/install_import_cleanup.py`

3. Restart the CRM using your usual command. Open Import Data and start a new preview.

The installer backs up the four importer files and the standard `data/insurance_crm.db` database. If you use a different database path, back it up separately before installing. It checks the importer file hashes and stops without changing files if your current code differs from the saved V3.5 package. Do not bypass that check; merge against your current code instead. No new dependencies or database migrations are required.

To undo: stop the server, restore the four `app/` files from the printed backup folder, and restart. Restoring code does not undo contacts imported afterward. Keep database backups private and out of GitHub.

## What changes

- Recognized full state names and mixed-case postal abbreviations normalize automatically. Unknown names and misspellings remain visible for review.
- Each preview shows all-row counts, cell correction counts, and errors grouped by field, exact source value, and reason.
- Replace repeated values once and review the refreshed preview before committing. No status meaning is guessed automatically.
- Download a cleaned CSV or original source values before committing.
- Valid records import while invalid records are held. Afterward, download only rejected rows, with source row numbers, error messages, and original values in a JSON audit column. Fix and upload that smaller file; leave the three added metadata columns set to Skip.
- Existing duplicate checks, stale-preview checks, transactional commit, blank-field protection, and Do Not Call protection remain in place.
- Rejected source records are retained only in the expiring import batch. Download them within one hour of upload. Full successful source rows are removed at commit.

CSV stores ZIP codes as text, including leading zeros, but spreadsheet programs may reinterpret them. When editing CSV, explicitly import ZIP and identifier columns as Text. CSV exports escape formula-like values for spreadsheet safety. Original source values means parsed cell values, not a byte-for-byte copy of the original file; keep your original upload.

## Verification and limits

Automated tests use the saved CRM model and templates in a temporary test application. The running CRM and current repository were unavailable, so installation and live application verification remain pending.

The provided 773-row contact export was previewed against an empty test database, without importing it. The original importer classified 331 as new, 10 as skipped, and 432 as errors. With this update: 459 new, 12 skipped, and 302 needing review. Actual counts will differ against your CRM's existing contacts. Remaining issues include missing last names, nonstandard call statuses, and malformed states. No names or statuses were guessed, and no real contacts are included in this update package.

Tests cover 400 mixed-format states, leading-zero ZIPs, grouped corrections, stale correction rejection, rejected-row export and retry, repeated commits, original-value preservation, existing duplicate protection, Do Not Call, transaction rollback, source formats, and browser isolation. Run from a CRM checkout with development dependencies installed: `python -m pytest tests -q` after copying the included tests into a test checkout.
