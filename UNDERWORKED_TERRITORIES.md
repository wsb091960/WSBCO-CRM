# Underworked Territories

Private route `/territories`; sidebar **Underworked Territories**. Oregon, California,
West Virginia and Texas, all 403 counties. Read-only; no schema changes or new dependencies.

Two transparent lenses rank counties descending:

- Low CRM presence: published age-64 estimate / (all Medicare CRM contacts + 1).
- Low recent outreach: published age-64 estimate / (distinct recently worked contacts + 1).

The +1 avoids division by zero. Equal indices sort by age-64 count, then county name.
Map thresholds 100, 500, 2,000 and 10,000 are fixed across states and lenses, not percentile bands.
The index is a planning ratio, not penetration, available leads or a sales probability.
Contact counts are all ages, using the existing Medicare workspace membership rule
(GolfProfile contacts excluded). Dates of birth and street coordinates are not required.

Recent outreach includes valid nonfuture last-contact dates, saved call-log attempts
(excluding creating/failed/canceled setup), and activities explicitly typed call/email.
Contacts count once across sources. Notes, scheduled follow-ups, generic status changes
and dispositions alone do not establish outreach. Call totals count only saved call logs,
so a call activity may establish contact-level outreach without adding to call-log totals.
All dates use Pacific calendar days, including today through the current instant;
naive persisted timestamps are UTC. Defaults to 90 days; 30/60/180/365 also supported.
No CRM writes, dialing, email or new lead creation occurs in this view.

Missing activity database/table is read-only and explicitly reported; saved call logs
and last-contact dates remain usable. Incomplete recorded history can overstate gaps.
Blank/unknown counties, geocoding conflicts and address-cache fingerprint mismatches
are excluded and counted as state-level data-quality gaps. DNC contacts remain in
coverage counts and are labeled on the review list; existing contact permissions apply.

Reuses the validated July 1, 2025 Census single-age snapshots from Turning 65,
county geometry, Esri basemaps and keyboard-accessible map controller. Census reference
date remains visible beside present-day CRM figures. County details link to upcoming
CRM birthdays and 2027 county plans. Minimum population and zero-contact filters,
paginated contact review and aggregate-only CSV retain applied filter context.
CSV contains formula, source URL/hash, lookback start/as-of timestamp and data gaps.

Validation: `pytest tests -q` and Node map checks, including distinct outreach sources,
Pacific/UTC boundaries, future and non-outreach exclusions, county data gaps, all four
states, filters, privacy, auth, pagination, safe rendering and reproducible CSV math.
Detailed medical/supplemental plan-benefit development remains separate and held.
