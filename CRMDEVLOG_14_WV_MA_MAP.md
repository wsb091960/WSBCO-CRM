# CRMDevLog #14 — West Virginia MA County Map

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
