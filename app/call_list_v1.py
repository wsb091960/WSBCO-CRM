from datetime import date, datetime
import json
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import DateTime, ForeignKey, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.exc import IntegrityError
from app.database import Base, get_db
from app.models import Lead, CallLog
from app.call_list_gis import (GeoFilter, ManualCallGeography, CallListZipLocation,
    STATE_NAMES, saved_filter, spatial_summary, fetch_zip_location, zip5)

router = APIRouter(prefix="/call-list")
templates = Jinja2Templates(directory="app/templates")
OUTCOMES = {"No Answer": "Attempt Again", "Busy": "Attempt Again", "Left Message": "Attempt Again", "Live Voicemail": "Attempt Again", "Callback": "Callback", "Interested": "Interested", "Appointment Set": "Appointment Set", "Not Interested": "Not Interested", "Do Not Call": "Do Not Call", "Wrong Number": "Wrong Number", "Disconnected": "Wrong Number", "Sold": "Sold"}
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

def candidates(db):
    today = date.today()
    contacted_today = set(db.scalars(select(CallLog.lead_id).where(CallLog.started_at >= datetime.combine(today, datetime.min.time()))).all())
    leads = db.scalars(select(Lead).where((Lead.phone != "") | (Lead.mobile != ""))).all()
    eligible = [l for l in leads if ((l.phone or '').strip() or (l.mobile or '').strip()) and (l.status or "").strip().lower() not in EXCLUDED and l.id not in contacted_today and (l.last_contact is None or l.last_contact.date() != today)]
    def score(l):
        due = l.next_follow_up
        group = 0 if due and due < today else 1 if due == today else 2 if (l.status or '').lower() == 'callback' else 3 if (l.status or '').lower() == 'new' else 4
        priority = 0 if (l.priority or '').lower() in {'urgent', 'high'} else 1
        return (group, priority, due or date.max, l.call_attempts or 0, l.id)
    return sorted(eligible, key=score)

def active_batch(db):
    return db.scalar(select(ManualCallBatch).where(ManualCallBatch.completed_at.is_(None)).order_by(ManualCallBatch.id.desc()).limit(1))

def render_list(request, db, form_data=None, error='', status_code=200):
    batch = active_batch(db)
    items = db.scalars(select(ManualCallItem).where(ManualCallItem.batch_id == batch.id).order_by(ManualCallItem.id)).all() if batch else []
    lead_ids = [i.lead_id for i in items]
    leads = {l.id: l for l in db.scalars(select(Lead).where(Lead.id.in_(lead_ids))).all()} if lead_ids else {}
    logs = db.scalars(select(CallLog).where(CallLog.lead_id.in_(lead_ids), CallLog.direction == 'manual')).all() if lead_ids else []
    log_by_call = {(log.lead_id, log.completed_at): log for log in logs}
    rows = [{"item": item, "lead": leads.get(item.lead_id),
             "log": log_by_call.get((item.lead_id, item.completed_at)) if item.completed_at else None} for item in items]
    done = sum(item.completed_at is not None for item in items)
    batch_geo = saved_filter(db, batch)
    source = form_data if form_data is not None else request.query_params
    explicit_search = any(key in source for key in ('state', 'county', 'city', 'zip_code', 'states', 'counties', 'cities', 'zips', 'geo_mode'))
    if not explicit_search:
        source = batch_geo.fields()
    try:
        geo = GeoFilter.search(source) if explicit_search else batch_geo
    except HTTPException as exc:
        geo, error, status_code = GeoFilter(), exc.detail, 400
    eligible = [] if error else [lead for lead in candidates(db) if geo.matches(lead)]
    summary = spatial_summary(eligible, rows)
    return templates.TemplateResponse(request=request, name="call_list_v1.html", status_code=status_code,
        context={"rows": rows, "batch": batch, "done": done, "available": len(eligible),
                 "outcomes": OUTCOMES, "filters": dict(source) if error else geo.fields(),
                 "geo_label": geo.label(), "batch_geo_label": batch_geo.label(),
                 "map_url": '/gis?' + urlencode(geo.map_fields()),
                 "summary": summary, "error": error, "state_names": STATE_NAMES})

@router.get("")
def call_list(request: Request, db: Session = Depends(get_db)):
    return render_list(request, db)

@router.post("/generate")
async def generate(request: Request, db: Session = Depends(get_db)):
    # An unfinished list must never be replaced by clicking Generate again.
    if active_batch(db):
        return RedirectResponse('/call-list', status_code=303)
    form = await request.form()
    try:
        geo = GeoFilter.search(form)
    except HTTPException:
        return render_list(request, db, form_data=form)
    leads = [lead for lead in candidates(db) if geo.matches(lead)][:10]
    if leads:
        batch = ManualCallBatch()
        db.add(batch)
        db.flush()
        db.add_all([ManualCallItem(batch_id=batch.id, lead_id=lead.id) for lead in leads])
        db.add(ManualCallGeography(batch_id=batch.id, filters_json=json.dumps(geo.fields())))
        db.commit()
    return RedirectResponse('/call-list?' + urlencode(geo.fields()), status_code=303)

@router.get('/gis/zip/{zip_code}')
def zip_location(zip_code: str, db: Session = Depends(get_db)):
    if len(zip_code) != 5 or zip5(zip_code) != zip_code:
        raise HTTPException(400, 'A five-digit US ZIP is required.')
    cached = db.get(CallListZipLocation, zip_code)
    if not cached:
        location = fetch_zip_location(zip_code)
        db.add(CallListZipLocation(**location))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()  # Another request may have cached this ZIP first.
        cached = db.get(CallListZipLocation, zip_code)
    return JSONResponse({'zip': cached.zip_code, 'lat': cached.latitude, 'lon': cached.longitude,
                         'state': cached.state, 'place': cached.place}, headers={'Cache-Control': 'no-store'})

@router.post("/{lead_id}/disposition")
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
