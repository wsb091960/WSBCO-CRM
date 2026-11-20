"""County market estimates and private, DOB-based contact targeting."""
from calendar import monthrange
from datetime import date, datetime
from functools import lru_cache
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import inspect, select, text

from app.call_list_gis import county_key, state_code
from app.gis_map import _fingerprint
from app.golf_integration import GolfProfile
from app.ma_county_map import load_catalog, load_geometry
from app.models import Lead

STATES = {'OR': 'Oregon', 'CA': 'California', 'WV': 'West Virginia', 'TX': 'Texas'}
FIPS = {'OR': '41', 'CA': '06', 'WV': '54', 'TX': '48'}
DATA_DIR = Path(__file__).resolve().parents[1] / 'data/turning65'


def local_today():
    return datetime.now(ZoneInfo('America/Los_Angeles')).date()


@lru_cache(maxsize=4)
def population(state):
    try:
        data = json.loads((DATA_DIR / f'{state.lower()}_2025.json').read_text())
        if data['state'] != state or data['reference_date'] != '2025-07-01':
            raise ValueError('Incorrect population snapshot')
        expected = {c['id'] for c in load_geometry(state)['counties']}
        if set(data['counties']) != expected or len(data['source_sha256']) != 64:
            raise ValueError('Incomplete population snapshot')
        for county in data['counties'].values():
            values = [county[k] for k in ('population', 'age64', 'age65plus')]
            if any(type(v) is not int or v < 0 for v in values) or sum(values[1:]) > values[0]:
                raise ValueError('Invalid population count')
        return data
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(503, 'Population estimates are unavailable. Restore the verified Census snapshot.') from exc


def stars_number(value):
    try:
        rating = float(value)
        return rating if math.isfinite(rating) and 1 <= rating <= 5 else None
    except (TypeError, ValueError):
        return None


def service_area(state, year, carrier='', plan_id='', stars='all'):
    try:
        data = load_catalog(year, state)
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(503, 'The selected plan catalog is unavailable.') from exc
    carriers = sorted({p['carrier'] for p in data['plans'].values()})
    if carrier and carrier not in carriers:
        raise HTTPException(422, 'Choose an insurer listed in this state and plan year.')
    minimum = None if stars == 'all' else float(stars)
    choices = sorted((p for p in data['plans'].values()
                      if (not carrier or p['carrier'] == carrier)
                      and (minimum is None or (stars_number(p['stars']) or 0) >= minimum)),
                     key=lambda p: (p['carrier'], p['plan_name'], p['id']))
    allowed = {p['id'] for p in choices}
    if plan_id and plan_id not in allowed:
        raise HTTPException(422, 'Choose a plan that matches the selected state, year, insurer and star rating.')
    selected = {plan_id} if plan_id else allowed
    active = bool(carrier or plan_id or stars != 'all')
    area = {county for county, plans in data['county_plans'].items()
            if not active or selected.intersection(plans)}
    return {'catalog': data, 'carriers': carriers, 'plans': choices,
            'ids': area, 'filtered': active,
            'selected_plan': data['plans'].get(plan_id)}


def birthday_in_year(dob, year):
    # Feb 28 is the planning convention for Feb 29 birthdays in non-leap years.
    return date(year, dob.month, min(dob.day, monthrange(year, dob.month)[1]))


def current_age(dob, today):
    if not isinstance(dob, date) or dob > today:
        return None
    return today.year - dob.year - (today < birthday_in_year(dob, today.year))


def add_months(day, months):
    year, month = divmod(day.year * 12 + day.month - 1 + months, 12)
    return date(year, month + 1, min(day.day, monthrange(year, month + 1)[1]))


def birthday_window(window, start, end, today):
    if window == 'age64':
        return None, None, 'Currently age 64'
    if window != 'custom':
        return today, add_months(today, int(window)), f'Next {window} months'
    try:
        first = date.fromisoformat(start) if start else today
        last = date.fromisoformat(end) if end else add_months(today, 6)
        if first < today or last < first:
            raise ValueError('Invalid future date range')
        return first, last, f'{first.isoformat()} through {last.isoformat()}'
    except ValueError as exc:
        raise HTTPException(422, 'Choose a birthday date range starting today or later, with the end after the start.') from exc


