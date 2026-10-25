# CRMDevLog #8 — Simple GIS search

The territory map and 10-contact call list now use **State, County, City, ZIP** in that order. Fill any fields and select **Search**. Entered fields narrow the results automatically. **Clear** removes the location restrictions. The AND/OR selector and contact-status search control are removed from the map search.

## Calling workflow

1. Open **GIS Territory Map** and search your area.
2. Select **Open 10-Call List** to carry the same geographic selection into calling.
3. Review eligible contacts and select **Generate … Calls from This Search**.
4. Dial manually, record a disposition and notes, and save.

The territory map counts all matching CRM contacts. The call-list count includes only contacts currently eligible to call. The map may therefore show more contacts than the list. Calling exclusions and priority ordering are preserved.

Existing unfinished lists remain saved. Searching or clearing previews another area without replacing the pending list. A list generated before geographic filtering was installed remains available. Old saved OR selections are readable for continuity, while all new searches narrow across entered fields.

## Maps and contact records

The territory map retains the existing Esri street-address pins and map layers. Contact popups show name, address, status and an **Open contact** link within the CRM. Multiple contacts at the same location appear together. The page uses existing geocoded locations. The manual batch-geocoding button has been removed at William’s request.

The call-list preview shows approximate ZIP centers and contact counts. It does not represent individual street locations. Contacts without a usable map location remain available for calling when otherwise eligible. Search, saved lists and call dispositions remain usable if map resources cannot load.

State names and abbreviations are accepted. City and county matching ignore case and extra spaces. County names accept the County suffix. ZIP+4 matches the first five digits; leading zeros are preserved. Invalid location inputs produce a message instead of generating a broader list.

## Data and installation

Runtime files integrate the existing GIS call-list package with the current CRM source. Existing lead, call-log, call-batch, call-item and address-cache schemas are retained. The new geographic snapshot and ZIP cache tables are created through the app's existing startup `create_all`. No current database file, credentials or contact export is included in this update.

The installation package includes `gis_simple_search/install.py`. Run it from the existing CRM project root after extracting the ZIP. It verifies known baseline files, backs up files being replaced, and copies the update. It does not replace `main.py` or database configuration. Restart or deploy the updated source through the existing workflow.

## Verification

```bash
python -m pytest -q tests
node --test tests/test_call_list_gis_js.cjs tests/test_gis_map_js.cjs
```

Checks cover shared geography, City, single-field and combined searches, blank fields, empty results, invalid input, ZIP+4, leading zeros, geographic snapshots, old saved lists, list preservation, disposition logging, contact links, scoped geocoding, stale search responses, Clear, and unavailable map libraries. All tests use synthetic contacts and mocked external lookups. Desktop/mobile visual inspection and live deployment remain release checks; a browser could not be installed in the build environment.
