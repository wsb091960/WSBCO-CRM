"""Owner-only Esri address audit. Preview only: never mutates CRM records."""
import json
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
