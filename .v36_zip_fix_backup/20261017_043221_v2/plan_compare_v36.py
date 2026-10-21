from datetime import datetime, timezone
import csv, json, re
from pathlib import Path
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column
from app.database import Base, get_db
from app.models import Lead

router = APIRouter()
templates = Jinja2Templates(directory='app/templates')
DATA_FILE = Path(__file__).resolve().parent / 'data' / 'oregon_2027_mapd.csv'
SOURCE = 'CMS CY2027 Landscape 202609.1 (September 22, 2026); Oregon workbook prepared October 14, 2026'
MEDICARE_URL = 'https://www.medicare.gov/plan-compare/'

class PlanComparison(Base):
    __tablename__ = 'plan_comparisons_v36'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(Integer, ForeignKey('leads.id'), index=True)
    zip_code: Mapped[str] = mapped_column(String(5))
    county: Mapped[str] = mapped_column(String(100), default='')
    coverage_year: Mapped[int] = mapped_column(Integer)
    plan_type: Mapped[str] = mapped_column(String(10))
    notes: Mapped[str] = mapped_column(Text, default='')
    plans_json: Mapped[str] = mapped_column(Text, default='[]')
    source_url: Mapped[str] = mapped_column(String(500), default=MEDICARE_URL)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

# Verified local ZIP mapping. Unknown ZIPs require explicit county confirmation;
# never infer service-area eligibility from ZIP alone.
ZIP_COUNTIES_V36 = {'97420': 'Coos'}

def normalize_county_v36(value):
    return re.sub(r'\s+county\s*$', '', (value or '').strip(), flags=re.I).strip()

def resolve_county_v36(zip_code, county):
    county = normalize_county_v36(county)
    mapped = ZIP_COUNTIES_V36.get((zip_code or '').strip())
    # For verified ZIPs, correct a missing/stale CRM county. For other ZIPs,
    # preserve user-supplied county and require confirmation.
    if mapped and (not county or county.casefold() != mapped.casefold()):
        return mapped
    return county

def catalog():
    with DATA_FILE.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))

def county_plans(county, plan_type):
    if not county:
        return []
    return [p for p in catalog() if p['county'].casefold() == normalize_county_v36(county).casefold() and (plan_type == 'ALL' or p['category'] == plan_type)]

@router.get('/leads/{lead_id}/compare')
def compare_page(lead_id: int, request: Request, county: str = '', zip_code: str = '', plan_type: str = 'General MAPD', db: Session = Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if lead is None: raise HTTPException(404, 'Contact not found')
    zip_code = zip_code.strip() or (lead.zip_code or '')
    county = resolve_county_v36(zip_code, county.strip() or (lead.county or ''))
    if plan_type not in ('General MAPD', 'Special Needs MAPD', 'ALL'): plan_type = 'General MAPD'
    plans = county_plans(county, plan_type)
    history = db.scalars(select(PlanComparison).where(PlanComparison.lead_id == lead_id).order_by(PlanComparison.id.desc()).limit(20)).all()
    return templates.TemplateResponse(request=request, name='plan_compare_v36.html', context={'lead':lead, 'history':history, 'plans':plans, 'county':county, 'zip_code':zip_code, 'plan_type':plan_type, 'counties':sorted(set(p['county'] for p in catalog())), 'source':SOURCE, 'medicare_url':MEDICARE_URL, 'saved':request.query_params.get('saved') == '1'})

@router.post('/leads/{lead_id}/compare')
def save_comparison(lead_id:int, zip_code:str=Form(...), county:str=Form(...), coverage_year:int=Form(...), plan_type:str=Form('General MAPD'), selected_ids:list[str]=Form([]), notes:str=Form(''), db:Session=Depends(get_db)):
    if db.get(Lead,lead_id) is None: raise HTTPException(404, 'Contact not found')
    if not re.fullmatch(r'\d{5}',zip_code.strip()): raise HTTPException(422,'ZIP must have five digits')
    if coverage_year != 2027: raise HTTPException(422,'Only 2027 catalog is installed')
    if plan_type not in ('General MAPD','Special Needs MAPD','ALL'): raise HTTPException(422,'Invalid plan category')
    if not 1 <= len(selected_ids) <= 3 or len(set(selected_ids)) != len(selected_ids): raise HTTPException(422,'Select one to three different plans')
    county = resolve_county_v36(zip_code, county)
    available = {p['plan_segment_id']:p for p in county_plans(county,plan_type)}
    if any(s not in available for s in selected_ids): raise HTTPException(422,'One or more selected plans are not listed in the selected county/category')
    plans = [available[s] for s in selected_ids]
    db.add(PlanComparison(lead_id=lead_id,zip_code=zip_code.strip(),county=county.strip()[:100],coverage_year=2027,plan_type=plan_type,notes=notes[:5000],plans_json=json.dumps(plans),source_url=MEDICARE_URL))
    db.commit()
    return RedirectResponse(f'/leads/{lead_id}/compare?saved=1',status_code=303)
