from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    first_name: Mapped[str] = mapped_column(String(80), default="", index=True)
    last_name: Mapped[str] = mapped_column(String(80), default="", index=True)
    spouse: Mapped[str] = mapped_column(String(160), default="")
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    medicare_effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    medicare_mbi: Mapped[str] = mapped_column(String(32), default="")
    medicaid_number: Mapped[str] = mapped_column(String(64), default="")
    plan_id: Mapped[str] = mapped_column(String(40), default="")

    phone: Mapped[str] = mapped_column(String(32), default="", index=True)
    mobile: Mapped[str] = mapped_column(String(32), default="")
    email: Mapped[str] = mapped_column(String(255), default="")

    address: Mapped[str] = mapped_column(String(255), default="")
    city: Mapped[str] = mapped_column(String(100), default="")
    state: Mapped[str] = mapped_column(String(2), default="OR")
    zip_code: Mapped[str] = mapped_column(String(10), default="")
    county: Mapped[str] = mapped_column(String(100), default="")

    current_coverage: Mapped[str] = mapped_column(String(255), default="")
    interested_supplement: Mapped[bool] = mapped_column(Boolean, default=False)
    interested_advantage: Mapped[bool] = mapped_column(Boolean, default=False)
    interested_pdp: Mapped[bool] = mapped_column(Boolean, default=False)
    interested_dental: Mapped[bool] = mapped_column(Boolean, default=False)

    status: Mapped[str] = mapped_column(String(50), default="New", index=True)
    lead_source: Mapped[str] = mapped_column(String(100), default="")
    last_contact: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_follow_up: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    follow_up_type: Mapped[str] = mapped_column(String(100), default="")
    priority: Mapped[str] = mapped_column(String(20), default="Normal", index=True)
    agent: Mapped[str] = mapped_column(String(120), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    call_attempts: Mapped[int] = mapped_column(Integer, default=0)

    created: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class CallLog(Base):
    __tablename__ = "call_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    lead_id: Mapped[int] = mapped_column(Integer, index=True)

    twilio_call_sid: Mapped[str] = mapped_column(String(64), default="", index=True)
    agent_phone: Mapped[str] = mapped_column(String(32), default="")
    lead_phone: Mapped[str] = mapped_column(String(32), default="")

    direction: Mapped[str] = mapped_column(String(30), default="outbound-api")
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    disposition: Mapped[str] = mapped_column(String(60), default="")
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)

    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    notes: Mapped[str] = mapped_column(Text, default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
