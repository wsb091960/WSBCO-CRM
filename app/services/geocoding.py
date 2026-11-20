"""Transactional contact geocoding queue, processed outside contact saves.

Only address fields are sent to Esri. Jobs survive restarts, and a lease plus
address fingerprint prevents concurrent or outdated lookups overwriting a pin.
"""
import json
import logging
import math
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import Float, Integer, String, event, inspect, or_, select, text, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

log = logging.getLogger("uvicorn.error.geocoding")
ADDRESS_FIELDS = ("address", "city", "state", "zip_code")


class GeocodingJob(Base):
    __tablename__ = "contact_geocoding_jobs"
    lead_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    address_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), index=True)
    reason: Mapped[str] = mapped_column(String(40), default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt: Mapped[float] = mapped_column(Float, default=0, index=True)
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    lease_token: Mapped[str] = mapped_column(String(64), default="")


def address_state(lead):
    parts = {k: str(getattr(lead, k, "") or "").strip() for k in ADDRESS_FIELDS}
    if parts["address"].casefold() in {"", "unknown", "n/a", "none", "-", "—"}:
        return "incomplete"
    if re.search(r"\b(?:p\.?\s*o\.?\s*box|post\s+office\s+box)\b", parts["address"], re.I):
        return "po_box"
    if not ((parts["city"] and parts["state"]) or re.fullmatch(r"\d{5}(?:-\d{4})?", parts["zip_code"])):
        return "incomplete"
    return "pending"


def install_contact_hooks(lead_model):
    def enqueue(mapper, connection, lead):
        from app.gis_map import _fingerprint
        status = address_state(lead)
        values = dict(lead_id=lead.id, address_hash=_fingerprint(lead),
                      status="review" if status == "po_box" else status,
                      reason=status if status != "pending" else "", attempts=0,
                      next_attempt=0, lease_until=0, lease_token="")
        statement = insert(GeocodingJob).values(**values)
        connection.execute(statement.on_conflict_do_update(
            index_elements=["lead_id"], set_={k: v for k, v in values.items() if k != "lead_id"}))

    def address_changed(mapper, connection, lead):
        if any(inspect(lead).attrs[k].history.has_changes() for k in ADDRESS_FIELDS):
            enqueue(mapper, connection, lead)

    def removed(mapper, connection, lead):
        connection.execute(GeocodingJob.__table__.delete().where(GeocodingJob.lead_id == lead.id))

    event.listen(lead_model, "after_insert", enqueue)
    event.listen(lead_model, "after_update", address_changed)
    event.listen(lead_model, "after_delete", removed)


def lookup_address(lead):
    """Conservative street match; ambiguous/ZIP-level/PO-box results need review."""
    from app.call_list_gis import state_code, zip5
    from app.gis_map import _address
    token = os.getenv("ARCGIS_API_KEY", "").strip()
    if not token:
        return {"status": "retry", "reason": "configuration"}
    payload = urlencode({"SingleLine": _address(lead), "outFields": "Addr_type,Region,Postal,Subregion",
                         "f": "json", "token": token, "outSR": "4326",
                         "forStorage": "true", "maxLocations": "2"}).encode()
    request = Request(
        "https://geocode-api.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates",
        data=payload, headers={"Content-Type": "application/x-www-form-urlencoded",
                              "User-Agent": "WSBCO-CRM-Geocoding/1.0"})
    try:
        with urlopen(request, timeout=12) as response:
            result = json.load(response)
        if result.get("error"):
            reason = "configuration" if result["error"].get("code") in (401, 403, 498, 499) else "service_error"
            return {"status": "retry", "reason": reason}
        candidates = result.get("candidates") or []
        if not candidates:
            return {"status": "review", "reason": "no_match"}
        candidate = candidates[0]
        attr, location = candidate.get("attributes") or {}, candidate.get("location") or {}
        score = float(candidate.get("score") or 0)
        lat, lon = location.get("y"), location.get("x")
        if (not math.isfinite(score) or score < 95
                or attr.get("Addr_type") not in ("PointAddress", "StreetAddress")
                or (lead.state and state_code(attr.get("Region")) != state_code(lead.state))
                or (lead.zip_code and zip5(attr.get("Postal")) != zip5(lead.zip_code))
                or type(lat) not in (int, float) or type(lon) not in (int, float)
                or not math.isfinite(lat) or not math.isfinite(lon)
                or not -90 <= lat <= 90 or not -180 <= lon <= 180 or (lat == 0 and lon == 0)):
            return {"status": "review", "reason": "uncertain_match"}
        for other in candidates[1:]:
            other_location = other.get("location") or {}
            if (float(other.get("score") or 0) >= score - 3
                    and (other_location.get("x"), other_location.get("y")) != (lon, lat)):
                return {"status": "review", "reason": "ambiguous"}
        return {"status": "matched", "reason": "", "lat": float(lat), "lon": float(lon),
                "score": score, "match_type": attr["Addr_type"],
                "county": str(attr.get("Subregion") or "").strip()[:100]}
    except Exception:
        # Never log request URLs, provider bodies, addresses, or credentials.
        return {"status": "retry", "reason": "service_error"}


def initialize_cache(engine):
    from sqlalchemy.orm import Session
    from app.gis_map import _cache
    with Session(engine) as db:
        _cache(db)
        db.execute(text('''CREATE TABLE IF NOT EXISTS gis_coordinate_sources (
            lead_id INTEGER PRIMARY KEY, address_hash TEXT NOT NULL,
            source TEXT NOT NULL, checked_at TEXT, precision TEXT)'''))
        db.commit()


def process_next(engine, lookup=None, now=None):
    """Claim one committed job, release DB before HTTP, then verify address/lease."""
    from sqlalchemy.orm import Session
    from app.call_list_gis import county_key
    from app.gis_map import _fingerprint
    from app.models import Lead
    now = time.time() if now is None else now
    lookup = lookup or lookup_address
    ready = or_(GeocodingJob.status.in_(["pending", "retry"]),
                (GeocodingJob.status == "processing") & (GeocodingJob.lease_until <= now))
    token = secrets.token_hex(16)
    with Session(engine) as db:
        job_id = db.scalar(select(GeocodingJob.lead_id).where(
            ready, GeocodingJob.next_attempt <= now).order_by(
            GeocodingJob.next_attempt, GeocodingJob.lead_id).limit(1))
        if job_id is None:
            return False
        claim = db.execute(update(GeocodingJob).where(
            GeocodingJob.lead_id == job_id, ready, GeocodingJob.next_attempt <= now).values(
            status="processing", lease_token=token, lease_until=now + 120,
            attempts=GeocodingJob.attempts + 1))
        db.commit()
        if claim.rowcount != 1:
            return True
        lead = db.get(Lead, job_id)
        job = db.get(GeocodingJob, job_id)
        if lead is None:
            if job:
                db.delete(job)
            db.commit()
            return True
        fingerprint = job.address_hash
        db.expunge(lead)
    try:
        result = lookup(lead)
    except Exception:
        result = {"status": "retry", "reason": "service_error"}
    with Session(engine) as db:
        # Serialize only the short result write against a concurrent address edit.
        db.execute(text("BEGIN IMMEDIATE"))
        job, current = db.get(GeocodingJob, job_id), db.get(Lead, job_id)
        if (not job or not current or job.lease_token != token
                or job.address_hash != fingerprint or _fingerprint(current) != fingerprint):
            db.rollback()
            return True
        job.status, job.reason = result["status"], result["reason"]
        job.lease_until, job.lease_token = 0, ""
        if job.status == "retry":
            delay = 3600 if job.reason == "configuration" else min(3600, 30 * 2 ** min(job.attempts - 1, 7))
            job.next_attempt = now + delay
        elif job.status == "matched":
            county = result.get("county", "")
            if county and not (current.county or "").strip():
                current.county = county
            elif county and county_key(county) != county_key(current.county):
                job.reason = "county_conflict"
            db.execute(text('''INSERT INTO gis_address_points
                (lead_id,address_hash,latitude,longitude,score,match_type,result)
                VALUES (:id,:hash,:lat,:lon,:score,:type,'matched')
                ON CONFLICT(lead_id) DO UPDATE SET address_hash=excluded.address_hash,
                latitude=excluded.latitude,longitude=excluded.longitude,score=excluded.score,
                match_type=excluded.match_type,result=excluded.result'''),
                {"id": job_id, "hash": fingerprint, "lat": result["lat"], "lon": result["lon"],
                 "score": result["score"], "type": result["match_type"]})
            precision = "Address point" if result["match_type"] == "PointAddress" else "Estimated street-range location"
            db.execute(text('''INSERT INTO gis_coordinate_sources
                (lead_id,address_hash,source,checked_at,precision) VALUES (:id,:hash,:source,:checked,:precision)
                ON CONFLICT(lead_id) DO UPDATE SET address_hash=excluded.address_hash,
                source=excluded.source,checked_at=excluded.checked_at,precision=excluded.precision'''),
                {"id": job_id, "hash": fingerprint, "source": "Esri World Geocoding Service",
                 "checked": datetime.now(timezone.utc).isoformat(), "precision": precision})
        db.commit()
    log.info("Contact geocoding job completed: %s", result["status"])
    return True


def contact_geocoding_status(db, lead):
    from app.gis_map import _fingerprint
    job = db.get(GeocodingJob, lead.id)
    if job and job.address_hash == _fingerprint(lead):
        if job.status == "matched":
            return ("Address located. Saved county differs from the address match; review the county."
                    if job.reason == "county_conflict" else "Address located")
        if job.status == "incomplete":
            return "Address needed — add a street address and city/state or ZIP."
        if job.status == "review":
            return ("Address needs review — use a residential street address instead of a PO box."
                    if job.reason == "po_box" else "Address needs review — confirm the street address, city, state and ZIP.")
        if job.status == "retry":
            return "Address lookup delayed — it will retry automatically."
        return "Locating address — refresh shortly."
    if inspect(db.connection()).has_table("gis_address_points"):
        row = db.execute(text("SELECT address_hash,result FROM gis_address_points WHERE lead_id=:id"),
                         {"id": lead.id}).first()
        if row and row[0] == _fingerprint(lead):
            return "Address located" if row[1] == "matched" else "Address needs review"
    return "Address has not been geocoded. Automatic lookup runs for new contacts and address changes."


class GeocodingWorker:
    def __init__(self, engine):
        self.engine = engine
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, name="contact-geocoding", daemon=True)

    def start(self):
        initialize_cache(self.engine)
        self.thread.start()
        if os.getenv("ARCGIS_API_KEY", "").strip():
            log.info("Automatic contact geocoding worker started; Esri is configured")
        else:
            log.warning("Automatic contact geocoding is waiting for Esri configuration")

    def run(self):
        while not self.stop_event.is_set():
            try:
                process_next(self.engine)
            except Exception:
                log.warning("Contact geocoding temporarily unavailable; retrying")
            self.stop_event.wait(2)

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=15)
