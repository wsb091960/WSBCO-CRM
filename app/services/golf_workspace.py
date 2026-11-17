"""Shared golf counts and filters. Opening a request never marks it contacted."""
from sqlalchemy import func, select

from app.golf_integration import GolfProfile
from app.models import Lead


def new_golf_request():
    return (
        (GolfProfile.stage == "Inquiry")
        & (Lead.status == "New")
        & Lead.last_contact.is_(None)
    )


def golf_summary(db):
    contacts = select(func.count()).select_from(GolfProfile).join(
        Lead, Lead.id == GolfProfile.lead_id
    )
    return {
        "golf_count": db.scalar(contacts),
        "new_golf_count": db.scalar(contacts.where(new_golf_request())),
    }
