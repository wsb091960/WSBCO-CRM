# Detailed benefit comparison — development only

Started November 19, 2026 (America/Los_Angeles) at William Burton's request.

**Do not merge or deploy this branch.** The live CRM uses Esri by default at
commit `00c6651c95230155e440bf1eab4cde07282c5246`. This branch starts the benefit
data feasibility and validation work. It does not change CRM routes, rendered
comparisons, runtime requirements, or live benefit values. Render watches `main`
with automatic deployment disabled. No benefits deployment has been requested.

## First milestone

The official CMS CY2027 PBP ZIP was downloaded successfully. Its readme confirms
the 2027 submission year; its Excel dictionary supplies field titles and code
meanings. The evidence importer joins contract, PBP, segment, and year exactly,
checks plan names and source versions, and retains complete source rows with
file/line references and hashes. Repeated network/group records are preserved.

| State | Distinct plans in county catalog | Exact PBP identity matches | Name/version review issues |
|---|---:|---:|---:|
| West Virginia | 70 | 70 | 0 |
| Oregon | 95 | 95 | 0 |
| California | 394 | 394 | 0 |
| Texas | 421 | 421 | 0 |
| Total | 980 | 980 | 0 |

These are distinct contract/PBP/segment identities, not summed county listings.
All 980 have baseline medical financial, professional, inpatient, dental,
vision, hearing, and supplemental-service table records. A table record is
**not proof a benefit is covered**: blanks, indicator codes, conditions,
limits, networks and eligibility must still be interpreted. Missing optional
out-of-network, point-of-service or flexibility records are reported separately
and are not silently treated as absent coverage. `release_ready` remains false
for every plan, even where the matching audit passes.

The initial import retains 12 PBP tables; other supplemental variations,
SSBCI/eligibility-specific tables and tier tables still need assessment. It is
not yet a complete benefit model. The 2026 source has not been imported.

## Source and reproducibility

- [Official CMS benefits page](https://www.cms.gov/data-research/statistics-trends-and-reports/medicare-advantagepart-d-contract-and-enrollment-data/benefits-data/pbp-benefits-2027)
- [Official CMS source ZIP](https://www.cms.gov/files/zip/pbp-benefits-2027.zip)
- ZIP SHA-256: `6d8430e2ecb51acf3cc8547f12dd73506aa73f0dccf034cc3c3393868576ff47`
- HTTP Last-Modified: October 1, 2026, 17:45:40 GMT. This is transport metadata,
  not an asserted date for every individual plan record.
- `2027_coverage_audit.json` records table and dictionary hashes and coverage.
- `atrio_choice_rx_partial_check.json` records a small carrier-document check.

The [official ATRIO Douglas County Summary of Benefits](https://www.atriohp.com/media/zvybx12z/2027-dg-sb_final-v2.pdf)
was readable through web retrieval and a page image. Its page 7 (printed page 6)
states an in-network $0 primary-care copay and $50 specialist copay for Choice Rx
H6743-007. The PBP specialist fields agree. The primary-care amount cells are
blank with the copay indicator set to No; the importer retains that distinction
instead of replacing every blank with zero. This checks two items only, not the
whole plan. Direct programmatic PDF download returned 403, so automated carrier
document retrieval is not yet established for this source.

Install development dependencies, download the pinned official ZIP, then run:

```bash
python scripts/build_ma_benefit_evidence.py \
  --source-zip /path/to/pbp-benefits-2027.zip --year 2027 \
  --catalog app/data/ma_map/wv_2027.json \
  --catalog app/data/ma_map/or_2027.json \
  --catalog app/data/ma_map/ca_2027.json \
  --catalog app/data/ma_map/tx_2027.json \
  --source-url https://www.cms.gov/files/zip/pbp-benefits-2027.zip \
  --last-modified 'Thu, 01 Oct 2026 17:45:40 GMT' \
  --output development/generated/ma_benefits/2027
```

Generated evidence is ignored by Git; source hashes and compact audit results
are tracked. The development-only openpyxl dependency is not added to runtime
requirements. All source values remain strings: missing, explicit zero, No,
unknown codes and unparsed bit masks remain distinct.

## Release conditions still open

1. Define and verify benefit mappings for medical deductible, primary care,
   specialists, inpatient day ranges, dental, vision and hearing. Preserve
   copay/coinsurance, per-service deductibles, network context, time periods,
   annual/shared allowances, benefit caps, authorization and eligibility rules.
2. Decode dictionary masks and category lists with tested contextual rules.
   Unresolved codes must stay unavailable for client-facing comparisons.
3. Cross-check representative HMO, PPO, SNP, no-Part-D and supplemental variants
   across carriers and all four states against current carrier SB/EOC documents.
   Record exact document applicability, page references and disagreements.
4. Assess other PBP tables and the 2026 source. Fail closed on year, identity,
   source-version, schema, missing-data or document conflicts.
5. Build the side-by-side development UI only from reviewed normalized values,
   with sources, limits and missing-value labels. Validate readability and the
   current discovery/filter/comparison workflow, including iPad use.
6. Review the completed development result with William. Do not merge or deploy
   benefits changes while these validation conditions remain open. This first
   milestone does not establish release readiness.

## Validation so far

All 217 active repository tests pass, including 52 focused tests: 44 county-map/catalog tests and 8 new evidence tests.
The evidence tests cover wrong-year/segment joins, group preservation, name and
version mismatches, duplicate-column conflicts, malformed records, and the
distinction among blanks, zero, No, and unresolved multi-selection codes.
The real-source 980-plan audit is separate from those synthetic tests and is
recorded in the adjacent JSON. No production benefit UI testing is claimed.
