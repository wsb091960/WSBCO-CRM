"""Read-only county coverage and recorded outreach, with explicit data gaps."""
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

from sqlalchemy import inspect, select, text

from app.call_list_gis import county_key, state_code
from app.database import DATA_DIR
from app.gis_map import _fingerprint
from app.golf_integration import GolfProfile
from app.models import CallLog, Lead

PACIFIC = ZoneInfo('America/Los_Angeles')
ACTIVITY_DB = DATA_DIR / 'wsbco_activity.db'


def utc_now():
    return datetime.now(timezone.utc)


def timestamp(value):
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def activity_events():
    """Never create an activity database/table while viewing a territory."""
    con = None
    try:
        con = sqlite3.connect(Path(ACTIVITY_DB).resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
        rows = con.execute("SELECT lead_id, created_at FROM activities WHERE activity_type IN ('call','email')").fetchall()
        return rows, True
    except sqlite3.Error:
        return [], False
    finally:
        if con is not None:
            con.close()


def coverage(db, state, counties, days, now=None):
    now = now or utc_now()
    today = now.astimezone(PACIFIC).date()
    first = today - timedelta(days=days - 1)
    start = datetime.combine(first, time.min, PACIFIC).astimezone(timezone.utc)
    golf = select(GolfProfile.id).where(GolfProfile.lead_id == Lead.id).exists()
    leads = {l.id: l for l in db.scalars(select(Lead).where(~golf)) if state_code(l.state) == state}
    latest, calls = {}, {}

    def record(lead_id, value):
        moment = timestamp(value)
        if lead_id in leads and moment and moment <= now:
            latest[lead_id] = max(latest.get(lead_id, moment), moment)
            return moment
        return None

    for lead in leads.values():
        record(lead.id, lead.last_contact)
    for call in db.scalars(select(CallLog).join(Lead, Lead.id == CallLog.lead_id).where(~golf)):
        # A failed API setup or abandoned draft is not evidence of outreach.
        if (call.status or '').lower() in {'creating', 'failed', 'canceled', 'cancelled'}:
            continue
        moment = record(call.lead_id, call.started_at)
        if moment and moment >= start:
            calls[call.lead_id] = calls.get(call.lead_id, 0) + 1
    events, activity_available = activity_events()
    for lead_id, value in events:
        record(lead_id, value)

    connection = db.connection()
    cached = {}
    if inspect(connection).has_table('gis_address_points'):
        cached = dict(db.execute(text('SELECT lead_id,address_hash FROM gis_address_points')).all())
    conflicts = set()
    if inspect(connection).has_table('contact_geocoding_jobs'):
        conflicts = set(db.execute(text("SELECT lead_id FROM contact_geocoding_jobs WHERE reason='county_conflict'")).scalars())
    county_ids = {county_key(c['name']): c['id'] for c in counties}
    county_names = {c['id']: c['name'] for c in counties}
    stats = {c['id']: {'contacts': 0, 'worked': 0, 'gap': 0, 'calls': 0, 'dnc': 0, 'last_worked': ''} for c in counties}
    contacts, unresolved = [], 0
    for lead in leads.values():
        cid = county_ids.get(county_key(lead.county))
        if lead.id in conflicts or (lead.id in cached and cached[lead.id] != _fingerprint(lead)):
            cid = None
        if cid is None:
            unresolved += 1
            continue
        moment = latest.get(lead.id)
        worked = bool(moment and moment >= start)
        last = moment.astimezone(PACIFIC).isoformat(timespec='seconds') if moment else ''
        dnc = (lead.status or '').strip().lower() == 'do not call'
        row = stats[cid]
        row['contacts'] += 1
        row['worked'] += int(worked)
        row['gap'] += int(not worked)
        row['calls'] += calls.get(lead.id, 0)
        row['dnc'] += int(dnc)
        if moment and (not row['last_worked'] or moment > timestamp(row['last_worked'])):
            row['last_worked'] = last
        contacts.append({'id': lead.id, 'county_id': cid, 'county': county_names[cid],
                         'name': ' '.join(p for p in (lead.first_name, lead.last_name) if p).strip(),
                         'status': lead.status or '', 'city': lead.city or '', 'phone': lead.phone or lead.mobile or '',
                         'worked': worked, 'last_worked': last, 'dnc': dnc, 'url': f'/leads/{lead.id}'})
    contacts.sort(key=lambda c: (c['worked'], c['last_worked'], c['name'].casefold(), c['id']))
    return {'counties': stats, 'contacts': contacts, 'unresolved': unresolved,
            'activity_available': activity_available, 'today': today, 'start': first,
            'as_of': now.astimezone(PACIFIC).isoformat(timespec='seconds')}
