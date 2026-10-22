# WSBCO CRM — Version 3.2 Add/Edit Contact

Drop-in redesign of the existing contact form. No database migration is included.

## Install from `/workspaces/WSBCO-CRM`

```bash
cp app/templates/lead_form.html app/templates/lead_form_before_v32.html

unzip -o WSBCO_CRM_V3_2_Add_Edit_Contact.zip -d v32_contact_form

cp v32_contact_form/app/templates/lead_form.html app/templates/lead_form.html
cp v32_contact_form/app/static/css/contact_form_v32.css app/static/css/contact_form_v32.css
cp v32_contact_form/app/static/js/contact_form_v32.js app/static/js/contact_form_v32.js

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Hard refresh: Ctrl+Shift+R

The age-65 display is only a planning reference. It does not automatically overwrite the Medicare Effective field.

## Restore
```bash
cp app/templates/lead_form_before_v32.html app/templates/lead_form.html
```
