from datetime import datetime
from urllib.parse import urljoin

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session
from twilio.request_validator import RequestValidator
from twilio.twiml.voice_response import VoiceResponse

from app.database import get_db
from app.models import CallLog, Lead
from app.services.phone_service import normalize_us_phone
from app.services.settings import get_settings
from app.services.twilio_service import (
    TwilioConfigurationError,
    TwilioDialer,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

ELIGIBLE_STATUSES = ("New", "Attempt Again", "Callback", "Interested")


async def _validate_twilio_request(request: Request) -> None:
    settings = get_settings()
    if not settings.validate_signatures:
        return

    signature = request.headers.get("X-Twilio-Signature", "")
    form = await request.form()
    public_url = f"{settings.base_url}{request.url.path}"
    if request.url.query:
        public_url += f"?{request.url.query}"

    validator = RequestValidator(settings.auth_token)
    if not validator.validate(public_url, dict(form), signature):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")


def _begin_call(db: Session, lead: Lead) -> CallLog:
    phone_source = lead.phone or lead.mobile
    if not phone_source:
        raise ValueError("This contact does not have a phone number.")

    lead_phone = normalize_us_phone(phone_source)
    settings = get_settings()

    call_log = CallLog(
        lead_id=lead.id,
        agent_phone=settings.agent_number,
        lead_phone=lead_phone,
        status="creating",
        started_at=datetime.utcnow(),
    )
    db.add(call_log)
    db.flush()

    try:
        twilio_call = TwilioDialer(settings).start_agent_first_call(call_log.id)
    except Exception as exc:
        call_log.status = "failed"
        call_log.error_message = str(exc)
        db.commit()
        raise

    call_log.twilio_call_sid = twilio_call.sid
    call_log.status = twilio_call.status or "queued"

    lead.call_attempts = (lead.call_attempts or 0) + 1
    lead.last_contact = datetime.utcnow()
    lead.status = "In Progress"
    lead.updated = datetime.utcnow()

    db.commit()
    db.refresh(call_log)
    return call_log


@router.get("/dialer")
def dialer_dashboard(request: Request, db: Session = Depends(get_db)):
    next_lead = db.scalar(
        select(Lead)
        .where(Lead.status.in_(ELIGIBLE_STATUSES))
        .order_by(
            Lead.next_follow_up.asc(),
            Lead.priority.desc(),
            Lead.id.asc(),
        )
        .limit(1)
    )
    history = db.scalars(
        select(CallLog).order_by(CallLog.started_at.desc()).limit(20)
    ).all()
    lead_names = {
        lead.id: f"{lead.first_name} {lead.last_name}"
        for lead in db.scalars(select(Lead)).all()
    }

    return templates.TemplateResponse(
        request=request,
        name="dialer.html",
        context={
            "next_lead": next_lead,
            "history": history,
            "lead_names": lead_names,
            "configured": get_settings().is_complete,
        },
    )


@router.post("/dialer/call-next")
def call_next_lead(db: Session = Depends(get_db)):
    lead = db.scalar(
        select(Lead)
        .where(Lead.status.in_(ELIGIBLE_STATUSES))
        .order_by(
            Lead.next_follow_up.asc(),
            Lead.priority.desc(),
            Lead.id.asc(),
        )
        .limit(1)
    )

    if not lead:
        return RedirectResponse(
            url="/dialer?error=No+eligible+leads+are+available.",
            status_code=303,
        )

    try:
        call_log = _begin_call(db, lead)
    except (ValueError, TwilioConfigurationError) as exc:
        return RedirectResponse(
            url=f"/leads/{lead.id}?call_error={str(exc)}",
            status_code=303,
        )
    except Exception as exc:
        return RedirectResponse(
            url=f"/leads/{lead.id}?call_error=Twilio+call+failed",
            status_code=303,
        )

    return RedirectResponse(
        url=f"/leads/{lead.id}?calling=1&call_id={call_log.id}",
        status_code=303,
    )


@router.post("/leads/{lead_id}/call")
def call_selected_lead(lead_id: int, db: Session = Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Contact not found")

    if lead.status == "Do Not Call":
        return RedirectResponse(
            url=f"/leads/{lead.id}?call_error=Contact+is+marked+Do+Not+Call",
            status_code=303,
        )

    try:
        call_log = _begin_call(db, lead)
    except (ValueError, TwilioConfigurationError) as exc:
        return RedirectResponse(
            url=f"/leads/{lead.id}?call_error={str(exc)}",
            status_code=303,
        )
    except Exception:
        return RedirectResponse(
            url=f"/leads/{lead.id}?call_error=Twilio+call+failed",
            status_code=303,
        )

    return RedirectResponse(
        url=f"/leads/{lead.id}?calling=1&call_id={call_log.id}",
        status_code=303,
    )


@router.post("/twilio/connect/{call_log_id}")
async def connect_agent_to_lead(
    call_log_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    await _validate_twilio_request(request)

    call_log = db.get(CallLog, call_log_id)
    if not call_log:
        response = VoiceResponse()
        response.say("The contact record could not be found.")
        response.hangup()
        return Response(str(response), media_type="application/xml")

    settings = get_settings()
    response = VoiceResponse()
    response.say("WSBCO dialer. Connecting your contact now.")

    dial = response.dial(
        caller_id=settings.twilio_number,
        answer_on_bridge=True,
        timeout=30,
    )
    dial.number(call_log.lead_phone)

    return Response(str(response), media_type="application/xml")


@router.post("/twilio/status/{call_log_id}")
async def twilio_status_callback(
    call_log_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    await _validate_twilio_request(request)
    form = await request.form()

    call_log = db.get(CallLog, call_log_id)
    if not call_log:
        return Response(status_code=204)

    status = str(form.get("CallStatus") or "").strip()
    call_sid = str(form.get("CallSid") or "").strip()
    duration = str(form.get("CallDuration") or "0").strip()

    if call_sid:
        call_log.twilio_call_sid = call_sid
    if status:
        call_log.status = status

    if status == "in-progress" and call_log.answered_at is None:
        call_log.answered_at = datetime.utcnow()

    if status in {"completed", "busy", "failed", "no-answer", "canceled"}:
        call_log.completed_at = datetime.utcnow()
        try:
            call_log.duration_seconds = int(duration)
        except ValueError:
            call_log.duration_seconds = 0

    db.commit()
    return Response(status_code=204)


@router.post("/calls/{call_log_id}/disposition")
async def save_disposition(
    call_log_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    call_log = db.get(CallLog, call_log_id)
    if not call_log:
        raise HTTPException(status_code=404, detail="Call not found")

    lead = db.get(Lead, call_log.lead_id)
    form = await request.form()

    disposition = str(form.get("disposition") or "").strip()
    notes = str(form.get("notes") or "").strip()
    next_follow_up = str(form.get("next_follow_up") or "").strip()

    call_log.disposition = disposition
    call_log.notes = notes

    if lead:
        status_map = {
            "No Answer": "Attempt Again",
            "Voicemail": "Attempt Again",
            "Callback": "Callback",
            "Appointment Set": "Appointment Set",
            "Interested": "Interested",
            "Not Interested": "Not Interested",
            "Do Not Call": "Do Not Call",
            "Wrong Number": "Wrong Number",
            "Sold": "Sold",
        }
        lead.status = status_map.get(disposition, lead.status)
        if notes:
            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
            entry = f"[{timestamp}] {disposition}: {notes}"
            lead.notes = f"{lead.notes}\n\n{entry}".strip()
        if next_follow_up:
            lead.next_follow_up = datetime.fromisoformat(next_follow_up).date()
        lead.updated = datetime.utcnow()

    db.commit()
    return RedirectResponse(
        url=f"/leads/{call_log.lead_id}?saved=1",
        status_code=303,
    )
