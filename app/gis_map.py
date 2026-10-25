"""Territory map and call selection share the same geographic matching rules."""
from collections import defaultdict
from fastapi import APIRouter, Depends, Query, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Lead
from app.call_list_gis import GeoFilter, STATE_NAMES, state_code, zip5

router = APIRouter(prefix="/gis", tags=["GIS"])
templates = Jinja2Templates(directory="app/templates")

@router.get("")
def gis_page(request: Request):
    return templates.TemplateResponse(request=request, name="gis_map.html", context={"state_names": STATE_NAMES})

def geography(
    state: str = Query("", max_length=80),
    county: str = Query("", max_length=100),
    city: str = Query("", max_length=100),
    zip_code: str = Query("", max_length=10),
):
    return GeoFilter.search({'state': state, 'county': county, 'city': city, 'zip_code': zip_code})

@router.get("/summary")
def gis_summary(
    geo: GeoFilter = Depends(geography),
    db: Session = Depends(get_db),
):
    leads = _matching_leads(db, geo)
    groups = defaultdict(lambda: {"count": 0, "counties": set(), "statuses": defaultdict(int)})
    for lead in leads:
        zipcode = zip5(lead.zip_code)
        if not zipcode:
            continue
        key = (state_code(lead.state), zipcode)
        item = groups[key]
        item["count"] += 1
        if lead.county:
            item["counties"].add(lead.county.strip())
        item["statuses"][lead.status or "Unknown"] += 1
    return {
        "total": len(leads),
        "missing_zip": len(leads) - sum(x["count"] for x in groups.values()),
        "zip_count": len(groups),
        "locations": [
            {"state": s, "zip": z, "count": v["count"],
             "counties": sorted(v["counties"]),
             "statuses": dict(v["statuses"])}
            for (s, z), v in sorted(groups.items())
        ],
        "note": "ZIP-level counts only. Markers represent ZIP areas, not contact addresses.",
    }

# Coordinates are kept in a separate cache; the Lead schema and dispositions stay untouched.
import hashlib
import json
import math
import os
import re
from urllib.parse import urlencode
from urllib.request import Request as UrlRequest, urlopen
from fastapi import HTTPException
from sqlalchemy import text

def _cache(db):
    db.execute(text("""CREATE TABLE IF NOT EXISTS gis_address_points (
        lead_id INTEGER PRIMARY KEY, address_hash TEXT NOT NULL,
        latitude REAL, longitude REAL, score REAL, match_type TEXT,
        result TEXT NOT NULL
    )"""))
    db.commit()

def _address(lead):
    return ", ".join(str(v).strip() for v in (lead.address, lead.city, lead.state, lead.zip_code) if v and str(v).strip())

def _fingerprint(lead):
    return hashlib.sha256(_address(lead).lower().encode("utf-8")).hexdigest()

def _matching_leads(db, geo):
    return [lead for lead in db.scalars(select(Lead).order_by(Lead.id)).all() if geo.matches(lead)]

def _geocode(lead, token):
    payload = urlencode({"SingleLine": _address(lead),
        "outFields": "Addr_type,Region,Postal", "f": "json", "token": token}).encode()
    req = UrlRequest("https://geocode-api.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates",
        data=payload, headers={"Content-Type": "application/x-www-form-urlencoded",
                               "User-Agent": "WSBCO-CRM-GIS/1.0"})
    with urlopen(req, timeout=12) as response:
        obj = json.load(response)
    if obj.get("error"):
        raise ValueError("Esri geocoding failed")
    candidate = (obj.get("candidates") or [None])[0]
    if not candidate:
        return None
    attr = candidate.get("attributes") or {}
    score = float(candidate.get("score") or 0)
    region = state_code(attr.get("Region"))
    postal = str(attr.get("Postal") or "")[:5]
    expected_zip = str(lead.zip_code or "")[:5]
    match_type = str(attr.get("Addr_type") or "")
    location = candidate.get("location") or {}
    lat, lon = location.get("y"), location.get("x")
    if (score < 95 or match_type not in ("PointAddress", "StreetAddress")
            or (lead.state and region != state_code(lead.state))
            or (expected_zip and postal != expected_zip)
            or not isinstance(lat, (float, int)) or not isinstance(lon, (float, int))
            or not math.isfinite(lat) or not math.isfinite(lon)
            or not -90 <= lat <= 90 or not -180 <= lon <= 180):
        return None
    return (float(lat), float(lon), score, match_type)

