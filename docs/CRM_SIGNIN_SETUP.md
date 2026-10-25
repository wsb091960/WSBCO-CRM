# Single-user CRM sign-in and GIS contact popups

This change is on a feature branch. **Configure Render before merging or deploying** or the CRM will show a 503 setup message (fail closed). The live database is not changed.

## Render environment variables
- `CRM_ADMIN_PASSWORD`: a unique strong password you choose; never paste it in chat or commit it.
- `CRM_SESSION_SECRET`: a random secret of at least 32 characters. Generate privately with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Do not share it.

In Render: Web Service > Environment > Add Environment Variable, then save/deploy.

## Codespaces
Set both variables in your local environment before starting uvicorn. Do not commit a .env file or client database.

## Behavior
- One password sign-in covers the entire CRM, including GIS map, contacts and the manual call list.
- Signed session cookie lasts 12 hours; sign-out clears it.
- GIS pin popup shows name, address, phone, status, and a link to the contact detail page to update dispositions.
- Website lead intake POST endpoint remains public; the health check remains public.
- Existing contacts, geocoding cache, and call logs are untouched.
- The application currently has no per-user access controls; this is intentionally a single-user password gate.

## Validation after configuration
1. In a private browser window, open the CRM URL; it should redirect to /login.
2. Incorrect password must not grant access.
3. Sign in, open GIS, click a mapped pin; verify the contact's name, address and phone.
4. Open Contact, update a test contact's disposition through the existing CRM flow.
5. Sign out; /gis/points and /leads must return 401 without a session.
6. Verify website lead intake still works.

**Security note:** Put the CRM behind HTTPS in Render. Protect the admin password and session secret; rotating the session secret signs out all sessions. This change does not include account recovery, MFA, or a distributed login rate limiter.
