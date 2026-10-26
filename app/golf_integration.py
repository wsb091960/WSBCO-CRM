"""CRMDevLog #12: golf inquiries and explicit student sync (opt-in, no insurance mutation)."""
import os
import secrets
import json
import re
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base, get_db
from app.models import Lead

router = APIRouter(prefix="/golf", tags=["Golf CRM"])


class GolfProfile(Base):
    __tablename__ = "golf_profiles"
    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, unique=True, nullable=False, index=True)
    stage = Column(String(40), nullable=False, default="Inquiry")
    program = Column(String(100), nullable=False, default="Individual lesson")
    goal = Column(Text, nullable=False, default="")
    golf_student_id = Column(String(64), nullable=False, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class Inquiry(BaseModel):
    submission_id: str = Field(min_length=1, max_length=200)
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(default="", max_length=80)
    email: str = Field(default="", max_length=255)
    phone: str = Field(default="", max_length=32)
    program: str = Field(default="Individual lesson", max_length=100)
    goal: str = Field(default="", max_length=2000)
    experience: str = Field(default="", max_length=100)
    preferred_contact: str = Field(default="", max_length=100)

    @field_validator("submission_id", "first_name", "last_name", "email", "phone", "program", "goal", "experience", "preferred_contact", mode="before")
    @classmethod
    def trim_text(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("phone")
    @classmethod
    def valid_phone(cls, value):
        if not 10 <= len(re.sub(r"\D", "", value)) <= 15:
            raise ValueError("A valid phone number is required")
        return value

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        if value:
            from email_validator import validate_email, EmailNotValidError
            try:
                return validate_email(value, check_deliverability=False).normalized
            except EmailNotValidError as exc:
                raise ValueError("Invalid email address") from exc
        return value


class GolfInquiryReceipt(Base):
    """One immutable receipt per Google Form response, including retry deliveries."""
    __tablename__ = "golf_inquiry_receipts"
    submission_id = Column(String(200), primary_key=True)
    lead_id = Column(Integer, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


def require_key(value: str | None, expected_env: str):
    expected = os.getenv(expected_env, "").strip()
    if not expected or not value or not secrets.compare_digest(value, expected):
        raise HTTPException(status_code=403, detail="Integration authentication required")


@router.post("/inquiries", status_code=201)
def create_inquiry(payload: Inquiry, x_golf_form_key: str | None = Header(default=None),
                   db: Session = Depends(get_db)):
    """Server-side Google Apps Script webhook; do not embed secret in public form."""
    require_key(x_golf_form_key, "GOLF_FORM_WEBHOOK_KEY")
    previous = db.get(GolfInquiryReceipt, payload.submission_id)
    if previous:
        return {"crm_contact_id": previous.lead_id, "golf_stage": "Inquiry", "already_saved": True}
    notes = "\n".join([
        "Golf lesson inquiry — Reedsport Golf Course",
        "Program: " + payload.program,
        "Experience: " + (payload.experience or "Not provided"),
        "Preferred contact: " + (payload.preferred_contact or "Not provided"),
        "Golf goals: " + (payload.goal or "Not provided"),
    ])
    lead = Lead(first_name=payload.first_name.strip(), last_name=payload.last_name.strip(),
                email=payload.email.strip(), phone=payload.phone.strip(),
                lead_source="Reedsport Golf lesson form", status="New", notes=notes)
    db.add(lead)
    db.flush()
    db.add(GolfProfile(lead_id=lead.id, program=payload.program.strip(),
                       goal=payload.goal.strip()))
    db.add(GolfInquiryReceipt(submission_id=payload.submission_id, lead_id=lead.id))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        previous = db.get(GolfInquiryReceipt, payload.submission_id)
        if not previous:
            raise
        return {"crm_contact_id": previous.lead_id, "golf_stage": "Inquiry", "already_saved": True}
    return {"crm_contact_id": lead.id, "golf_stage": "Inquiry", "already_saved": False}


@router.get("/contacts")
def golf_contacts(x_golf_admin_key: str | None = Header(default=None),
                  db: Session = Depends(get_db)):
    require_key(x_golf_admin_key, "GOLF_ADMIN_API_KEY")
    rows = db.query(GolfProfile, Lead).join(Lead, Lead.id == GolfProfile.lead_id).all()
    return [{"crm_contact_id": lead.id, "name": f"{lead.first_name} {lead.last_name}".strip(),
             "phone": lead.phone, "email": lead.email, "stage": profile.stage,
             "program": profile.program, "goal": profile.goal,
             "golf_student_id": profile.golf_student_id} for profile, lead in rows]


@router.post("/contacts/{lead_id}/convert")
def convert_to_student(lead_id: int, x_golf_admin_key: str | None = Header(default=None),
                       db: Session = Depends(get_db)):
    require_key(x_golf_admin_key, "GOLF_ADMIN_API_KEY")
    profile = db.query(GolfProfile).filter_by(lead_id=lead_id).first()
    lead = db.get(Lead, lead_id)
    if not profile or not lead:
        raise HTTPException(404, "Golf contact not found")
    if profile.golf_student_id:
        return {"crm_contact_id": lead_id, "golf_student_id": profile.golf_student_id,
                "already_linked": True}
    url = os.getenv("GOLF_COACH_API_URL", "").rstrip("/")
    token = os.getenv("GOLF_COACH_SYNC_KEY", "").strip()
    if not url or not token or not url.startswith("https://"):
        raise HTTPException(503, "Golf Coach HTTPS URL and sync key must be configured")
    data = json.dumps({"crm_contact_id": lead.id, "first_name": lead.first_name,
                       "last_name": lead.last_name, "email": lead.email,
                       "phone": lead.phone, "primary_goal": profile.goal}).encode()
    request = Request(url + "/integrations/crm/students", data=data, method="POST",
                      headers={"Content-Type": "application/json", "X-Golf-Sync-Key": token})
    try:
        with urlopen(request, timeout=15) as response:
            result = json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise HTTPException(502, "Golf Coach sync unavailable") from exc
    student_id = result.get("student_id")
    if not student_id:
        raise HTTPException(502, "Golf Coach returned no student ID")
    profile.golf_student_id = str(student_id)
    profile.stage = "Active student"
    db.commit()
    return {"crm_contact_id": lead_id, "golf_student_id": student_id, "already_linked": False}
