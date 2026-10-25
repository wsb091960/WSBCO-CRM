from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from urllib.parse import urlencode
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import DateTime, ForeignKey, Integer, String, select, and_, or_
from sqlalchemy.orm import Mapped, Session, mapped_column
from app.database import Base, get_db
from app.models import Lead, CallLog

router = APIRouter(prefix="/call-list")
templates = Jinja2Templates(directory="app/templates")
OUTCOMES = {"No Answer": "Attempt Again", "Left Message": "Attempt Again", "Live Voicemail": "Attempt Again", "Callback": "Callback", "Interested": "Interested", "Appointment Set": "Appointment Set", "Not Interested": "Not Interested", "Do Not Call": "Do Not Call", "Wrong Number": "Wrong Number", "Sold": "Sold"}
EXCLUDED = {"do not call", "sold", "wrong number", "not interested"}

class ManualCallBatch(Base):
    __tablename__ = "manual_call_batches"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class ManualCallItem(Base):
    __tablename__ = "manual_call_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(Integer, ForeignKey("manual_call_batches.id"), index=True)
    lead_id: Mapped[int] = mapped_column(Integer, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    outcome: Mapped[str] = mapped_column(String(60), default="")

def territory_query(request):
    q = request.query_params
    return {k: q.get(k, "").strip() for k in ("state", "county", "zip_code")} | {"mode": q.get("mode", "and") if q.get("mode") in ("and", "or") else "and"}

def candidates(db, territory=None):
    today = date.today()
    contacted_today = set(db.scalars(select(CallLog.lead_id).where(CallLog.started_at >= datetime.combine(today, datetime.min.time()))).all())
    stmt = select(Lead).where((Lead.phone != "") | (Lead.mobile != ""))
    if territory:
        parts = []
        if territory["state"]:
            parts.append(Lead.state.ilike(territory["state"]))
        if territory["county"]:
            parts.append(Lead.county.ilike(territory["county"]))
        if territory["zip_code"]:
            parts.append(Lead.zip_code.like(territory["zip_code"] + "%"))
        if parts:
            stmt = stmt.where((and_ if territory["mode"] == "and" else or_)(*parts))
    leads = db.scalars(stmt).all()
    eligible = [l for l in leads if (l.status or "").strip().lower() not in EXCLUDED and l.id not in contacted_today and (l.last_contact is None or l.last_contact.date() != today)]
    def score(l):
        due = l.next_follow_up
        group = 0 if due and due < today else 1 if due == today else 2 if (l.status or '').lower() == 'callback' else 3 if (l.status or '').lower() == 'new' else 4
        priority = 0 if (l.priority or '').lower() in {'urgent', 'high'} else 1
        return (group, priority, due or date.max, l.call_attempts or 0, l.id)
    return sorted(eligible, key=score)

def active_batch(db):
    return db.scalar(select(ManualCallBatch).where(ManualCallBatch.completed_at.is_(None)).order_by(ManualCallBatch.id.desc()).limit(1))

def render_list(request, db):
    batch = active_batch(db)
    items = db.scalars(select(ManualCallItem).where(ManualCallItem.batch_id == batch.id).order_by(ManualCallItem.id)).all() if batch else []
    lead_ids = [i.lead_id for i in items]
    leads = {l.id: l for l in db.scalars(select(Lead).where(Lead.id.in_(lead_ids))).all()} if lead_ids else {}
    rows = [{"item": item, "lead": leads.get(item.lead_id)} for item in items]
    done = sum(item.completed_at is not None for item in items)
    territory = territory_query(request)
    return templates.TemplateResponse(request=request, name="call_list_v1.html", context={"rows": rows, "batch": batch, "done": done, "available": len(candidates(db, territory)), "outcomes": OUTCOMES, "territory": territory, "territory_qs": urlencode(territory)})

@router.get("")
def call_list(request: Request, db: Session = Depends(get_db)):
    return render_list(request, db)

@router.post("/generate")
def generate(request: Request, db: Session = Depends(get_db)):
    # An unfinished list must never be replaced by clicking Generate again.
    if active_batch(db):
        return RedirectResponse('/call-list', status_code=303)
    leads = candidates(db, territory_query(request))[:10]
    if leads:
        batch = ManualCallBatch()
        db.add(batch)
        db.flush()
        db.add_all([ManualCallItem(batch_id=batch.id, lead_id=lead.id) for lead in leads])
        db.commit()
    return RedirectResponse('/call-list', status_code=303)

@router.post("/{lead_id}/outcome")
async def record_outcome(lead_id: int, request: Request, db: Session = Depends(get_db)):
    batch = active_batch(db)
    if not batch:
        raise HTTPException(409, 'No active call list')
    item = db.scalar(select(ManualCallItem).where(ManualCallItem.batch_id == batch.id, ManualCallItem.lead_id == lead_id, ManualCallItem.completed_at.is_(None)))
    if not item:
        raise HTTPException(409, 'Contact is not pending in the current call list')
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(404, 'Contact not found')
    if (lead.status or '').strip().lower() == 'do not call':
        raise HTTPException(403, 'Do Not Call contact')
    form = await request.form()
    outcome = str(form.get('outcome', '')).strip()
    if outcome not in OUTCOMES:
        raise HTTPException(400, 'Invalid outcome')
    notes = str(form.get('notes', '')).strip()[:2000]
    followup = str(form.get('next_follow_up', '')).strip()
    followup_date = None
    if followup:
        try:
            followup_date = date.fromisoformat(followup)
        except ValueError:
            raise HTTPException(400, 'Invalid follow-up date')
    now = datetime.utcnow()
    db.add(CallLog(lead_id=lead.id, lead_phone=lead.phone or lead.mobile, direction='manual', status='completed', disposition=outcome, started_at=now, completed_at=now, notes=notes))
    lead.call_attempts = (lead.call_attempts or 0) + 1
    lead.last_contact = now
    lead.status = OUTCOMES[outcome]
    lead.updated = now
    if followup_date:
        lead.next_follow_up = followup_date
    if notes:
        lead.notes = ((lead.notes or '') + '\n' + f'[{now:%Y-%m-%d %H:%M} UTC] {outcome}: {notes}').strip()
    item.completed_at = now
    item.outcome = outcome
    remaining = db.scalar(select(ManualCallItem.id).where(ManualCallItem.batch_id == batch.id, ManualCallItem.completed_at.is_(None), ManualCallItem.id != item.id).limit(1))
    if remaining is None:
        batch.completed_at = now
    db.commit()
    return RedirectResponse('/call-list?recorded=1', status_code=303)
