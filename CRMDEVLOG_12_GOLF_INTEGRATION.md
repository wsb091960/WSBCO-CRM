# CRMDevLog #12 — Reedsport Golf Form intake

## Scope
Connect the existing published Reedsport Golf Course lesson request Form to WSBCO CRM. Student conversion and Golf Coach changes are outside this release.

- Form ID: `1cx-a4BpzNNYhpGQMA2TNIaL1NKygHST51UiY9RfAAkw`
- Apps Script project: `1E1B4Th2nJZJvDtElpphb-lkBqyqvhrrM4Jf0rGD-xsYA7nydn_tRwNSb`
- Webhook: `POST /golf/inquiries`, authenticated with `X-Golf-Form-Key`.
- Private configuration: Render `GOLF_FORM_WEBHOOK_KEY` must match Script Property `CRM_GOLF_FORM_KEY`. Never commit either value.
- `google_form/Code.gs` binds to the existing form. `setupGolfLeadForm()` installs one form-submit trigger and one five-minute recovery trigger.
- Form answers map to name, phone, optional email, experience, goals and contact preference. Details are visible in CRM contact notes, with lead source `Reedsport Golf lesson form` and a separate `GolfProfile`.
- One immutable `GolfInquiryReceipt` per response prevents retry deliveries from duplicating contacts. Independent inquiries are never merged by name alone.
- Response rows remain in the linked Google Sheet. Pending transfers are retried. Email alerts go to williamsburton@gmail.com only after the CRM confirms a contact ID, with a direct contact link.
- A successful email is marked sent. If an email provider accepts a message but then returns an ambiguous error, a retry could still duplicate that email; contact creation remains idempotent.
- Before creating the additive schema, an existing SQLite database is backed up under its persistent `backups/` directory. Existing Lead columns are not altered.
- Existing protected golf listing and explicit conversion endpoints remain disabled unless their separate environment variables are configured.

## Validation
- 11 intake/backup tests: authentication, validation, optional email/single name, receipt idempotency, preserving insurance records and database backup.
- 3 script tests: published-field mapping, failed-save retry/no success email, email retry without a second contact.
- Manual calling and Google Maps regressions: 30 tests passed.
- Deployment and Google authorization must be verified before marking the live connection complete.

## Live activation — October 25, 2026, 8:17 PM PDT
- PR #14 merged to main (`ce5fcf9bd163becca37a216e11fdced68edddca2`) and deployed live on Render. `/health` returned 200; intake without the private key returned 403.
- Google authorization approved; form-submit and five-minute recovery triggers installed successfully.
- Published Form submission created clearly labeled `CRM Connection Test` contact #736. Optional email was omitted; goals and experience appeared in CRM notes.
- Detailed success alert delivered to williamsburton@gmail.com, including a direct link to contact #736.
- The original Google Forms response notification remains enabled. Automatic approval review prevented disabling it, so both the generic Form notification and detailed post-save CRM alert may arrive.
- Flyer QR replacement and Golf workspace/Coach conversion are separate follow-up work.
- Manual recovery check completed successfully with no pending deliveries. The synthetic contact is marked Do Not Call to exclude it from calling workflows; no call was placed or logged.
