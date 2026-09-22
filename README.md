# WSBCO Insurance CRM — Phase 1.2

Phase 1.2 adds an agent-first Twilio power dialer to the Phase 1.1 contact CRM.

## New Features

- Call selected contact
- Call next eligible lead
- Agent-first two-leg dialing
- Twilio status callbacks
- Automatic call-attempt counter
- Automatic last-contact timestamp
- Call-history database table
- Call dispositions and follow-up dates
- Do Not Call protection
- US phone-number normalization
- Optional Twilio webhook signature validation

## Upgrade Existing Phase 1.1 Project

Back up the existing database first:

```bash
cp data/insurance_crm.db data/insurance_crm.backup.db
```

Copy the Phase 1.2 files over your Phase 1.1 files. Do not delete your existing
`data/insurance_crm.db`.

Install the new dependencies:

```bash
pip install -r requirements.txt
```

Create your environment file:

```bash
cp .env.example .env
```

Edit `.env` and enter:

- Twilio Account SID
- Twilio Auth Token
- Twilio phone number
- Your agent phone number
- Public HTTPS application URL

Start the app:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The new `call_logs` table is created automatically at startup.

## GitHub Codespaces BASE_URL

Make port 8000 public, then copy its HTTPS forwarded address. It usually resembles:

```text
https://YOUR-CODESPACE-NAME-8000.app.github.dev
```

Do not add a trailing slash.

## Twilio Trial Accounts

A Twilio trial account may require the agent and destination numbers to be
verified before calls can be completed.

## Webhook Security

Keep this setting during initial Codespaces testing:

```env
VALIDATE_TWILIO_SIGNATURES=false
```

After the public URL is stable, change it to `true` and restart the app.

## Call Eligibility

Call Next Lead selects these statuses:

- New
- Attempt Again
- Callback
- Interested

Contacts marked Do Not Call are blocked from selected calling.

## Privacy

This remains a development build. Before storing real Medicare beneficiary
identifiers, add authentication, authorization, HTTPS enforcement, encryption
at rest, audit logging, secure backups, and session timeout controls.
