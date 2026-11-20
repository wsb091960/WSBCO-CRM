# Automatic contact geocoding

New contacts receive a durable geocoding job in the same database transaction
as the contact. This covers manual entry, imports and website/integration
intake. Changing the street address, city, state or ZIP queues a fresh lookup;
notes, calls and county-only edits do not.

The app's background worker processes committed jobs using Esri when
`ARCGIS_API_KEY` is configured, or the key-free U.S. Census geocoder otherwise.
An Esri authentication/configuration error also falls back to Census.
Contact saves never wait for a provider request. The queue
survives app restarts, retries transient errors with bounded backoff, and uses
short leases and address fingerprints to reject duplicate or stale results.
No separate service or new runtime dependency is required.

Only street-address fields are sent to the selected geocoder. Esri requests
storage permission and WGS84 coordinates. For Esri, a score of at least 95, a street/address-point result,
matching supplied state/ZIP, valid coordinates and no near-tied alternate
location are required to create a territory-map pin. Provenance and location
precision are saved. Verified county results fill a blank county; conflicting
existing counties are preserved and flagged on the contact.

Census requires one address match, matching supplied state/ZIP and house number,
a TIGER street segment, county geography and valid coordinates. These are
estimated street-range locations; no confidence score is invented. Census
requests use POST bodies so addresses are not embedded in the request URL.
Reference: https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.html

The contact's **Address location** field reports locating, located, delayed,
address needed or review status. Website/golf inquiries that currently collect
no street address wait until an address is added. PO boxes and uncertain
matches require review. Correcting the address retries the lookup. Existing
historical contacts and coordinates are not bulk reprocessed by this release.

The existing GIS cache is reused. One new `contact_geocoding_jobs` table is
created at startup; the leads schema is unchanged. No plan-discovery or
additional-benefit changes are included.

Validation uses synthetic contacts and mocked Esri responses: manual/import/
website/golf intake, rollback/deletion, background startup/shutdown, retries,
lease recovery, address races, privacy, location validation, and additive
schema initialization without backfilling existing contacts.
