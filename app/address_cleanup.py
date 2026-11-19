"""Owner-only Esri address audit. Preview only: never mutates CRM records."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import os
import re
import secrets
from urllib.parse import urlencode
from urllib.request import Request as UrlRequest, urlopen

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Lead

router = APIRouter(prefix="/address-cleanup", tags=["Address Cleanup"])
templates = Jinja2Templates(directory="app/templates")
basic = HTTPBasic()

def owner(credentials: HTTPBasicCredentials = Depends(basic)):
    password = os.getenv("GIS_MAP_PASSWORD", "")
    if not password or not (secrets.compare_digest(credentials.username, "owner") and secrets.compare_digest(credentials.password, password)):
        raise HTTPException(status_code=401, detail="Owner access required", headers={"WWW-Authenticate": "Basic"})
    return True

def valid_zip(value):
    return bool(re.fullmatch(r"\d{5}(?:-\d{4})?", (value or "").strip()))

@router.get("")
def page(request: Request, _: bool = Depends(owner)):
    return templates.TemplateResponse(request=request, name="address_cleanup.html", context={})

@router.get("/audit")
def audit(db: Session = Depends(get_db), _: bool = Depends(owner)):
    leads = db.scalars(select(Lead)).all()
    return {"total": len(leads), "missing_zip": sum(not valid_zip(l.zip_code) for l in leads),
            "missing_county": sum(not (l.county or "").strip() for l in leads),
            "missing_street": sum(not (l.address or "").strip() for l in leads),
            "ready_for_geocoding": sum(bool((l.address or "").strip() and (l.city or "").strip() and (l.state or "").strip()) for l in leads)}

@router.post("/preview")
def preview(db: Session = Depends(get_db), _: bool = Depends(owner)):
    token = os.getenv("ARCGIS_API_KEY", "")
    if not token:
        raise HTTPException(503, "ARCGIS_API_KEY missing in server environment")
    leads = db.scalars(select(Lead).order_by(Lead.id)).all()
    results = []
    # Only ten eligible records, never save anything. Do not return token to browser.
    for lead in leads:
        if len(results) >= 10:
            break
        if not all((lead.address or "").strip(),) or not (lead.city or "").strip() or not (lead.state or "").strip():
            continue
        address = ", ".join(v.strip() for v in (lead.address, lead.city, lead.state, lead.zip_code) if v and v.strip())
        payload = urlencode({"SingleLine": address, "outFields": "Match_addr,Addr_type,City,Region,Postal,Subregion", "f":"json", "token":token}).encode()
        try:
            req = UrlRequest("https://geocode-api.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates", data=payload, headers={"Content-Type":"application/x-www-form-urlencoded","User-Agent":"WSBCO-CRM-address-audit/1.0"})
            with urlopen(req, timeout=12) as response:
                obj = json.load(response)
            if obj.get("error"):
                raise ValueError(obj["error"].get("message","ArcGIS error"))
            candidate = (obj.get("candidates") or [None])[0]
            attr = candidate.get("attributes", {}) if candidate else {}
            score = float(candidate.get("score",0)) if candidate else 0
            street_level = attr.get("Addr_type") in ("PointAddress", "StreetAddress", "StreetInt")
            results.append({"id":lead.id,"name":(lead.first_name+" "+lead.last_name).strip(),
                "existing":{"state":lead.state or "","zip":lead.zip_code or "","county":lead.county or ""},
                "suggested":{"state":attr.get("Region") or "","zip":attr.get("Postal") or "","county":attr.get("Subregion") or ""},
                "score":score,"match_type":attr.get("Addr_type") or "Unmatched",
                "review":"High confidence — preview only" if score>=95 and street_level else "Manual review",
                "error":""})
        except Exception as exc:
            results.append({"id":lead.id,"name":(lead.first_name+" "+lead.last_name).strip(),
                "existing":{"state":lead.state or "","zip":lead.zip_code or "","county":lead.county or ""},
                "suggested":{},"score":0,"match_type":"Error","review":"Manual review","error":str(exc)[:120]})
    return {"results":results,"notice":"Preview only. No CRM records changed. Esri may charge for requests."}

# Phase 2: explicitly approved, backed-up, conservative county-only updates.
_STATE_NAMES = {"OR":"OREGON","WV":"WEST VIRGINIA","WA":"WASHINGTON","CA":"CALIFORNIA","TX":"TEXAS"}
def _normalize_county(value):
    return re.sub(r"\\s+County$", "", (value or "").strip(), flags=re.I).strip()

@router.post("/apply-first-10")
def apply_first_ten(db: Session = Depends(get_db), _: bool = Depends(owner)):
    """Geocode first ten eligible missing-county records; back up SQLite before writes."""
    token = os.getenv("ARCGIS_API_KEY", "")
    if not token:
        raise HTTPException(503, "ArcGIS key missing")
    url = db.get_bind().url
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise HTTPException(503, "Automatic backup only supports file-based SQLite; no updates performed")
    source = Path(url.database).resolve()
    if not source.is_file():
        raise HTTPException(503, "Database file not found; no updates performed")
    # Database backup must succeed before contacting Esri or making any edits.
    backup_dir = source.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / ("before_county_update_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f") + ".db")
    try:
        with sqlite3.connect(str(source)) as original, sqlite3.connect(str(backup_path)) as copy:
            original.backup(copy)
    except Exception:
        raise HTTPException(503, "Database backup failed; no records changed")
    leads = db.scalars(select(Lead).where((Lead.county == None) | (Lead.county == "")).order_by(Lead.id)).all()
    updated, skipped, checked = [], [], 0
    for lead in leads:
        if checked >= 10:
            break
        if not all([(lead.address or "").strip(), (lead.city or "").strip(), (lead.state or "").strip(), valid_zip(lead.zip_code)]):
            continue
        checked += 1
        address = ", ".join(v.strip() for v in (lead.address, lead.city, lead.state, lead.zip_code) if v)
        payload = urlencode({"SingleLine":address,"outFields":"Addr_type,Region,Postal,Subregion","f":"json","token":token}).encode()
        try:
            req = UrlRequest("https://geocode-api.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates",data=payload,headers={"Content-Type":"application/x-www-form-urlencoded","User-Agent":"WSBCO-CRM-county-cleanup/1.0"})
            with urlopen(req,timeout=12) as response:
                obj=json.load(response)
            if obj.get("error"):
                raise ValueError(obj["error"].get("message","ArcGIS error"))
            cand=(obj.get("candidates") or [None])[0]
            a=cand.get("attributes",{}) if cand else {}
            score=float(cand.get("score",0)) if cand else 0
            state=(lead.state or "").upper().strip()
            matched_state=(a.get("Region") or "").upper().strip()
            matched_zip=(a.get("Postal") or "").strip()[:5]
            county=_normalize_county(a.get("Subregion"))
            kind=a.get("Addr_type")
            eligible=(score>=95 and kind in ("PointAddress","StreetAddress","Subaddress")
                and matched_state in (state,_STATE_NAMES.get(state,""))
                and matched_zip == (lead.zip_code or "")[:5] and bool(county))
            if eligible and not (lead.county or "").strip():
                lead.county=county
                updated.append({"id":lead.id,"county":county,"score":score})
            else:
                skipped.append({"id":lead.id,"reason":"Uncertain match or state/ZIP mismatch"})
        except Exception as exc:
            skipped.append({"id":lead.id,"reason":str(exc)[:100]})
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(500,"Database write failed; backup retained")
    return {"checked":checked,"updated":updated,"skipped":skipped,"backup_file":backup_path.name,
            "note":"County only; state, ZIP and existing county values were not overwritten."}
