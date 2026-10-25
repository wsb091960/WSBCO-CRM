# CRMDevLog #10 — Manual calling workflow

Implemented October 25, 2026.

The Contact page opens with manual calling controls: readable phone numbers,
call disposition, notes and an optional follow-up date. The small top Auto call
button remains available by explicit choice. The large bottom dial button and
requirement to start a Twilio call before logging a manual result are removed.

A saved manual call records one call-log entry, updates attempts and last-contact
time, and appears in the Contact activity timeline. Repeat submissions use a
unique database key to prevent duplicate attempts. Non-contact outcomes such as
No Answer preserve the existing lead status; meaningful outcomes such as
Interested, Callback or Do Not Call update it.

Manual saves from a Contact page also complete that contact in its active saved
10-call list. Save & Next Contact advances to the next pending list entry. Skip
finishes a list entry without recording a call or increasing attempts. Completed
and skipped entries remain visible until a new batch is generated explicitly.
Contact eligibility and phone availability are checked again when saving.

Geographic filters and saved-list persistence are retained. List priority orders
follow-ups and callbacks before other contacts, with the longest waiting first
within the same priority group. Rows display the selection reason and last call.
The Follow-Up Center and activity timeline use the configured CRM data directory.

Existing follow-ups use dates. Optional automated calls retain their existing
provider workflow and result form.

## Validation

- 55 Python regression checks passed across manual workflow, GIS call lists and
  geographic search, including concurrent duplicate submissions, cross-page
  saves, DNC/phone changes, invalid forms, skipped entries and list completion.
- 9 existing GIS browser-script checks passed.
- Contact templates render successfully in the request-level checks.
- Automated visual inspection was unavailable because the browser executable
  download failed in the execution environment.

## Rollout

Application startup creates the new `manual_call_submissions` table through the
existing SQLAlchemy `create_all` hook. Existing contacts, call logs and list
entries require no data conversion. The code change does not place phone calls.
