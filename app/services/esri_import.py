"""Conservative, opt-in Esri county suggestions for import previews.

Never sends names, phone numbers, or Medicare identifiers to Esri.
"""
import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen

URL = "https://geocode-api.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates"

# Esri may return a full state name while CRM stores its postal abbreviation.
_STATE_NAMES = """AL Alabama|AK Alaska|AZ Arizona|AR Arkansas|CA California|CO Colorado|CT Connecticut|DE Delaware|FL Florida|GA Georgia|HI Hawaii|ID Idaho|IL Illinois|IN Indiana|IA Iowa|KS Kansas|KY Kentucky|LA Louisiana|ME Maine|MD Maryland|MA Massachusetts|MI Michigan|MN Minnesota|MS Mississippi|MO Missouri|MT Montana|NE Nebraska|NV Nevada|NH New Hampshire|NJ New Jersey|NM New Mexico|NY New York|NC North Carolina|ND North Dakota|OH Ohio|OK Oklahoma|OR Oregon|PA Pennsylvania|RI Rhode Island|SC South Carolina|SD South Dakota|TN Tennessee|TX Texas|UT Utah|VT Vermont|VA Virginia|WA Washington|WV West Virginia|WI Wisconsin|WY Wyoming|DC District of Columbia""".split("|")
_STATE_LOOKUP = {name[3:].upper(): name[:2] for name in _STATE_NAMES}


def normalize_state(value):
    text = str(value or "").strip().upper().replace(".", "")
    return _STATE_LOOKUP.get(text, text)



def suggest_county(data, request_fn=None):
    """Return a verified missing county suggestion, or a review reason."""
    if data.get("county"):
        return {"status": "existing", "county": ""}
    fields = [str(data.get(k) or "").strip() for k in ("address", "city", "state", "zip_code")]
    if not all(fields[:3]):
        return {"status": "incomplete", "county": ""}
    token = os.getenv("ARCGIS_API_KEY", "")
    if not token:
        return {"status": "unconfigured", "county": ""}
    payload = urlencode({
        "SingleLine": ", ".join(x for x in fields if x),
        "outFields": "Addr_type,Region,Postal,Subregion",
        "f": "json", "token": token, "maxLocations": "1",
    }).encode()
    try:
        if request_fn is None:
            def request_fn(body):
                req = Request(URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
                with urlopen(req, timeout=12) as response:
                    return json.load(response)
        result = request_fn(payload)
        if result.get("error"):
            return {"status": "service_error", "county": ""}
        candidate = (result.get("candidates") or [None])[0]
        if not candidate:
            return {"status": "no_match", "county": ""}
        attrs = candidate.get("attributes") or {}
        score = float(candidate.get("score") or 0)
        postal = str(attrs.get("Postal") or "").split("-")[0]
        original_postal = fields[3].split("-")[0]
        state = str(attrs.get("Region") or "").upper()
        county = str(attrs.get("Subregion") or "").strip()
        if (score >= 95 and attrs.get("Addr_type") in {"PointAddress", "StreetAddress"}
                and normalize_state(state) == normalize_state(fields[2])
                and (not original_postal or postal == original_postal)
                and county):
            return {"status": "verified", "county": county, "score": score}
        reasons = []
        if score < 95:
            reasons.append("low_score")
        if attrs.get("Addr_type") not in {"PointAddress", "StreetAddress"}:
            reasons.append("not_street_level")
        if normalize_state(state) != normalize_state(fields[2]):
            reasons.append("state_mismatch")
        if original_postal and postal != original_postal:
            reasons.append("zip_mismatch")
        if not county:
            reasons.append("county_missing")
        return {"status": "review", "county": "", "score": score, "reasons": reasons}
    except Exception:
        return {"status": "service_error", "county": ""}


def enrich_preview(result, limit=10, lookup=suggest_county):
    """Review at most limit eligible create/update rows; no database writes."""
    suggestions = {}
    checked = 0
    for row in result["rows"]:
        if checked >= limit:
            break
        if row["action"] not in ("create", "update") or row["data"].get("county"):
            continue
        checked += 1
        suggestions[str(row["row"])] = lookup(row["data"])
    return suggestions


def eligible_rows(result):
    """Only actionable rows with missing county need Esri checks."""
    return [row for row in result["rows"]
            if row["action"] in ("create", "update") and not row["data"].get("county")]


def enrich_next_batch(result, previous=None, limit=10, lookup=suggest_county):
    """Resume after previous results; never repeat already checked rows."""
    suggestions = dict(previous or {})
    pending = [row for row in eligible_rows(result) if str(row["row"]) not in suggestions]
    for row in pending[:limit]:
        suggestions[str(row["row"])] = lookup(row["data"])
    return suggestions
