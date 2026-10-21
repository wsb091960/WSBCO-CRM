from datetime import datetime, timezone
import json
import re
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column
from app.database import Base, get_db
from app.models import Lead

router = APIRouter()
templates = Jinja2Templates(directory='app/templates')
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

@router.get('/leads/{lead_id}/compare')
def compare_page(lead_id: int, request: Request, db: Session = Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(404, 'Contact not found')
    history = db.scalars(select(PlanComparison).where(PlanComparison.lead_id == lead_id).order_by(PlanComparison.id.desc()).limit(20)).all()
    return templates.TemplateResponse(request=request, name='plan_compare_v36.html', context={'lead': lead, 'history': history, 'medicare_url': MEDICARE_URL, 'current_year': datetime.now().year, 'saved': request.query_params.get('saved') == '1'})

@router.post('/leads/{lead_id}/compare')
def save_comparison(lead_id: int, zip_code: str = Form(...), county: str = Form(''), coverage_year: int = Form(...), plan_type: str = Form('MAPD'), notes: str = Form(''), plan_name: list[str] = Form([]), carrier: list[str] = Form([]), premium: list[str] = Form([]), db: Session = Depends(get_db)):
    if db.get(Lead, lead_id) is None:
        raise HTTPException(404, 'Contact not found')
    if not re.fullmatch(r'\d{5}', zip_code.strip()):
        raise HTTPException(422, 'ZIP must have five digits')
    if not 2020 <= coverage_year <= datetime.now().year + 2:
        raise HTTPException(422, 'Invalid coverage year')
    if plan_type not in ('MAPD', 'MA', 'PDP'):
        raise HTTPException(422, 'Invalid plan type')
    if len(plan_name) > 3 or len(carrier) > 3 or len(premium) > 3:
        raise HTTPException(422, 'Maximum three plans')
    plans = [{'name': n.strip()[:200], 'carrier': (carrier[i] if i < len(carrier) else '').strip()[:200], 'premium': (premium[i] if i < len(premium) else '').strip()[:100]} for i,n in enumerate(plan_name) if n.strip()]
    record = PlanComparison(lead_id=lead_id, zip_code=zip_code.strip(), county=county.strip()[:100], coverage_year=coverage_year, plan_type=plan_type, notes=notes[:5000], plans_json=json.dumps(plans))
    db.add(record)
    db.commit()
    return RedirectResponse(f'/leads/{lead_id}/compare?saved=1', status_code=303)
