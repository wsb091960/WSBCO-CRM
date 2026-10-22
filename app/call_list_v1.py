from datetime import date, datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Lead, CallLog

router = APIRouter(prefix="/call-list")
templates = Jinja2Templates(directory="app/templates")
OUTCOMES = {"No Answer": "Attempt Again", "Left Message": "Attempt Again", "Live Voicemail": "Attempt Again", "Callback": "Callback", "Interested": "Interested", "Appointment Set": "Appointment Set", "Not Interested": "Not Interested", "Do Not Call": "Do Not Call", "Wrong Number": "Wrong Number", "Sold": "Sold"}
EXCLUDED = {"do not call", "sold", "wrong number", "not interested"}

def candidates(db):
    today=date.today()
    contacted_today=set(db.scalars(select(CallLog.lead_id).where(CallLog.started_at >= datetime.combine(today, datetime.min.time()))).all())
    leads=db.scalars(select(Lead).where((Lead.phone != "") | (Lead.mobile != ""))).all()
    eligible=[l for l in leads if (l.status or "").strip().lower() not in EXCLUDED and l.id not in contacted_today and (l.last_contact is None or l.last_contact.date() != today)]
    def score(l):
        due=l.next_follow_up
        group=0 if due and due < today else 1 if due == today else 2 if (l.status or '').lower() == 'callback' else 3 if (l.status or '').lower() == 'new' else 4
        priority=0 if (l.priority or '').lower() in {'urgent','high'} else 1
        return (group, priority, due or date.max, l.call_attempts or 0, l.id)
    return sorted(eligible, key=score)

@router.get("")
def call_list(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request=request, name="call_list_v1.html", context={"contacts": [], "available": len(candidates(db)), "generated": False, "outcomes": OUTCOMES})

@router.post("/generate")
def generate(request: Request, db: Session = Depends(get_db)):
    contacts=candidates(db)[:10]
    return templates.TemplateResponse(request=request, name="call_list_v1.html", context={"contacts": contacts, "available": len(candidates(db)), "generated": True, "outcomes": OUTCOMES})

@router.post("/{lead_id}/outcome")
async def record_outcome(lead_id: int, request: Request, db: Session = Depends(get_db)):
    lead=db.get(Lead, lead_id)
    if not lead: raise HTTPException(404, 'Contact not found')
    form=await request.form()
    outcome=str(form.get('outcome','')).strip()
    if outcome not in OUTCOMES: raise HTTPException(400, 'Invalid outcome')
    if (lead.status or '').strip().lower() == 'do not call': raise HTTPException(403, 'Do Not Call contact')
    notes=str(form.get('notes','')).strip()[:2000]
    now=datetime.utcnow()
    db.add(CallLog(lead_id=lead.id, lead_phone=lead.phone or lead.mobile, direction='manual', status='completed', disposition=outcome, started_at=now, completed_at=now, notes=notes))
    lead.call_attempts=(lead.call_attempts or 0)+1
    lead.last_contact=now
    lead.status=OUTCOMES[outcome]
    lead.updated=now
    if outcome == 'Callback':
        value=str(form.get('next_follow_up','')).strip()
        if value:
            try: lead.next_follow_up=date.fromisoformat(value)
            except ValueError: raise HTTPException(400,'Invalid follow-up date')
    if notes: lead.notes=((lead.notes or '')+'\n'+f'[{now:%Y-%m-%d %H:%M} UTC] {outcome}: {notes}').strip()
    db.commit()
    return RedirectResponse('/call-list?recorded=1', status_code=303)
