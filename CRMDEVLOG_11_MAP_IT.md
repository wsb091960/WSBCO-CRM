# CRMDevLog #11 — Contact Map It button

The contact console now places **Map It** beside the full address. It opens
Esri ArcGIS Map Viewer in a new tab, leaving the manual call form and its unsaved notes open.
The address and button wrap to fit narrow contact panels and phone screens.

- Uses the contact's existing matched GIS coordinates when the address fingerprint
  still matches and both coordinates are finite and in range.
- Falls back to a URL-encoded search for the saved street address plus city/state
  or ZIP. Old or invalid coordinates cannot override the current address.
- Disables the button with address guidance when no usable destination exists.
- Sends only the location in the link; no name, phone, notes, or insurance fields.
- No geocoder calls, contact writes, schema migrations, or calling workflow changes.

## Esri update — October 25, 2026

William requested Esri mapping instead of Google Maps. Map It now opens ArcGIS
Map Viewer with an Esri Streets basemap and a simplified map view. Matched GIS
coordinates use ArcGIS longitude/latitude order, center the view at street scale,
and add a WGS84 marker. Address fallback uses ArcGIS's address search.
The original CRM tab remains open. No CRM data or API-key settings change.

URL parameters follow Esri's official reference:
https://doc.arcgis.com/en/arcgis-online/reference/use-url-parameters.htm

Validation: all 119 Python tests and 8 JavaScript checks passed, including the
manual calling regression checks. Request-level tests cover address fallback,
matched coordinates, stale and invalid points, missing addresses, URL encoding,
and preservation of manual-call form data on errors. The ArcGIS viewer opened
anonymously in the cloud browser, but map rendering could not be visually checked
because that browser lacks WebGL2 support. Live CRM link verification is recorded
with the deployment.

Deployment completion and the deployed commit are recorded in the saved
CRMDevLog #11 entry.
