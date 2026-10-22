# WSBCO CRM V3.4 — Calendar & Follow-Up Center

This phase turns `/calendar` into a daily sales queue.

## Install
From `/workspaces/WSBCO-CRM`:

```bash
unzip -o WSBCO_CRM_V3_4_Followup_Center.zip -d v34_followup

cp v34_followup/app/followup_v34.py app/followup_v34.py
cp v34_followup/app/templates/calendar_v34.html app/templates/calendar_v34.html
cp v34_followup/app/static/css/calendar_v34.css app/static/css/calendar_v34.css

python v34_followup/install_v34.py
python -m py_compile app/main.py app/followup_v34.py

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Then open `/calendar`.

V3.4 reads the existing CRM database and uses each lead's `next_follow_up` date. It does not create a second follow-up database.

Views:
- Today
- Overdue
- Upcoming
- All Open

Each queue row provides Call, Open Contact Console, and Edit Contact actions.

Restore backend:
```bash
cp app/main_before_v34.py app/main.py
```
