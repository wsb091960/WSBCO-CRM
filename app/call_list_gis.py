"""Geographic filtering and ZIP-level mapping; no street addresses leave the CRM."""
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import json
import math
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request as URLRequest, urlopen

from fastapi import HTTPException
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

STATE_NAMES = dict(pair.split(':') for pair in (
    'AL:Alabama|AK:Alaska|AZ:Arizona|AR:Arkansas|CA:California|CO:Colorado|'
    'CT:Connecticut|DE:Delaware|DC:District of Columbia|FL:Florida|GA:Georgia|'
    'HI:Hawaii|ID:Idaho|IL:Illinois|IN:Indiana|IA:Iowa|KS:Kansas|KY:Kentucky|'
    'LA:Louisiana|ME:Maine|MD:Maryland|MA:Massachusetts|MI:Michigan|MN:Minnesota|'
    'MS:Mississippi|MO:Missouri|MT:Montana|NE:Nebraska|NV:Nevada|NH:New Hampshire|'
    'NJ:New Jersey|NM:New Mexico|NY:New York|NC:North Carolina|ND:North Dakota|'
    'OH:Ohio|OK:Oklahoma|OR:Oregon|PA:Pennsylvania|RI:Rhode Island|SC:South Carolina|'
    'SD:South Dakota|TN:Tennessee|TX:Texas|UT:Utah|VT:Vermont|VA:Virginia|'
    'WA:Washington|WV:West Virginia|WI:Wisconsin|WY:Wyoming|PR:Puerto Rico|'
    'VI:Virgin Islands|GU:Guam|AS:American Samoa|MP:Northern Mariana Islands'
).split('|'))
STATE_CODES = {v.casefold(): k for k, v in STATE_NAMES.items()}

def state_code(value):
    value = str(value or '').strip()
    return STATE_CODES.get(value.casefold(), value.upper())

def county_key(value):
    value = ' '.join(str(value or '').casefold().split())
    return re.sub(r'\s+(county|parish|borough)$', '', value)

def city_key(value):
    return ' '.join(str(value or '').casefold().split())

def zip5(value):
    value = str(value or '').strip()
    return value[:5] if re.fullmatch(r'[0-9]{5}(?:-[0-9]{4})?', value) else ''

def tokens(value):
    values = list(dict.fromkeys(v.strip() for v in str(value or '').split(',') if v.strip()))
    if len(values) > 20 or any(len(v) > 80 for v in values):
        raise HTTPException(400, 'Use at most 20 entries per field, with at most 80 characters each.')
    return values

@dataclass(frozen=True)
class GeoFilter:
    states: tuple = ()
    counties: tuple = ()
    zips: tuple = ()
    mode: str = 'and'
    cities: tuple = ()

    @classmethod
    def parse(cls, data):
        mode = str(data.get('geo_mode', 'and')).lower()
        if mode not in {'and', 'or'}:
            raise HTTPException(400, 'Choose AND or OR matching.')
        states = tuple(dict.fromkeys(state_code(v) for v in tokens(data.get('state', data.get('states', '')))))
        if any(v not in STATE_NAMES for v in states):
            raise HTTPException(400, 'Use valid state names or two-letter state abbreviations.')
        raw_zips = tokens(data.get('zip_code', data.get('zips', '')))
        if any(not zip5(v) for v in raw_zips):
            raise HTTPException(400, 'ZIP entries must have five digits or ZIP+4 format. Keep leading zeros.')
        counties = tuple(dict.fromkeys(county_key(v) for v in tokens(data.get('county', data.get('counties', '')))))
        cities = tuple(dict.fromkeys(city_key(v) for v in tokens(data.get('city', data.get('cities', '')))))
        return cls(states, counties, tuple(dict.fromkeys(zip5(v) for v in raw_zips)), mode, cities)

    @classmethod
    def search(cls, data):
        """New searches always narrow results; OR is retained only for old snapshots."""
        return cls.parse({**dict(data), 'geo_mode': 'and'})

    def matches(self, lead):
        checks = []
        if self.states:
            checks.append(state_code(lead.state) in self.states)
        if self.counties:
            checks.append(county_key(lead.county) in self.counties)
        if self.cities:
            checks.append(city_key(lead.city) in self.cities)
        if self.zips:
            checks.append(zip5(lead.zip_code) in self.zips)
        return not checks or (all(checks) if self.mode == 'and' else any(checks))

    def fields(self):
        return {'states': ', '.join(self.states), 'counties': ', '.join(self.counties),
                'cities': ', '.join(self.cities), 'zips': ', '.join(self.zips), 'geo_mode': self.mode}

    def map_fields(self):
        fields = self.fields()
        return {'state': fields['states'], 'county': fields['counties'],
                'city': fields['cities'], 'zip_code': fields['zips']}

    def label(self):
        parts = []
        for title, values in [('State', self.states), ('County', self.counties), ('City', self.cities), ('ZIP', self.zips)]:
            if values:
                parts.append(title + ': ' + ', '.join(values))
        return (' ' + self.mode.upper() + ' ').join(parts) or 'All locations'

