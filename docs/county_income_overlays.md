# County income and age overlays

Entry: sidebar **Income & Age Layers**, `/turning65?overlay=income`.
The existing Turning 65 entry opens the age layer. Both use the same map,
service-area filters, county selection, birthday targeting and owner access.

- **Age** colors counties by the existing exact-age-64 or age-65+ count/share.
- **Income** colors counties by 2024 median household income and ranks counties
  by that estimate. It does not sum or average county medians into an area median.
- **Both** colors counties by income and overlays teal circles representing the
  selected age count/share. Circle area is proportional to the age measure,
  using a fixed cross-state scale. County bounding-box centers are reference
  positions, not household or person locations; circles ignore pointer events
  so county clicks and keyboard links remain available.

All 403 counties: Oregon 36, California 58, West Virginia 55, Texas 254.
Income colors use fixed $50,000 / $65,000 / $80,000 / $100,000 boundaries
across states. Missing estimates use gray, distinct from zero and from counties
outside a selected plan service area. County details/table show the estimate
and its published 90% confidence range. CSV adds income, bounds, dollar year,
source/hash and selected overlay without personal identities. Income is for
all households, not specifically seniors or the residents in the age layer.

## Income source and reproducible refresh

U.S. Census Bureau **SAIPE 2024**, released January 2026, model-based annual
median household income in **2024 dollars**. The raw file identifies its
creation date as `07JAN2026`. Income year is separate from the existing
July 1, 2025 population snapshot and the selected CMS plan year.

- Source page: https://www.census.gov/data/datasets/2024/demo/saipe/2024-state-and-county.html
- Source file: https://www2.census.gov/programs-surveys/saipe/datasets/2024/2024-state-and-county/est24all.txt
- Official fixed-width layout: https://www2.census.gov/programs-surveys/saipe/technical-documentation/file-layouts/state-county/2024-estimate-layout.txt

The builder uses columns 134–139 for the estimate, 141–146 for the lower
bound, and 148–153 for the upper bound. It matches county FIPS exactly to
the existing map and rejects duplicates, partial coverage, unexpected source
versions, and invalid confidence bounds. Each checked-in JSON retains the
full source SHA-256. There are no runtime Census requests or new dependencies.

```sh
curl -fL 'https://www2.census.gov/programs-surveys/saipe/datasets/2024/2024-state-and-county/est24all.txt' -o /tmp/est24all.txt
python scripts/build_county_income.py --source /tmp/est24all.txt
```

Spot reconciliation against the source: Douglas OR $61,341, 90% interval
$57,629–$65,053; Bexar TX $72,578, interval $70,607–$74,549.
Refresh is explicit; updating to a later vintage requires updating the builder,
validator, labels, documentation, source verification and snapshots together.

## Validation — November 20, 2026 (America/Los_Angeles)

- 300 active Python tests passed: 299 in the complete suite plus the remaining
  legacy XLS test after installing its missing test-only `xlwt` dependency.
- All 23 JavaScript checks passed, including nine shared county-map checks.
- Browser verified income/combined selection, Coos county click and values,
  all 254 Texas Esri county links and all 254 Texas outline counties/circles.
  Browser used a disposable local empty database, not production contacts.
- Syntax, compile and whitespace checks passed.
- No contact writes, migration, new paid resources or runtime dependencies.
  The detailed-benefit development branch remains separate and held.
- Signed-in production and physical mobile-device acceptance are separate usage
  checks; local browser QA does not establish those.
