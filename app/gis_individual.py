"""Password-protected, opt-in individual contact geocoding and mapping."""
import base64
import json
import os
import secrets
from urllib.parse import urlencode
from urllib.request import Request as URLRequest, urlopen

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy import Float, ForeignKey, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.database import Base, get_db
from app.models import Lead

router = APIRouter(prefix="/gis/individual", tags=["GIS Individual"])
templates = Jinja2Templates(directory="app/templates")
basic = HTTPBasic()

class ContactGeo(Base):
    __tablename__ = "contact_geo"
    lead_id: Mapped[int] = mapped_column(Integer, ForeignKey("leads.id"), primary_key=True)
    address_key: Mapped[str] = mapped_column(String(700))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    score: Mapped[float] = mapped_column(Float)

def authorize(credentials: HTTPBasicCredentials = Depends(basic)):
    expected = os.environ.get("GIS_MAP_PASSWORD", "")
    if not expected or not (secrets.compare_digest(credentials.username, "owner") and secrets.compare_digest(credentials.password, expected)):
        raise HTTPException(401, "GIS password required", headers={"WWW-Authenticate": "Basic"})
    return True

def address_key(lead):
    return "|".join((lead.address or "", lead.city or "", lead.state or "", lead.zip_code or "")).strip().lower()

@router.get("", response_class=HTMLResponse)
def page(request: Request, _: bool = Depends(authorize)):
    return templates.TemplateResponse(request=request, name="gis_individual.html", context={})

@router.get("/data")
def data(db: Session = Depends(get_db), _: bool = Depends(authorize)):
    leads = db.scalars(select(Lead)).all()
    saved = {g.lead_id:g for g in db.scalars(select(ContactGeo)).all()}
    pins = []
    missing = 0
    for lead in leads:
        key = address_key(lead)
        geo = saved.get(lead.id)
        if geo and geo.address_key == key and lead.address and lead.city:
            pins.append({"id":lead.id,"name":(lead.first_name+" "+lead.last_name).strip(),"lat":geo.latitude,"lon":geo.longitude,"score":geo.score,"county":lead.county or "","zip":lead.zip_code or ""})
        else:
            missing += 1
    return {"pins":pins,"unmapped":missing,"total":len(leads)}

@router.post("/geocode")
def geocode(db: Session = Depends(get_db), _: bool = Depends(authorize)):
    token = os.environ.get("ARCGIS_API_KEY", "")
    if not token:
        raise HTTPException(503, "ARCGIS_API_KEY is not configured on the server")
    saved = {g.lead_id:g for g in db.scalars(select(ContactGeo)).all()}
    processed = 0
    matched = 0
    for lead in db.scalars(select(Lead).order_by(Lead.id)).all():
        if processed >= 10:
            break
        if not lead.address or not lead.city or not lead.state:
            continue
        key = address_key(lead)
        if lead.id in saved and saved[lead.id].address_key == key:
            continue
        processed += 1
        address = ", ".join(x for x in (lead.address, lead.city, lead.state, lead.zip_code) if x)
        params = urlencode({"SingleLine":address,"f":"json","outFields":"Match_addr,Addr_type","token":token})
        try:
            req = URLRequest("https://geocode-api.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates?" + params, headers={"User-Agent":"WSBCO-CRM/1.0"})
            with urlopen(req, timeout=12) as response:
                result = json.load(response)
            candidates = result.get("candidates") or []
            candidate = candidates[0] if candidates else None
            # Avoid plotting approximate ZIP/city matches as street addresses.
            if not candidate or float(candidate.get("score",0)) < 90 or candidate.get("attributes",{}).get("Addr_type") not in ("PointAddress","StreetAddress","StreetInt"):
                continue
            loc = candidate["location"]
            db.merge(ContactGeo(lead_id=lead.id,address_key=key,latitude=float(loc["y"]),longitude=float(loc["x"]),score=float(candidate["score"])))
            matched += 1
        except Exception:
            continue
    db.commit()
    return {"processed":processed,"matched":matched,"note":"Up to 10 addresses per request. Only high-confidence street-level matches are saved."}
