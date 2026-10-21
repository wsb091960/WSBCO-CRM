# WSBCO CRM — Version 3 Power Dialer

Drop-in Version 3 UI upgrade for the existing `/dialer` page.

## What it changes

- Replaces `app/templates/dialer.html`
- Adds `app/static/css/dialer_v3.css`
- Adds `app/static/js/dialer_v3.js`

## What it does NOT change

- No database changes
- No SQLAlchemy changes
- No Twilio route changes
- No `.env` changes
- No call-log schema changes

The package uses the existing backend variables:

- `next_lead`
- `history`
- `lead_names`
- `configured`

And existing routes:

- `/dialer`
- POST `/dialer/call-next`
- `/leads/{id}`
- `/leads/{id}/edit`
- `/leads/new`

## Install from `/workspaces/WSBCO-CRM`

Stop Uvicorn first.

```bash
cp app/templates/dialer.html app/templates/dialer_before_v3.html

unzip -o WSBCO_CRM_V3_Power_Dialer.zip -d v3_dialer

cp v3_dialer/app/templates/dialer.html app/templates/dialer.html
cp v3_dialer/app/static/css/dialer_v3.css app/static/css/dialer_v3.css
cp v3_dialer/app/static/js/dialer_v3.js app/static/js/dialer_v3.js
```

Restart:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open:

```text
/dialer
```

## Restore

```bash
cp app/templates/dialer_before_v3.html app/templates/dialer.html
```

Then restart Uvicorn.

## Included

- Current lead workspace
- Contact notes
- Medicare effective date
- Product-interest pills
- Priority and call-attempt display
- Large Call Next Lead control
- Agent-first workflow panel
- Queue rules panel
- Responsive recent call history
- Twilio configuration warning
- Mobile/iPad layout
- Call-start visual feedback
