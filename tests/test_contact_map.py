"""Single-contact map destinations use isolated synthetic records, never a geocoder."""
from html import unescape
import re
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.gis_map import _cache, _fingerprint
from app.models import CallLog, Lead
from app.routers.leads import router


@pytest.fixture
def setup():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: db
        lead = Lead(first_name='Synthetic', last_name='Contact', phone='541-555-0142',
                    address='123 Example Street', city='Roseburg', state='OR',
                    zip_code='97470', notes='Keep my notes', status='Interested')
        db.add(lead)
        db.commit()
        with TestClient(app) as client:
            yield client, db, lead
    engine.dispose()


def map_link(page):
    match = re.search(r'<a class="contact-map-button" href="([^"]+)"([^>]+)>', page)
    assert match, 'Expected enabled Map It link'
    url = urlparse(unescape(match[1]))
    assert (url.scheme, url.netloc, url.path) == ('https', 'www.google.com', '/maps/search/')
    assert 'target="_blank"' in match[2] and 'rel="noopener noreferrer"' in match[2]
    return parse_qs(url.query)


def point(db, lead, lat=43.2, lon=-123.3, result='matched', address_hash=None):
    _cache(db)
    db.execute(text('INSERT INTO gis_address_points '
                    '(lead_id,address_hash,latitude,longitude,result) VALUES (:id,:hash,:lat,:lon,:result)'),
               {'id': lead.id, 'hash': address_hash or _fingerprint(lead),
                'lat': lat, 'lon': lon, 'result': result})
    db.commit()


def test_address_fallback_is_read_only_without_creating_cache(setup):
    client, db, lead = setup
    page = client.get(f'/leads/{lead.id}')
    assert page.status_code == 200
    assert map_link(page.text) == {'api': ['1'], 'query': ['123 Example Street, Roseburg, OR, 97470']}
    assert not inspect(db.connection()).has_table('gis_address_points')
    assert lead.notes == 'Keep my notes' and lead.status == 'Interested' and lead.call_attempts == 0
    assert db.scalar(select(CallLog.id)) is None
    assert 'id="manual-call-form"' in page.text


def test_matched_current_coordinates_are_preferred_without_contact_identity(setup):
    client, db, lead = setup
    point(db, lead)
    query = map_link(client.get(f'/leads/{lead.id}').text)
    assert query == {'api': ['1'], 'query': ['43.2,-123.3']}


@pytest.mark.parametrize('change', [
    {'address_hash': 'outdated-address'}, {'result': 'review'},
    {'lat': None}, {'lat': float('inf')}, {'lon': -181}, {'lat': 91}, {'lat': 0, 'lon': 0},
])
def test_stale_unmatched_and_invalid_points_fall_back_to_current_address(setup, change):
    client, db, lead = setup
    point(db, lead, **change)
    assert map_link(client.get(f'/leads/{lead.id}').text)['query'] == ['123 Example Street, Roseburg, OR, 97470']


def test_address_change_cannot_reuse_old_pin(setup):
    client, db, lead = setup
    point(db, lead)
    lead.address = '987 Other Street'
    db.commit()
    assert map_link(client.get(f'/leads/{lead.id}').text)['query'][0].startswith('987 Other Street,')


@pytest.mark.parametrize('address,city,state,zipcode', [
    ('', 'Roseburg', 'OR', '97470'), ('  ', '', 'OR', ''),
    ('Unknown', 'Roseburg', 'OR', '97470'), ('123 Example Street', '', '', ''),
    ('123 Example Street', '', 'OR', 'bad-zip'),
])
def test_unusable_location_disables_button_with_guidance(setup, address, city, state, zipcode):
    client, db, lead = setup
    lead.address, lead.city, lead.state, lead.zip_code = address, city, state, zipcode
    db.commit()
    page = client.get(f'/leads/{lead.id}').text
    assert '<a class="contact-map-button"' not in page
    assert 'type="button" disabled aria-describedby="contact-map-help"' in page
    assert 'Add an address to map this contact.' in page


def test_special_characters_and_street_plus_zip_are_encoded_as_one_query(setup):
    client, db, lead = setup
    lead.address = '123 A&B Street #4?query=elsewhere'
    lead.city = lead.state = ''
    lead.zip_code = '97470-1234'
    db.commit()
    assert map_link(client.get(f'/leads/{lead.id}').text) == {
        'api': ['1'], 'query': ['123 A&B Street #4?query=elsewhere, 97470-1234']}


def test_invalid_manual_call_preserves_notes_and_map_link(setup):
    client, db, lead = setup
    page = client.post(f'/leads/{lead.id}/manual-call', data={
        'outcome': 'Invalid', 'submission_token': 'invalid', 'notes': 'Unsaved draft'})
    assert page.status_code == 400 and 'Unsaved draft' in page.text
    assert map_link(page.text)['query'][0].startswith('123 Example Street,')
