"""Aggregate-only GIS map. Never expose contact names, addresses or phones."""
from collections import defaultdict
from fastapi import APIRouter, Depends, Query, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Lead

router = APIRouter(prefix="/gis", tags=["GIS"])
templates = Jinja2Templates(directory="app/templates")

@router.get("")
def gis_page(request: Request):
    return templates.TemplateResponse(request=request, name="gis_map.html", context={})

@router.get("/summary")
def gis_summary(
    state: str = Query("", max_length=2),
    county: str = Query("", max_length=100),
    zip_code: str = Query("", max_length=10),
    mode: str = Query("and", pattern="^(and|or)$"),
    status: str = Query("", max_length=50),
    db: Session = Depends(get_db),
):
    filters = []
    if state.strip():
        filters.append(Lead.state.ilike(state.strip()))
    if county.strip():
        filters.append(Lead.county.ilike(county.strip()))
    if zip_code.strip():
        filters.append(Lead.zip_code.like(zip_code.strip() + "%"))
    stmt = select(Lead.zip_code, Lead.state, Lead.county, Lead.status)
    if filters:
        from sqlalchemy import and_, or_
        stmt = stmt.where((and_ if mode == "and" else or_)(*filters))
    if status.strip():
        stmt = stmt.where(Lead.status.ilike(status.strip()))
    rows = db.execute(stmt).all()
    groups = defaultdict(lambda: {"count": 0, "counties": set(), "statuses": defaultdict(int)})
    for zipcode, state_value, county_value, status_value in rows:
        zip5 = (zipcode or "").strip()[:5]
        if len(zip5) != 5 or not zip5.isdigit():
            continue
        key = ((state_value or "").strip().upper(), zip5)
        item = groups[key]
        item["count"] += 1
        if county_value:
            item["counties"].add(county_value.strip())
        item["statuses"][status_value or "Unknown"] += 1
    return {
        "total": sum(x["count"] for x in groups.values()),
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

def _matching_leads(db, state, county, zip_code, mode, status):
    filters = []
    if state.strip():
        filters.append(Lead.state.ilike(state.strip()))
    if county.strip():
        filters.append(Lead.county.ilike(county.strip()))
    if zip_code.strip():
        filters.append(Lead.zip_code.like(zip_code.strip() + "%"))
    stmt = select(Lead)
    if filters:
        from sqlalchemy import and_, or_
        stmt = stmt.where((and_ if mode == "and" else or_)(*filters))
    if status.strip():
        stmt = stmt.where(Lead.status.ilike(status.strip()))
    return db.scalars(stmt.order_by(Lead.id)).all()

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
    region = str(attr.get("Region") or "").upper()
    postal = str(attr.get("Postal") or "")[:5]
    expected_zip = str(lead.zip_code or "")[:5]
    match_type = str(attr.get("Addr_type") or "")
    location = candidate.get("location") or {}
    lat, lon = location.get("y"), location.get("x")
    if (score < 95 or match_type not in ("PointAddress", "StreetAddress")
            or (lead.state and region != str(lead.state).upper())
            or (expected_zip and postal != expected_zip)
            or not isinstance(lat, (float, int)) or not isinstance(lon, (float, int))):
        return None
    return (float(lat), float(lon), score, match_type)

@router.get("/points")
def individual_points(
    state: str = Query("", max_length=2),
    county: str = Query("", max_length=100),
    zip_code: str = Query("", max_length=10),
    mode: str = Query("and", pattern="^(and|or)$"),
    status: str = Query("", max_length=50),
    db: Session = Depends(get_db),
):
    _cache(db)
    leads = _matching_leads(db, state, county, zip_code, mode, status)
    saved = {r[0]: r for r in db.execute(text(
        "SELECT lead_id, address_hash, latitude, longitude, result FROM gis_address_points")).all()}
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
                       "status": lead.status or ""})
    return {"points": points, "pending": pending, "total": len(leads),
            "unmapped": len(leads) - len(points)}

@router.post("/geocode-batch")
def geocode_batch(db: Session = Depends(get_db), _: bool = Depends(owner)):
    token = os.getenv("ARCGIS_API_KEY", "")
    if not token:
        raise HTTPException(503, "ARCGIS_API_KEY is not configured")
    _cache(db)
    saved = {r[0]: r[1] for r in db.execute(text(
        "SELECT lead_id, address_hash FROM gis_address_points")).all()}
    processed = matched = 0
    for lead in db.scalars(select(Lead).order_by(Lead.id)).all():
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
