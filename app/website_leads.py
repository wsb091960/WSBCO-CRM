"""Public website lead intake; no medical identifiers collected."""
import os
import re
import time
from collections import defaultdict, deque
from threading import Lock
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, EmailStr, field_validator
from sqlalchemy import or_
from app.database import SessionLocal
from app.models import Lead

router = APIRouter(prefix="/api/website", tags=["website leads"])
ALLOWED_ORIGINS = {"https://turning65medicaremadeeasy.com", "https://www.turning65medicaremadeeasy.com"}
WINDOW = 3600
MAX_REQUESTS = 12
hits = defaultdict(deque)
lock = Lock()

class WebsiteLead(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    phone: str = Field(min_length=7, max_length=32)
    email: EmailStr
    zip_code: str = Field(pattern=r"^\d{5}$")
    state: str = Field(default="OR", pattern=r"^[A-Z]{2}$")
    interests: list[str] = Field(default_factory=list, max_length=4)
    preferred_contact: str = Field(default="Phone", pattern=r"^(Phone|Email)$")
    consent: bool
    website: str = Field(default="", max_length=120)  # honeypot
    started_at: int = 0

    @field_validator("first_name", "last_name")
    @classmethod
    def clean_name(cls, v):
        v = v.strip()
        if not v or any(ord(c) < 32 for c in v): raise ValueError("Invalid name")
        return v

    @field_validator("interests")
    @classmethod
    def clean_interests(cls, values):
        valid={"Medicare Supplement", "Medicare Advantage", "Prescription Drug Plans", "Dental"}
        if any(v not in valid for v in values): raise ValueError("Invalid interest")
        return list(dict.fromkeys(values))

@router.post("/leads", status_code=201)
def create_website_lead(payload: WebsiteLead, request: Request):
    origin = request.headers.get("origin", "")
    if origin not in ALLOWED_ORIGINS:
        raise HTTPException(403, "Origin not allowed")
    if not payload.consent:
        raise HTTPException(422, "Contact permission required")
    if payload.website:
        return {"message": "Thank you. Your request has been received."}
    now=time.time()
    if payload.started_at and (now - payload.started_at < 3 or now - payload.started_at > 86400):
        raise HTTPException(400, "Please refresh and try again")
    ip=request.client.host if request.client else "unknown"
    with lock:
        q=hits[ip]
        while q and q[0] < now-WINDOW: q.popleft()
        if len(q)>=MAX_REQUESTS: raise HTTPException(429, "Too many requests. Please try again later")
        q.append(now)
    db=SessionLocal()
    try:
        email=str(payload.email).strip().lower()
        phone_digits=re.sub(r"\D", "", payload.phone)
        if len(phone_digits)<10 or len(phone_digits)>15:
            raise HTTPException(422, "Enter a valid phone number")
        # Avoid silently overwriting existing contacts. Exact email match only.
        existing=db.query(Lead).filter(Lead.email==email).first()
        if existing:
            return {"message": "Thank you. Your request has been received."}
        interests=set(payload.interests)
        lead=Lead(first_name=payload.first_name, last_name=payload.last_name,
            phone=payload.phone.strip(), email=email, zip_code=payload.zip_code,
            state=payload.state, status="New Lead", priority="Normal",
            lead_source="Turning65MedicareMadeEasy.com",
            interested_supplement="Medicare Supplement" in interests,
            interested_advantage="Medicare Advantage" in interests,
            interested_pdp="Prescription Drug Plans" in interests,
            interested_dental="Dental" in interests,
            notes=f"Website contact form. Preferred contact: {payload.preferred_contact}. Consent to contact: yes.")
        db.add(lead)
        db.commit()
        return {"message": "Thank you. Your request has been received."}
    finally:
        db.close()
