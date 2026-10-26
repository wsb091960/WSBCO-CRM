# CRMDevLog #12 — Golf CRM integration (development branch)

## What is implemented
- CRM `POST /golf/inquiries`: authenticated server-to-server intake; creates a CRM lead and a separate golf profile.
- CRM `GET /golf/contacts`: authenticated list of golf-only contacts.
- CRM `POST /golf/contacts/{lead_id}/convert`: explicit conversion to Golf Coach.
- Golf Coach `POST /integrations/crm/students`: authenticated, idempotent student creation with persistent CRM contact ID link.
- No changes to existing Lead or Student table columns; new tables created through existing SQLAlchemy startup.
- No automatic synchronization of insurance data or lesson/session records.

## Render environment variables
CRM:
- `GOLF_FORM_WEBHOOK_KEY`: random secret for trusted form relay (never put in browser code)
- `GOLF_ADMIN_API_KEY`: separate random secret for golf contact listing/conversion
- `GOLF_COACH_API_URL`: HTTPS origin for Golf Coach (example: https://wsbco-golf-coach.onrender.com)
- `GOLF_COACH_SYNC_KEY`: same strong random secret configured on Golf Coach

Golf Coach:
- `GOLF_COACH_SYNC_KEY`: matching shared secret

**Never commit secret values.** Do not configure these on production until tested on staging.

## Google Form relay
Create a Google Form with first name, last name, phone, email, lesson program, and golf goal.
Link responses to a Google Sheet and install a Google Apps Script *installable on-form-submit trigger*.
The trigger should read the response, then POST JSON to `/golf/inquiries` with the
`X-Golf-Form-Key` header. Store the secret in Apps Script Properties, not the Form or Sheet.
Point the QR code at the public Google Form responder URL, not the CRM webhook.
A form URL is required before the QR code can be generated.

## Review and test before merging
1. Back up both SQLite databases and verify Render persistent disks.
2. Start each app on staging; confirm new tables `golf_profiles` and `crm_student_links`.
3. Verify missing/invalid secrets return HTTP 403.
4. Submit a test inquiry; confirm a new CRM lead and golf profile.
5. Convert once; confirm student and link. Convert twice; confirm same student ID.
6. Confirm insurance contacts are unchanged and Golf Coach sessions remain intact.
7. Review duplicate-name/email handling (no automatic merging), youth/guardian consent,
   contact permissions, rate limiting, and logging before opening the public form.

## Current limitations
- API-first implementation: Golf workspace navigation, buttons, Google Form, flyer and QR code are **not** built yet.
- No background retries or cross-system transaction guarantees.
- No automatic matching of existing students; manual reconciliation is needed.
- No tests executed or production deployment performed.
