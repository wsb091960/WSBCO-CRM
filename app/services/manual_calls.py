"""One transaction for a manual call, its counters and saved-list progress."""
from datetime import date, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import String, Integer, select, update, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models import Lead, CallLog

OUTCOMES = ("Connected", "No Answer", "Busy", "Voicemail", "Left Message",
            "Live Voicemail", "Callback", "Interested", "Appointment Set",
            "Not Interested", "Do Not Call", "Wrong Number", "Disconnected", "Sold")
STATUS_CHANGES = {x: x for x in ("Callback", "Interested", "Appointment Set",
                                "Not Interested", "Do Not Call", "Wrong Number", "Sold")}
STATUS_CHANGES["Disconnected"] = "Wrong Number"


class ManualCallSubmission(Base):
    __tablename__ = "manual_call_submissions"
    token: Mapped[str] = mapped_column(String(80), primary_key=True)
    lead_id: Mapped[int] = mapped_column(Integer, index=True)


def usable_phone(lead):
    return next((str(p).strip() for p in (lead.mobile, lead.phone)
                 if sum(c.isdigit() for c in str(p or '')) >= 7), '')


def pending_item(db, lead_id):
    from app.call_list_v1 import ManualCallBatch, ManualCallItem
    return db.scalar(select(ManualCallItem).join(
        ManualCallBatch, ManualCallBatch.id == ManualCallItem.batch_id).where(
        ManualCallBatch.completed_at.is_(None), ManualCallItem.lead_id == lead_id,
        ManualCallItem.completed_at.is_(None)).order_by(ManualCallItem.id).limit(1))


def finish_batch(db, item, now):
    from app.call_list_v1 import ManualCallBatch, ManualCallItem
    remaining = db.scalar(select(ManualCallItem.id).where(
        ManualCallItem.batch_id == item.batch_id,
        ManualCallItem.completed_at.is_(None)).limit(1))
    if remaining is None:
        db.execute(update(ManualCallBatch).where(ManualCallBatch.id == item.batch_id)
                   .values(completed_at=now))


def save_manual_call(db, lead, form, *, item=None):
    from app.call_list_v1 import ManualCallItem
    outcome = str(form.get('outcome', '')).strip()
    if outcome not in OUTCOMES:
        raise HTTPException(400, 'Select a valid call disposition.')
    followup = str(form.get('next_follow_up', '')).strip()
    try:
        followup_date = date.fromisoformat(followup) if followup else None
    except ValueError:
        raise HTTPException(400, 'Invalid follow-up date.')
    token = str(form.get('submission_token', '')).strip()
    if token:
        previous = db.get(ManualCallSubmission, token)
        if previous:
            if previous.lead_id != lead.id:
                raise HTTPException(409, 'This call belongs to another contact.')
            return False
    # Saved list items have one stable key across both entry points.
    original_token = token
    if item:
        token = f'list-{item.id}'
    else:
        try:
            token = str(UUID(token))
        except ValueError:
            raise HTTPException(400, 'Reload the contact before logging a new call.')
    existing = db.get(ManualCallSubmission, token)
    if existing:
        if existing.lead_id != lead.id:
            raise HTTPException(409, 'This call was already submitted for another contact.')
        return False
    # Check again against current stored data, even if a page was left open.
    db.refresh(lead)
    if (lead.status or '').strip().lower() == 'do not call':
        raise HTTPException(403, 'Contact is marked Do Not Call.')
    phone = usable_phone(lead)
    if not phone:
        raise HTTPException(400, 'Add a usable phone number before recording a call.')
    notes = str(form.get('notes', '')).strip()[:2000]
    now = datetime.utcnow()
    if item and original_token and original_token != token:
        try:
            original_token = str(UUID(original_token))
        except ValueError:
            raise HTTPException(400, 'Invalid call form. Reload the contact.')
    db.add(ManualCallSubmission(token=token, lead_id=lead.id))
    if item and original_token and original_token != token:
        db.add(ManualCallSubmission(token=original_token, lead_id=lead.id))
    try:
        db.flush()  # Unique token serializes repeated submissions.
    except IntegrityError:
        db.rollback()
        existing = db.get(ManualCallSubmission, token)
        if existing and existing.lead_id == lead.id:
            return False
        raise HTTPException(409, 'Call save conflict. Reload the contact.')
    if item:
        claimed = db.execute(update(ManualCallItem).where(
            ManualCallItem.id == item.id, ManualCallItem.completed_at.is_(None))
            .values(completed_at=now, outcome=outcome))
        if claimed.rowcount != 1:
            db.rollback()
            raise HTTPException(409, 'This list entry is already completed or skipped.')
    db.add(CallLog(lead_id=lead.id, lead_phone=phone, direction='manual',
                   status='completed', disposition=outcome, started_at=now,
                   completed_at=now, notes=notes))
    values = dict(call_attempts=func.coalesce(Lead.call_attempts, 0) + 1,
                  last_contact=now, updated=now)
    if outcome in STATUS_CHANGES:
        values['status'] = STATUS_CHANGES[outcome]
    if followup_date:
        values['next_follow_up'] = followup_date
        values['follow_up_type'] = 'Call'
    if notes:
        values['notes'] = ((lead.notes or '') + '\n' +
                           f'[{now:%Y-%m-%d %H:%M} UTC] {outcome}: {notes}').strip()
    db.execute(update(Lead).where(Lead.id == lead.id).values(**values))
    db.flush()
    if item:
        finish_batch(db, item, now)
    db.commit()
    return True
