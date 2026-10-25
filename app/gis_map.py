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
