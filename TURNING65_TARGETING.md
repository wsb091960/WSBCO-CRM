# Turning 65 lead-generation targeting

Open **Turning 65 Heat Map** in the CRM sidebar (`/turning65`). Oregon,
California, West Virginia and Texas cover 403 counties in total.

- County shading by exact age-64 population or age-65+ population, with a
  count/percentage switch, county details, ranked counties and service-area totals.
- Optional insurer, exact-plan, plan-year and minimum-star filters using the
  existing CMS catalogs. County unions are deduplicated. Changing state clears
  incompatible plan selections; foreign-state counties and invalid filters fail
  explicitly. A previous county outside a new service area is deselected.
- An Esri/Leaflet map with three basemaps, state/county zoom and keyboard county
  links. An independent county-outline view, county selector and ranked table
  remain available when map resources fail.
- A separate private CRM birthday view for the next 6 or 12 months, a chosen
  future date range, or contacts currently age 64. Birthdays use Pacific local
  dates; Feb 29 uses Feb 28 in non-leap years for planning.
- Matching contact lists link to existing records and show upcoming birthdays,
  county, phone and status. Only current matched address coordinates appear as
  street-level location estimates. Missing/future birth dates, unknown counties,
  stale address locations and county conflicts are counted or excluded explicitly.
  Medicare membership follows the existing CRM rule excluding golf profiles.
- County links open the existing year/state-aware MA comparison. Territory CSV
  exports contain county aggregates, current CRM counts and source provenance,
  with no personal contact identifiers. Existing owner authentication protects
  the page, contact list, map configuration and CSV export.

Population counts are Census Vintage 2025 estimates **as of July 1, 2025**,
released in June 2026. They are not counts of current upcoming birthdays, named
leads, Medicare enrollment or individual eligibility. Birthday targeting uses
the CRM's own dates of birth instead. Plan service areas and ratings retain the
selected CMS catalog's source date and year; SNP eligibility still needs review.

The four generated snapshots in `app/data/turning65` retain source URLs and
SHA-256 hashes. `scripts/build_turning65_population.py --source-dir PATH` downloads
or reuses the original Census single-year-age CSV files and reconciles all ages,
sex totals and county coverage before writing snapshots. Refresh is explicit;
there are no Census downloads during web requests and no new runtime dependencies,
contact writes or database schema changes.

Validation: 266 Python tests and 14 GIS/targeting JavaScript checks passed.
All 403 county population/age totals and source hashes were independently
reconciled to the raw Census files. Coverage checks include Clover's seven-county
Texas area and the dated Bexar age-64 count of 21,564. Tests cover birthday/date
boundaries, missing data, authorization, safe contact rendering, export contents,
map selection/keyboard behavior and external-map outages.