class ManualCallGeography(Base):
    __tablename__ = 'manual_call_geography'
    batch_id: Mapped[int] = mapped_column(Integer, ForeignKey('manual_call_batches.id'), primary_key=True)
    filters_json: Mapped[str] = mapped_column(Text)

class CallListZipLocation(Base):
    __tablename__ = 'call_list_zip_locations'
    zip_code: Mapped[str] = mapped_column(String(5), primary_key=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    state: Mapped[str] = mapped_column(String(2))
    place: Mapped[str] = mapped_column(String(120), default='')
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

def saved_filter(db, batch):
    saved = db.get(ManualCallGeography, batch.id) if batch else None
    return GeoFilter.parse(json.loads(saved.filters_json)) if saved else GeoFilter()

def spatial_summary(leads, rows):
    groups = {}
    def group(lead):
        z = zip5(lead.zip_code)
        if not z:
            return None
        s = state_code(lead.state)
        return groups.setdefault((s, z), {'state': s, 'zip': z, 'eligible': 0, 'selected': 0, 'pending': 0})
    missing = 0
    for lead in leads:
        g = group(lead)
        if g is None:
            missing += 1
        else:
            g['eligible'] += 1
    selected_missing = 0
    for row in rows:
        lead = row['lead']
        g = group(lead) if lead else None
        if g is None:
            selected_missing += 1
        else:
            g['selected'] += 1
            g['pending'] += int(row['item'].completed_at is None)
    counties = Counter((state_code(l.state) or 'Unknown', county_key(l.county).title() or 'Unknown') for l in leads)
    ordered = sorted(groups.values(), key=lambda g: (-g['selected'], -g['eligible'], g['state'], g['zip']))
    return {'groups': ordered[:200], 'total_groups': len(ordered), 'missing_zip': missing,
            'selected_missing_zip': selected_missing, 'match_count': len(leads),
            'counties': [{'state': s, 'county': c, 'count': n} for (s, c), n in counties.most_common()]}

def fetch_zip_location(zip_code):
    """Only the five-digit ZIP is sent to the public postal lookup service."""
    try:
        request = URLRequest('https://api.zippopotam.us/us/' + zip_code,
                             headers={'User-Agent': 'WSBCO-CRM-GIS/1.0', 'Accept': 'application/json'})
        with urlopen(request, timeout=4) as response:
            data = json.loads(response.read(65536))
        place = data['places'][0]
        lat, lon = float(place['latitude']), float(place['longitude'])
        state = place['state abbreviation'].upper()
        if (data.get('country abbreviation') != 'US' or data.get('post code') != zip_code
                or not math.isfinite(lat) or not math.isfinite(lon)
                or not -90 <= lat <= 90 or not -180 <= lon <= 180 or state not in STATE_NAMES):
            raise ValueError('Invalid coordinates')
        return {'zip_code': zip_code, 'latitude': lat, 'longitude': lon,
                'state': state, 'place': str(place.get('place name', ''))[:120]}
    except HTTPError as error:
        raise HTTPException(404 if error.code == 404 else 503, 'ZIP location unavailable.') from error
    except (URLError, OSError, ValueError, KeyError, IndexError, TypeError) as error:
        raise HTTPException(503, 'ZIP lookup unavailable. Your contacts and call list are still usable.') from error
