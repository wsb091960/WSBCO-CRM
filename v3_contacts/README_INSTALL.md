# WSBCO CRM — Version 3 Contacts

Drop-in UI upgrade for the existing `/leads` page.

## Changes
- Replaces `app/templates/leads.html`
- Adds `app/static/css/contacts.css`
- No database, Twilio, model, route, or `.env` changes

## Install from `/workspaces/WSBCO-CRM`

```bash
cp app/templates/leads.html app/templates/leads_before_v3_contacts.html
unzip -o WSBCO_CRM_V3_Contacts.zip -d v3_contacts
cp v3_contacts/app/templates/leads.html app/templates/leads.html
cp v3_contacts/app/static/css/contacts.css app/static/css/contacts.css
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open `/leads`.

## Restore
```bash
cp app/templates/leads_before_v3_contacts.html app/templates/leads.html
```

## Included
- Professional Contacts header
- Search/status toolbar
- Desktop CRM table
- Tablet/mobile contact cards
- Status badges
- Priority styling
- Medicare effective date
- Product-interest pills
- Follow-up display
- Direct Twilio Call button
- Open/Edit actions
- Do Not Call protection
