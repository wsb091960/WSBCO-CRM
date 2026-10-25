"""Restore previously verified GIS coordinates without changing contact records."""
import csv
import hashlib
import io
import json
import math
import re

from fastapi import HTTPException
from sqlalchemy import select, text

from app.call_list_gis import county_key, state_code, zip5
from app.models import Lead

MAX_BYTES = 3 * 1024 * 1024
REQUIRED = {'First Name','Last Name','Address1','City','State','Zip','GIS Status',
            'Needs Review','GIS State','GIS ZIP','GIS Longitude','GIS Latitude'}


def normalized(value):
    return ' '.join(re.sub(r'[^\w\s]', ' ', str(value or '').casefold()).split())


def key(first, last, address, city, state, zipcode):
    return (normalized(first), normalized(last), normalized(address), normalized(city), state_code(state), zip5(zipcode))


def prepare(content, db, fingerprint):
    if len(content) > MAX_BYTES:
        raise HTTPException(400, 'Coordinate file is too large.')
    try:
        reader = csv.DictReader(io.StringIO(content.decode('utf-8-sig')))
        if not REQUIRED.issubset(reader.fieldnames or []):
            raise ValueError('Missing coordinate result columns')
        rows = list(reader)
    except (UnicodeError, csv.Error, ValueError) as exc:
        raise HTTPException(400, 'Use the GIS results CSV with its verification and coordinate columns.') from exc
    if len(rows) > 10000:
        raise HTTPException(400, 'Use at most 10,000 coordinate rows.')
    accepted, rejected = {}, 0
    for row in rows:
        try:
            lat, lon = float(row['GIS Latitude']), float(row['GIS Longitude'])
            if (row['GIS Status'].strip().casefold() != 'matched'
                    or row['Needs Review'].strip().casefold() not in {'no', 'false', '0', ''}
                    or not math.isfinite(lat) or not math.isfinite(lon)
                    or not -90 <= lat <= 90 or not -180 <= lon <= 180
                    or (lat == 0 and lon == 0)
                    or not zip5(row['Zip']) or zip5(row['Zip']) != zip5(row['GIS ZIP'])
                    or state_code(row['State']) != state_code(row['GIS State'])):
                raise ValueError('Unverified coordinate')
            identity = key(row['First Name'],row['Last Name'],row['Address1'],row['City'],row['State'],row['Zip'])
            if not all(identity):
                raise ValueError('Incomplete identity')
            accepted.setdefault(identity, []).append((lat, lon, row))
        except (ValueError, TypeError, KeyError):
            rejected += 1
    leads = db.scalars(select(Lead).order_by(Lead.id)).all()
    plan = []
    counts = {'source_rows': len(rows), 'source_unverified': rejected,
              'contacts': len(leads), 'matched': 0, 'unmatched': 0, 'ambiguous': 0}
    for lead in leads:
        identity = key(lead.first_name,lead.last_name,lead.address,lead.city,lead.state,lead.zip_code)
        options = accepted.get(identity, [])
        if not options:
            counts['unmatched'] += 1
            continue
        coords = {(round(lat, 6),round(lon, 6)) for lat,lon,row in options}
        counties = {county_key(row.get('GIS County')) for lat,lon,row in options if row.get('GIS County')}
        if len(coords) != 1 or (lead.county and counties and county_key(lead.county) not in counties):
            counts['ambiguous'] += 1
            continue
        lat,lon,row=options[0]
        plan.append({'id':lead.id,'hash':fingerprint(lead),'lat':lat,'lon':lon,
                     'source':row.get('GIS Source','Verified GIS results')[:300],
                     'checked':row.get('GIS Checked At','')[:80],
                     'precision':row.get('Coordinate Precision','')[:120]})
        counts['matched'] += 1
    signature = hashlib.sha256(content + json.dumps(plan,sort_keys=True).encode()).hexdigest()
    return plan, counts, signature


def restore(plan, db):
    db.execute(text('''CREATE TABLE IF NOT EXISTS gis_coordinate_sources (
        lead_id INTEGER PRIMARY KEY, address_hash TEXT NOT NULL,
        source TEXT NOT NULL, checked_at TEXT, precision TEXT
    )'''))
    existing = {row[0]:row for row in db.execute(text(
        'SELECT lead_id,address_hash,result FROM gis_address_points')).all()}
    restored = preserved = 0
    for item in plan:
        old=existing.get(item['id'])
        if old and old[1] == item['hash'] and old[2] == 'matched':
            preserved += 1
            continue
        db.execute(text('''INSERT INTO gis_address_points
            (lead_id,address_hash,latitude,longitude,score,match_type,result)
            VALUES (:id,:hash,:lat,:lon,NULL,'Verified GIS import','matched')
            ON CONFLICT(lead_id) DO UPDATE SET address_hash=excluded.address_hash,
            latitude=excluded.latitude,longitude=excluded.longitude,score=NULL,
            match_type=excluded.match_type,result=excluded.result'''), item)
        db.execute(text('''INSERT INTO gis_coordinate_sources
            (lead_id,address_hash,source,checked_at,precision)
            VALUES (:id,:hash,:source,:checked,:precision)
            ON CONFLICT(lead_id) DO UPDATE SET address_hash=excluded.address_hash,
            source=excluded.source,checked_at=excluded.checked_at,precision=excluded.precision'''),item)
        restored += 1
    db.commit()
    return {'restored':restored,'preserved':preserved}
