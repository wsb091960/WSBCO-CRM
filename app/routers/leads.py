from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Lead

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _parse_date(value: str | None) -> date | None:
    value = _clean(value)
    if not value:
        return None
    return date.fromisoformat(value)


def _parse_datetime(value: str | None) -> datetime | None:
    value = _clean(value)
    if not value:
        return None
    return datetime.fromisoformat(value)


def _lead_from_form(form) -> dict:
    return {
        "first_name": _clean(form.get("first_name")),
        "last_name": _clean(form.get("last_name")),
        "spouse": _clean(form.get("spouse")),
        "date_of_birth": _parse_date(form.get("date_of_birth")),
        "medicare_effective_date": _parse_date(form.get("medicare_effective_date")),
        "medicare_mbi": _clean(form.get("medicare_mbi")).upper(),
        "medicaid_number": _clean(form.get("medicaid_number")),
        "plan_id": _clean(form.get("plan_id")).upper(),
        "phone": _clean(form.get("phone")),
        "mobile": _clean(form.get("mobile")),
        "email": _clean(form.get("email")).lower(),
        "address": _clean(form.get("address")),
        "city": _clean(form.get("city")),
        "state": _clean(form.get("state")).upper()[:2],
        "zip_code": _clean(form.get("zip_code")),
        "county": _clean(form.get("county")),
        "current_coverage": _clean(form.get("current_coverage")),
        "interested_supplement": form.get("interested_supplement") == "on",
        "interested_advantage": form.get("interested_advantage") == "on",
        "interested_pdp": form.get("interested_pdp") == "on",
        "interested_dental": form.get("interested_dental") == "on",
        "status": _clean(form.get("status")) or "New",
        "lead_source": _clean(form.get("lead_source")),
        "last_contact": _parse_datetime(form.get("last_contact")),
        "next_follow_up": _parse_date(form.get("next_follow_up")),
        "follow_up_type": _clean(form.get("follow_up_type")),
        "priority": _clean(form.get("priority")) or "Normal",
        "agent": _clean(form.get("agent")),
        "notes": _clean(form.get("notes")),
        "call_attempts": int(form.get("call_attempts") or 0),
    }


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    leads = db.scalars(select(Lead)).all()
    total = len(leads)
    new_count = sum(1 for lead in leads if lead.status == "New")
    follow_up_count = sum(1 for lead in leads if lead.next_follow_up is not None)
    high_priority_count = sum(1 for lead in leads if lead.priority == "High")

    recent = db.scalars(
        select(Lead).order_by(Lead.updated.desc()).limit(8)
    ).all()

    return templates.TemplateResponse(
        request=request,
        name="dashboard_v2.html",
        context={
            "total": total,
            "new_count": new_count,
            "follow_up_count": follow_up_count,
            "high_priority_count": high_priority_count,
            "recent": recent,
        },
    )


@router.get("/leads")
def list_leads(
    request: Request,
    q: str = Query(default=""),
    status: str = Query(default=""),
    db: Session = Depends(get_db),
):
    statement = select(Lead)

    if q.strip():
        search = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                Lead.first_name.ilike(search),
                Lead.last_name.ilike(search),
                Lead.phone.ilike(search),
                Lead.mobile.ilike(search),
                Lead.email.ilike(search),
                Lead.city.ilike(search),
                Lead.zip_code.ilike(search),
            )
        )

    if status.strip():
        statement = statement.where(Lead.status == status.strip())

    statement = statement.order_by(
        Lead.priority.desc(),
        Lead.next_follow_up.asc(),
        Lead.last_name.asc(),
        Lead.first_name.asc(),
    )

    leads = db.scalars(statement).all()

    return templates.TemplateResponse(
        request=request,
        name="leads.html",
        context={"leads": leads, "q": q, "status": status},
    )


@router.get("/leads/new")
def new_lead_form(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="lead_form.html",
        context={"lead": None, "page_title": "Add Contact"},
    )


@router.post("/leads/new")
async def create_lead(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    data = _lead_from_form(form)

    if not data["first_name"] or not data["last_name"]:
        return templates.TemplateResponse(
            request=request,
            name="lead_form.html",
            context={
                "lead": data,
                "page_title": "Add Contact",
                "error": "First name and last name are required.",
            },
            status_code=400,
        )

    lead = Lead(**data)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    return RedirectResponse(
        url=f"/leads/{lead.id}?saved=1",
        status_code=303,
    )


@router.get("/leads/{lead_id}")
def lead_detail(
    lead_id: int,
    request: Request,
    saved: int = Query(default=0),
    calling: int = Query(default=0),
    call_id: int = Query(default=0),
    call_error: str = Query(default=""),
    db: Session = Depends(get_db),
):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Contact not found")

    return templates.TemplateResponse(
        request=request,
        name="lead_detail.html",
        context={
            "lead": lead,
            "saved": bool(saved),
            "calling": bool(calling),
            "call_id": call_id,
            "call_error": call_error,
        },
    )


@router.get("/leads/{lead_id}/edit")
def edit_lead_form(
    lead_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Contact not found")

    return templates.TemplateResponse(
        request=request,
        name="lead_form.html",
        context={"lead": lead, "page_title": "Edit Contact"},
    )


@router.post("/leads/{lead_id}/edit")
async def update_lead(
    lead_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Contact not found")

    form = await request.form()
    data = _lead_from_form(form)

    if not data["first_name"] or not data["last_name"]:
        return templates.TemplateResponse(
            request=request,
            name="lead_form.html",
            context={
                "lead": {**data, "id": lead_id},
                "page_title": "Edit Contact",
                "error": "First name and last name are required.",
            },
            status_code=400,
        )

    for field, value in data.items():
        setattr(lead, field, value)

    lead.updated = datetime.utcnow()
    db.commit()

    return RedirectResponse(
        url=f"/leads/{lead.id}?saved=1",
        status_code=303,
    )


@router.post("/leads/{lead_id}/delete")
def delete_lead(
    lead_id: int,
    db: Session = Depends(get_db),
):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Contact not found")

    db.delete(lead)
    db.commit()
    return RedirectResponse(url="/leads", status_code=303)
