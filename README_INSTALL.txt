WSBCO CRM V3.6 — Medicare Plan Comparison (initial manual workflow)

Extract ZIP into /workspaces/WSBCO-CRM, on feature/crm-v3-6-plan-comparison.
Run: python install_v36.py
Run: python -m pytest tests/test_imports_v35.py -q
Run: python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
Open a contact and click Compare Plans.

This is the first milestone, not a live Medicare.gov data integration.
Existing contacts remain untouched. New plan_comparisons_v36 table is created at startup.
The comparison window prefills ZIP and county from the selected contact.
No client data is sent to Medicare.gov by the CRM.
Review manually entered plan details against official sources.

Do not push to Alpha before testing. The application has no authentication layer
in the inspected source, so protect it from public access until authentication
and authorization are implemented. For production, add CSRF protection to the
save endpoint and access controls to client records.
