# CRMDevLog #14 — Medicare Advantage County Maps

November 19, 2026 (America/Los_Angeles). Initial WV implementation.

The sidebar **MA County Map** opens `/ma-map`. Each of the 55 WV county
polygons is a real link to that county's plans. A dropdown and county directory
provide alternative navigation. No student/contact or insurance records change.

## Included

- 2027 (default) and 2026 plan-year selection.
- All WV MA, MA-PD and SNP records in the selected CMS Landscape, across all
  published insurance brands. Standalone PDP and Cost categories are excluded.
- Filters for insurer, Part D coverage, and general versus special eligibility.
- Up to three plans compared side by side within one county, year and filter.
- Premiums, Part D deductible, in-network medical MOOP, star rating, SNP details,
  sanctions and enrollment-capacity fields from CMS. For MA-only plans, the
  monthly plan premium comes from Part C; CMS marks consolidated C+D as N/A.
- Source dates, source links, snapshot limitations and additional eligibility
  requirements. Unknown benefits are explicitly unavailable, never zero-filled.
- Existing owner middleware protects the page and comparison. Static map/plan
  data contains public information only. No DB migration, runtime downloads,
  paid map provider, new runtime dependency, or deployment settings are needed.

## Data provenance and refresh

| Input | Source update | WV county-plan entries | Distinct plan segments | Insurance brands |
|---|---|---:|---:|---:|
| [CMS CY2027 Landscape (202611)](https://www.cms.gov/files/zip/cy2027-landscape-202611.zip) | 2026-11-01 | 2,519 | 70 | 9 |
| [CMS CY2026 Landscape (202609)](https://www.cms.gov/files/zip/cy2026-landscape-202609.zip) | 2026-09-02 | 2,526 | 69 | 8 |
| [Census 2025 county boundaries, 1:5,000,000](https://www2.census.gov/geo/tiger/GENZ2025/shp/cb_2025_us_county_5m.zip) | 2025 boundaries | 55 counties | — | — |

Counts are county-plan rows or statewide unique segments/brands as labeled;
2,519 is not the number of distinct statewide plans. CMS excludes employer
sponsored plans, Part B-only plans, and National PACE plans from this Landscape.
The app does not claim to establish address-level service eligibility.

`app/data/ma_map` contains derived public data and the source SHA-256 hashes.
The original ZIP files are not committed. The refresh builder requires **pyshp**
as a development-only dependency:

```sh
python -m pip install pyshp
python scripts/build_wv_ma_catalog.py \
  --boundaries /path/to/cb_2025_us_county_5m.zip \
  --landscape 2027=/path/to/cy2027-landscape-202611.zip \
  --landscape 2026=/path/to/cy2026-landscape-202609.zip
```

Use original ZIPs from the linked government sources. The builder validates
columns, year, all county mappings and duplicate/conflicting plan records before
writing. Review regenerated changes, reconcile to the original files, and
restart/redeploy after an approved refresh to clear in-process data caches.
New plan years require an explicit catalog registration in `CATALOG_FILES`.

## Validation

- All 174 repository tests passed, including 9 county-map cases; the 9 relevant
  tests passed again after the MA-only premium display correction.
- Independently reconciled every 2026/2027 WV county-plan row, brand, premium,
  MOOP and drug deductible against the original downloaded CMS CSVs.
- Full app startup/health and logged-out map denial passed. Tests verify owner
  access, invalid county/year/IDs, foreign-county and filtered-out selections,
  missing data, selection limits, no PDP leakage, and source provenance.
- Desktop browser: clicked Mercer County, compared Peak Health/The Health
  Plan/UnitedHealthcare, changed plan year (clears comparison), and filtered
  plans without Part D. All displayed the expected source values.
- JS syntax and whitespace checks passed. Responsive CSS is included; no
  separate narrow-viewport browser test was performed.

## Remaining scope

Medical deductibles, visit copays and dental/vision/hearing details require
additional verified plan benefit sources; they are not supplied by Landscape.
Provider/pharmacy networks and personalized drug pricing are not evaluated.
This explorer does not yet save to a contact or print/email a comparison; the
existing Oregon contact comparison (#5) remains separate. Follow-up work should
unify these comparisons and retain correct state/year/county identity. Print
and email remain #6. Later states: Oregon, California, then Texas after WV
acceptance. Current source snapshots require an explicit refresh process;
automatic scheduled updates are not included in this first version.

The initial code/QA record alone does not establish a live release. Deployment
status and user acceptance belong in the main development log.

## Oregon expansion — November 19, 2026

William accepted the first WV version and requested Oregon next. The **MA County
Map** page now has **West Virginia** and **Oregon** state tabs. Open Oregon at
`/ma-map?state=OR`. All 36 Oregon county polygons remain clickable, including
counties with no MA plans in the selected source year. Zero-plan counties are
shaded gray and have a dated, explicit no-listings message. An empty result
after applying filters is identified separately.

| CMS input | Oregon county-plan rows | Distinct plan segments | Insurance brands | Counties with no MA listings |
|---|---:|---:|---:|---:|
| CY2027 Landscape (202611), updated 2026-11-01 | 518 | 95 | 14 | 5 |
| CY2026 Landscape (202609), updated 2026-09-02 | 595 | 101 | 15 | 6 |

Both catalogs use the same government ZIP sources and provenance format as WV.
The county geometry comes from the same Census 2025 national boundaries,
filtered to Oregon FIPS 41 and projected at Oregon's latitude. The source
builder keeps its filename for backward compatibility; use `--state OR` to
generate Oregon files and omit the flag (or use `--state WV`) for WV. Example:

```sh
python scripts/build_wv_ma_catalog.py --state OR \
  --boundaries /path/to/cb_2025_us_county_5m.zip \
  --landscape 2027=/path/to/cy2027-landscape-202611.zip \
  --landscape 2026=/path/to/cy2026-landscape-202609.zip
```

State navigation clears county, filters and comparison selections while keeping
the selected year. All county links, forms and comparison queries retain the
state explicitly. Foreign-state counties or plans are rejected. Old WV URLs
without a state parameter still work. Location/filter forms now use an explicit
action so a previous comparison anchor does not pull the user to an empty
comparison after changing year or filters.

Validation: 181 repository tests passed, including 16 map/catalog cases. Every
Oregon county-plan row, brand, plan name, coverage/SNP flag and core cost field
was independently reconciled against the original 2026 and 2027 CMS CSVs. A WV
rebuild produced identical geometry/catalog content apart from the import
timestamp. Full app health and Oregon access protection, JS syntax and
whitespace checks passed. Desktop browser checks cover county navigation,
Douglas County comparison/year switching, state reset and zero-plan county
handling. Detailed benefits, contact saving, source refresh automation and
narrow-viewport browser verification retain the limits described above. No
new runtime dependency, database migration or contact changes are introduced.

At the Oregon release, California and Texas remained future states under #14.
The California expansion is recorded below. Release details are recorded in
the main development log after deployment verification.

## California expansion — November 19, 2026

The **MA County Map** now includes a **California** state tab at
`/ma-map?state=CA`. All 58 Census county polygons are clickable. The existing
2026/2027 selection, all-insurer listing, drug/SNP filters, up-to-three-plan
comparison, missing-benefit labels, and dated no-listings behavior also apply
to California. State/year/county identity is preserved throughout; California
county IDs retain their leading zero (for example, Los Angeles is `06037`).

| CMS input | California county-plan rows | Distinct plan segments | Insurance brands | Counties with no MA listings |
|---|---:|---:|---:|---:|
| CY2027 Landscape (202611), updated 2026-11-01 | 1,278 | 394 | 38 | 3 |
| CY2026 Landscape (202609), updated 2026-09-02 | 1,334 | 402 | 41 | 2 |

California geometry uses the same Census 2025 national boundaries, filtered
to FIPS 06 and projected at latitude 37. Use `--state CA` with the existing
source builder and original government ZIP inputs to regenerate the files.
WV and Oregon data files and runtime dependencies are unchanged.

Validation: all 188 repository tests passed, including 23 map/catalog cases.
Independently reconciled every California county-plan row and core cost,
carrier, plan-name, drug-coverage and SNP fields against the original CMS CSVs
for both years. Full-app startup/health and California access checks, JS syntax
and whitespace checks passed. Desktop browser checks confirmed the 124-entry
2027 Los Angeles list, general-enrollment filtering, a three-brand comparison,
Lake County's change from no listings in 2027 to one in 2026, and state/reset
behavior. No separate narrow-viewport browser test was performed.

California inherits the documented limits for detailed medical/supplemental
benefits, provider/drug verification, contact saving and automated refreshes.
No contact changes or database migration were introduced. At the California
release, Texas remained the next state under #14. Its expansion is recorded
below; deployment evidence is recorded in the main log.

## Texas expansion — November 19, 2026

The **Texas** tab at `/ma-map?state=TX` completes the requested initial
four-state county-map rollout: West Virginia, Oregon, California and Texas.
All 254 Texas county polygons are clickable, with the same plan-year,
all-listed-insurer, drug-coverage/SNP filters and three-plan comparison.
No other state's catalog or geometry is replaced.

| CMS input | Texas county-plan rows | Distinct plan segments | Insurance brands | Counties with MA listings |
|---|---:|---:|---:|---:|
| CY2027 Landscape (202611), updated 2026-11-01 | 9,363 | 421 | 22 | 254 |
| CY2026 Landscape (202609), updated 2026-09-02 | 10,378 | 423 | 28 | 254 |

Counts describe public CMS Landscape records, including Special Needs Plans
with extra eligibility conditions; they are not individualized enrollment
determinations. The same plan segment appears in multiple county rows. Texas
geometry uses Census 2025 national county boundaries filtered to FIPS 48 and
projected at latitude 31. Use `--state TX` with the existing builder and
original government ZIP files to refresh Texas. Provenance retains the source
URLs, dates, hashes and import timestamp.

Validation: all 196 repository tests passed, including 31 map/catalog cases.
Every Texas county-plan row, carrier, plan name, coverage/SNP flag and core
cost field was independently reconciled with both original CMS CSVs. Desktop
browser checks confirmed Harris County's 99-entry 2027 list, general-plan
filtering, a three-brand comparison, a reset to 114 entries for 2026, Loving
County's own listings, and clean state switching. Full app health/access, JS
syntax and whitespace checks passed. No separate narrow-viewport browser test
was performed. There are no new runtime dependencies, DB migrations or contact
changes.

The initial four-state map rollout is delivered. Item #14 remains In progress
for the documented detailed-benefit, contact-save and source-refresh work;
this expansion does not supply medical copays/deductibles, supplemental
benefits, personalized drug pricing or network verification. The main
development log records the deployed commit and production checks.