def contact_targeting(db, state, county_rows, area_ids, window, start, end, today):
    first, last, window_label = birthday_window(window, start, end, today)
    county_by_name = {county_key(c['name']): c['id'] for c in county_rows}
    county_names = {c['id']: c['name'] for c in county_rows}
    # Same Medicare-workspace membership rule used by the current Contacts page.
    golf = select(GolfProfile.id).where(GolfProfile.lead_id == Lead.id).exists()
    leads = [lead for lead in db.scalars(select(Lead).where(~golf)).all()
             if state_code(lead.state) == state]
    connection = db.connection()
    cached = {}
    if inspect(connection).has_table('gis_address_points'):
        cached = {r['lead_id']: r for r in db.execute(text(
            'SELECT lead_id,address_hash,latitude,longitude,result FROM gis_address_points')).mappings()}
    conflicts = set()
    if inspect(connection).has_table('contact_geocoding_jobs'):
        conflicts = set(db.execute(text(
            "SELECT lead_id FROM contact_geocoding_jobs WHERE reason='county_conflict'")).scalars())
    by_county = {c['id']: {'contacts': 0, 'matching': 0, 'missing_dob': 0} for c in county_rows}
    matches, points = [], []
    counts = {'contacts': 0, 'matching': 0, 'missing_dob': 0, 'invalid_dob': 0,
              'unresolved_county': 0, 'unmapped': 0, 'mapped': 0}
    for lead in leads:
        county_id = county_by_name.get(county_key(lead.county))
        point = cached.get(lead.id)
        fingerprint = _fingerprint(lead)
        # A changed address cannot reuse its previous county/coordinates silently.
        if lead.id in conflicts or (point and point['address_hash'] != fingerprint):
            county_id = None
        if county_id is None:
            counts['unresolved_county'] += 1
            continue
        if county_id not in area_ids:
            continue
        stats = by_county[county_id]
        counts['contacts'] += 1
        stats['contacts'] += 1
        age = current_age(lead.date_of_birth, today)
        if age is None:
            key = 'missing_dob' if lead.date_of_birth is None else 'invalid_dob'
            counts[key] += 1
            stats['missing_dob'] += 1
            continue
        try:
            turns65 = birthday_in_year(lead.date_of_birth, lead.date_of_birth.year + 65)
        except ValueError:
            counts['invalid_dob'] += 1
            continue
        qualifies = age == 64 if window == 'age64' else first <= turns65 <= last
        if not qualifies:
            continue
        item = {'id': lead.id, 'name': ' '.join(p for p in (lead.first_name, lead.last_name) if p).strip(),
                'age': age, 'turns65': turns65.isoformat(), 'county_id': county_id,
                'county': county_names[county_id],
                'city': lead.city or '', 'phone': lead.phone or lead.mobile or '',
                'status': lead.status or '', 'url': f'/leads/{lead.id}'}
        matches.append(item)
        counts['matching'] += 1
        stats['matching'] += 1
        valid = False
        if point and point['result'] == 'matched' and point['address_hash'] == fingerprint:
            lat, lon = point['latitude'], point['longitude']
            valid = (type(lat) in (float, int) and type(lon) in (float, int)
                     and math.isfinite(lat) and math.isfinite(lon)
                     and -90 <= lat <= 90 and -180 <= lon <= 180 and (lat != 0 or lon != 0))
            if valid:
                points.append({k: item[k] for k in ('id', 'name', 'turns65', 'county_id', 'url')}
                              | {'lat': lat, 'lon': lon})
        if not valid:
            counts['unmapped'] += 1
    counts['mapped'] = len(points)
    matches.sort(key=lambda c: (c['turns65'], c['name'].casefold(), c['id']))
    return {'counts': counts, 'counties': by_county, 'matches': matches, 'points': points,
            'start': first, 'end': last, 'window_label': window_label, 'today': today}