@router.get("/points")
def individual_points(
    geo: GeoFilter = Depends(geography),
    db: Session = Depends(get_db),
):
    _cache(db)
    leads = _matching_leads(db, geo)
    saved = {r[0]: r for r in db.execute(text(
        "SELECT lead_id, address_hash, latitude, longitude, result FROM gis_address_points")).all()}
    precision = dict(db.execute(text('SELECT lead_id, precision FROM gis_coordinate_sources')).all()) if inspect(db.get_bind()).has_table('gis_coordinate_sources') else {}
    points = []
    pending = 0
    for lead in leads:
        if not (lead.address and lead.city and lead.state):
            continue
        row = saved.get(lead.id)
        if not row or row[1] != _fingerprint(lead):
            pending += 1
            continue
        if row[4] != "matched":
            continue
        points.append({"id": lead.id, "lat": row[2], "lon": row[3],
                       "status": lead.status or "",
                       "precision": precision.get(lead.id, ''),
                       "name": ' '.join(v for v in (lead.first_name, lead.last_name) if v).strip(),
                       "address": _address(lead), "url": f'/leads/{lead.id}'})
    return {"points": points, "pending": pending, "total": len(leads),
            "unmapped": len(leads) - len(points)}

@router.post("/geocode-batch")
def geocode_batch(geo: GeoFilter = Depends(geography), db: Session = Depends(get_db)):
    token = os.getenv("ARCGIS_API_KEY", "")
    if not token:
        raise HTTPException(503, "ARCGIS_API_KEY is not configured")
    _cache(db)
    saved = {r[0]: r[1] for r in db.execute(text(
        "SELECT lead_id, address_hash FROM gis_address_points")).all()}
    processed = matched = 0
    for lead in _matching_leads(db, geo):
        if processed >= 20:
            break
        if not (lead.address and lead.city and lead.state):
            continue
        fingerprint = _fingerprint(lead)
        if saved.get(lead.id) == fingerprint:
            continue
        try:
            result = _geocode(lead, token)
            state = "matched" if result else "review"
        except Exception:
            # Do not cache transient network failures; retry next batch.
            break
        lat, lon, score, match_type = result if result else (None, None, None, None)
        db.execute(text("""INSERT INTO gis_address_points
            (lead_id, address_hash, latitude, longitude, score, match_type, result)
            VALUES (:id,:hash,:lat,:lon,:score,:type,:result)
            ON CONFLICT(lead_id) DO UPDATE SET address_hash=excluded.address_hash,
            latitude=excluded.latitude,longitude=excluded.longitude,
            score=excluded.score,match_type=excluded.match_type,result=excluded.result"""),
            {"id":lead.id,"hash":fingerprint,"lat":lat,"lon":lon,
             "score":score,"type":match_type,"result":state})
        processed += 1
        matched += bool(result)
    db.commit()
    return {"processed": processed, "matched": matched,
            "notice": "Only street addresses were sent to Esri. CRM contacts were not modified."}


@router.post('/coordinates/restore')
async def restore_coordinates(request: Request, db: Session = Depends(get_db)):
    """Two-step restoration through the existing browser-bound import protection."""
    from app.imports_v35 import require_form
    from app.services.gis_coordinates import MAX_BYTES, prepare, restore
    form = await request.form(max_files=1, max_fields=5)
    require_form(request, form)
    upload = form.get('file')
    if not hasattr(upload, 'read'):
        raise HTTPException(400, 'Choose the verified GIS results CSV.')
    content = await upload.read(MAX_BYTES + 1)
    await upload.close()
    plan, counts, signature = prepare(content, db, _fingerprint)
    if str(form.get('commit','')) != '1':
        return {**counts,'signature':signature,'mode':'preview'}
    import secrets
    if not secrets.compare_digest(str(form.get('signature','')),signature):
        raise HTTPException(409,'Contacts or source changed. Preview the coordinate restoration again.')
    _cache(db)
    return {**counts,**restore(plan,db),'mode':'restored'}
