# CRMDevLog #11 — Contact Map It button

The contact console now places **Map It** beside the full address. It opens
Google Maps in a new tab, leaving the manual call form and its unsaved notes open.
The address and button wrap to fit narrow contact panels and phone screens.

- Uses the contact's existing matched GIS coordinates when the address fingerprint
  still matches and both coordinates are finite and in range.
- Falls back to a URL-encoded search for the saved street address plus city/state
  or ZIP. Old or invalid coordinates cannot override the current address.
- Disables the button with address guidance when no usable destination exists.
- Sends only the location in the link; no name, phone, notes, or insurance fields.
- No geocoder calls, contact writes, schema migrations, or calling workflow changes.

Validation: all 119 Python tests and 8 JavaScript checks passed, including the
manual calling regression checks. Request-level tests cover address fallback,
matched coordinates, stale and invalid points, missing addresses, URL encoding,
and preservation of manual-call form data on errors. Browser visual inspection
was unavailable because the browser executable download returned an invalid archive.

Deployment completion and the deployed commit are recorded in the saved
CRMDevLog #11 entry.
