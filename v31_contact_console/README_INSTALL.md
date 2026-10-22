# WSBCO CRM V3.1 Contact Console
PhoneBurner-inspired workflow using WSBCO styling.

Install from `/workspaces/WSBCO-CRM`:

```bash
cp app/templates/lead_detail.html app/templates/lead_detail_before_v31.html
unzip -o WSBCO_CRM_V3_1_Contact_Console.zip -d v31_contact_console
cp v31_contact_console/app/templates/lead_detail.html app/templates/lead_detail.html
cp v31_contact_console/app/static/css/contact_console_v31.css app/static/css/contact_console_v31.css
cp v31_contact_console/app/static/js/contact_console_v31.js app/static/js/contact_console_v31.js
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
Hard refresh: Ctrl+Shift+R

Restore:
`cp app/templates/lead_detail_before_v31.html app/templates/lead_detail.html`
