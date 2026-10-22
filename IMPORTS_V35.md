# WSBCO CRM v3.5 — Contact Imports

CSV, Excel (.xlsx and .xls), and private Google Sheets now use one workflow:
**Import Data → Choose source → Match columns → Review → Confirm → Results.**

The new Import Data link appears in the sidebar and on Contacts. This update builds on the existing v3.4 code; the Follow-Up Center uses the same contacts and follow-up dates. It does not replace the database.

## Install the update ZIP

In the existing CRM project folder, with the app stopped:

```bash
unzip -o WSBCO_CRM_V3_5_Data_Import.zip
python install_v35.py
python -m pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Then open `/imports` or click Import Data. The installer copies only the new import files and applies small changes to navigation, requirements, and app registration. It first saves all affected existing files and the database to a timestamped `backups/v35_*` folder. Run it from the project root. Restarting the app creates one staging table automatically; existing contact, activity, and call tables are preserved.

If using the GitHub feature branch, install its requirements and restart instead; no installer is needed. Test this feature branch before merging into your deployment branch.

## Prepare a source

- Put unique column headings on row 1 and one contact on each following row.
- Maximum: 10 MB uploaded file, 10,000 data rows, and 100 source columns. Expanded XLSX content is limited to 100 MB.
- First and last names must be separate and are required. Other columns are optional.
- Dates: `YYYY-MM-DD` or US `MM/DD/YYYY`, with a four-digit year. Excel native dates work. Last Contact also accepts ISO dates with optional hours, minutes, and seconds.
- Interest fields: Yes/No, True/False, Y/N, or 1/0.
- States use two-letter abbreviations. ZIP codes accept five digits or ZIP+4; numeric short ZIPs are padded to five digits.
- Keep phone numbers and identifiers as text in Excel. Values already rounded by a spreadsheet cannot be reconstructed.
- An Excel tab name is optional; otherwise the first tab is used. Save Excel formula results before importing; cached values are read and formulas are not executed.
- Download a blank CSV template from the import page if helpful.

Recognized aliases include DOB, MBI, ZIP, Cell, Supp, Adv, PDP, Dental, and Next Follow-up. Check all suggested column matches. You can skip columns. IDs and database timestamps are never imported.

## Matching and updates

The default is **Skip matching contacts**. Choose **Update matching contacts** when appropriate. Updates apply only mapped, nonblank source values; blanks never erase current values. Explicit No/False updates an interest field to false.

Matches use normalized Medicare MBI, email, phone/mobile, or full name plus birth date. Name alone does not trigger a merge. If a name-only row repeats a name already in the CRM, it is flagged for correction instead of creating another contact. Conflicting identities, conflicting Medicare MBIs, and phone/email matches to a different name are flagged. Repeated contacts within one source use the first valid row and skip later repeats.

An existing Do Not Call status cannot be cleared by an import. Review any intentional status change in the contact console.

Review the counts, row results, and proposed values. Updates also show current values. The page shows the first 200 rows; the results CSV includes outcomes for every source row. Invalid rows are left out while valid rows are saved. Fix invalid rows in the source and import them again. The results CSV identifies source row numbers and corrections.

If contacts change after preview, the preview refreshes and requires another confirmation. Commit claims and contact writes share one database transaction. Repeated confirmation cannot commit a completed batch again. A save failure rolls back the entire batch.

## Google Sheets connection — one-time server setup

Google Sheets access is implemented but requires credentials in your deployed CRM. A ChatGPT Google Drive connection does not automatically connect this separate FastAPI app. No live Google Sheet was accessed during validation.

1. In Google Cloud, create or select a project and enable the **Google Sheets API**.
2. Create a service account and a JSON key, following your organization's Google Cloud key policy.
3. Configure one of these server environment variables:
   - `GOOGLE_APPLICATION_CREDENTIALS`: absolute path to a private JSON credentials file on the server; or
   - `GOOGLE_SHEETS_CREDENTIALS_JSON`: the complete JSON key stored as a server secret/environment value.
4. Share only the needed spreadsheet with the service account's `client_email` as **Viewer**. Keep the sheet private.
5. Restart the CRM. Paste its standard Google Sheets URL into Import Data.
6. An explicit tab name takes precedence. Otherwise the URL's `gid` selects the tab, or the first tab is used.

The importer requests the read-only Sheets scope and makes read requests only. It does not write to the source sheet. Google Sheets must be a native spreadsheet, not an unconverted Excel file in Drive. If the connection is unavailable, download the sheet as CSV/Excel and use the file import.

Never put credential keys in GitHub or in the update ZIP.

Google documentation:
- https://developers.google.com/workspace/sheets/api/scopes
- https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/get

## Staging and results

Previews are stored server-side in the same SQLite database and bound to the initiating browser. They survive an app restart. Preview and results access expires one hour after upload. Expired records are removed on the next import; accessing an expired batch removes that batch. Cancel discards the staging record. On completion, raw source rows and preview values are replaced with a compact outcome summary. Clearing completed results does not delete imported contacts.

These browser tokens protect import batches; they are not a replacement for the CRM's overall access controls.

## Validation

Run from the repository root:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Covered: CSV encodings/delimiters, XLSX tab and native dates, real legacy XLS date cells, alias mapping, invalid input, blank-preserving updates, explicit false flags, follow-up dates, duplicate/repeat imports, conflicting identities, Do Not Call preservation, stale/competing previews, commit retry, full rollback, browser ownership, CSRF, expiry, cancellation, output escaping, limits, Google Sheets tab selection and permission/connection errors using mocked API responses.

Dashboard, Contacts, Calendar/Follow-Up Center, Import Data, template download, and health endpoint were also checked with the complete FastAPI app. Browser visual inspection was unavailable because the Chromium download failed. A live Google connection remains to be configured and verified.
