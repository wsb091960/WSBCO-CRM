# WSBCO CRM V3.3 — Activity Timeline & Call History

This phase adds persistent CRM activity history without changing your existing contact database.
Activities are stored in `data/wsbco_activity.db`, keyed to the existing lead ID.

## 1. Install files
From `/workspaces/WSBCO-CRM`:

```bash
cp app/templates/lead_detail.html app/templates/lead_detail_before_v33.html
unzip -o WSBCO_CRM_V3_3_Activity_Timeline.zip -d v33_activity

cp v33_activity/app/activity_v33.py app/activity_v33.py
cp v33_activity/app/static/css/activity_v33.css app/static/css/activity_v33.css
cp v33_activity/app/static/js/activity_v33.js app/static/js/activity_v33.js
python v33_activity/install_v33.py
```

## 2. Add the V3.3 Activity block to the Contact Console

Open the current template and find the existing Activity pane:
`<div id="activity" class="tab"> ... </div>`

Replace its INNER CONTENT with the contents of:
`v33_activity/ACTIVITY_TAB_SNIPPET.html`

Keep the outer `<div id="activity" class="tab">`.

## 3. Load the V3.3 CSS/JS

In `app/templates/lead_detail.html`, immediately after the existing contact-console stylesheet add:

```html
<link rel="stylesheet" href="/static/css/activity_v33.css?v=33">
```

Immediately before `{% endblock %}` add:

```html
<script src="/static/js/activity_v33.js?v=33"></script>
```

## 4. Restart
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
Hard refresh: Ctrl+Shift+R.

## What V3.3 records
- Manual activity notes
- Outbound call starts
- Call dispositions/results
- Call notes attached to dispositions
- Persistent chronological history by contact

The API endpoints are:
- GET `/api/leads/{lead_id}/activities`
- POST `/api/leads/{lead_id}/activities`

## Restore backend
```bash
cp app/main_before_v33.py app/main.py
```
