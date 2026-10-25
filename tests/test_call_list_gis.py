"""Functional GIS regression tests. Uses a fresh in-memory DB; never live contacts."""
from datetime import datetime, date, timedelta
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import Lead, CallLog
from app import call_list_v1 as calls
from app.call_list_gis import GeoFilter, ManualCallGeography, CallListZipLocation, fetch_zip_location, zip5

@pytest.fixture
def setup():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        app = FastAPI()
        app.include_router(calls.router)
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as client:
            yield client, db
    engine.dispose()

def lead(db, **kwargs):
    fields = dict(first_name='Test', last_name='Contact', phone='555-0100', state='OR', county='Douglas', zip_code='97467')
    fields.update(kwargs)
    item = Lead(**fields)
    db.add(item); db.commit()
    return item

def items(db):
    return db.scalars(select(calls.ManualCallItem).order_by(calls.ManualCallItem.id)).all()

def test_and_or_and_exact_normalization():
    contact = SimpleNamespace(state=' Oregon ', county='DOUGLAS County', zip_code='97467-1234')
    assert GeoFilter.parse({'states': 'Oregon, WA', 'counties': 'Douglas', 'zips': '97467'}).matches(contact)
    assert not GeoFilter.parse({'states': 'WA', 'counties': 'Douglas'}).matches(contact)
    assert GeoFilter.parse({'states': 'WA', 'counties': 'Douglas', 'geo_mode': 'or'}).matches(contact)
    assert not GeoFilter.parse({'counties': 'Doug'}).matches(contact)
    assert GeoFilter.parse({}).matches(contact)
    assert zip5('02108-1234') == '02108'
    assert zip5('2108') == ''

@pytest.mark.parametrize('fields', [{'states': 'XX'}, {'zips': '9746'}, {'geo_mode': 'xor'}, {'zips': '<script>'}, {'counties': ','.join(str(i) for i in range(21))}])
def test_invalid_filter_rejected(fields):
    with pytest.raises(HTTPException): GeoFilter.parse(fields)

def test_filter_priority_limit_and_saved_snapshot(setup):
    client, db = setup
    for i in range(12): lead(db, first_name=f'Test{i}')
    urgent = lead(db, priority='High', next_follow_up=date.today() - timedelta(days=1))
    lead(db, state='WA', county='Douglas')
    assert client.get('/call-list?states=OR&counties=Douglas').status_code == 200
    response = client.post('/call-list/generate', data={'states': 'Oregon', 'counties': 'Douglas', 'geo_mode': 'and'})
    assert response.status_code == 200
    saved = items(db)
    assert len(saved) == 10 and saved[0].lead_id == urgent.id
    assert all(db.get(Lead, i.lead_id).state == 'OR' for i in saved)
    snapshot = db.get(ManualCallGeography, saved[0].batch_id)
    assert json.loads(snapshot.filters_json)['states'] == 'OR'
    assert 'Saved selection: State: OR AND County: douglas' in response.text
    # A new search or generate click cannot replace the saved list.
    before = [i.lead_id for i in saved]
    assert client.get('/call-list?states=WA').status_code == 200
    client.post('/call-list/generate', data={'states': 'WA'})
    assert [i.lead_id for i in items(db)] == before
    # Returning without query params restores the saved search.
    assert 'value="OR"' in client.get('/call-list').text

def test_new_search_always_narrows_even_with_old_or_parameter(setup):
    client, db = setup
    a = lead(db)
    b = lead(db, state='WA', county='King', zip_code='98101')
    c = lead(db, state='CA', county='Douglas', zip_code='90210')
    lead(db, state='CA', county='Los Angeles', zip_code='90001')
    client.post('/call-list/generate', data={'states': 'WA', 'counties': 'Douglas', 'geo_mode': 'or'})
    assert not items(db)  # WA plus Douglas matches none; legacy OR must not broaden new lists.

def test_dnc_other_exclusions_and_contacted_today(setup):
    client, db = setup
    eligible = lead(db, zip_code='02108-1234', state='MA')
    for status in [' Do Not Call ', 'Sold', 'Wrong Number', 'Not Interested']:
        lead(db, status=status)
    lead(db, phone='', mobile='')
    lead(db, phone=' ', mobile=' ')
    lead(db, last_contact=datetime.utcnow())
    logged = lead(db)
    db.add(CallLog(lead_id=logged.id, started_at=datetime.utcnow())); db.commit()
    client.post('/call-list/generate', data={'zips': '02108'})
    assert [i.lead_id for i in items(db)] == [eligible.id]

def test_invalid_or_empty_search_never_broadens_generation(setup):
    client, db = setup
    lead(db)
    assert client.post('/call-list/generate', data={'states': 'invalid'}).status_code == 400
    assert not items(db)
    assert client.get('/call-list?zips=abc').status_code == 400
    assert client.post('/call-list/generate', data={'states': 'WA'}).status_code == 200
    assert not items(db)

def test_outcomes_complete_saved_list_without_geography_loss(setup):
    client, db = setup
    first, second = lead(db), lead(db)
    client.post('/call-list/generate', data={'states': 'OR'})
    batch_id = items(db)[0].batch_id
    response = client.post(f'/call-list/{first.id}/outcome', data={'outcome': 'Callback', 'notes': 'Tomorrow', 'next_follow_up': str(date.today()+timedelta(days=1))})
    assert response.status_code == 200 and '1 of 2 completed' in response.text
    assert 'Saved selection: State: OR' in response.text
    assert db.get(Lead, first.id).call_attempts == 1
    assert client.post(f'/call-list/{first.id}/outcome', data={'outcome': 'Callback'}).status_code == 409
    client.post(f'/call-list/{second.id}/outcome', data={'outcome': 'No Answer'})
    assert db.get(calls.ManualCallBatch, batch_id).completed_at is not None
    assert db.scalar(select(func.count()).select_from(CallLog)) == 2

def test_legacy_active_batch_and_state_zip_summary(setup):
    client, db = setup
    a = lead(db, zip_code='')
    b = lead(db)
    batch = calls.ManualCallBatch(); db.add(batch); db.flush()
    db.add(calls.ManualCallItem(batch_id=batch.id, lead_id=b.id)); db.commit()
    response = client.get('/call-list')
    assert response.status_code == 200 and 'Saved selection: All locations' in response.text
    summary = calls.spatial_summary(calls.candidates(db), [{'lead': b, 'item': items(db)[0]}])
    assert summary['missing_zip'] == 1 and summary['groups'][0]['selected'] == 1
    assert summary['counties'][0]['count'] == 2

def test_zip_cache_lookup_failures_and_input_validation(setup, monkeypatch):
    client, db = setup
    payload = dict(zip_code='97467', latitude=43.7, longitude=-124.1, state='OR', place='Reedsport')
    with patch.object(calls, 'fetch_zip_location', return_value=payload) as lookup:
        for _ in range(2):
            response = client.get('/call-list/gis/zip/97467')
            assert response.status_code == 200 and response.json()['lat'] == 43.7
        assert lookup.call_count == 1
    assert db.get(CallListZipLocation, '97467')
    assert client.get('/call-list/gis/zip/123').status_code == 400
    with patch.object(calls, 'fetch_zip_location', side_effect=HTTPException(503, 'Unavailable')):
        assert client.get('/call-list/gis/zip/90210').status_code == 503
        assert client.get('/call-list').status_code == 200

def test_map_data_escapes_untrusted_text(setup):
    client, db = setup
    lead(db, state='</script><script>alert(1)</script>')
    response = client.get('/call-list')
    assert '<script>alert(1)</script>' not in response.text
    assert r'\u003c/SCRIPT\u003e' in response.text

def test_zip_response_rejects_invalid_provider_coordinates():
    from app import call_list_gis as gis
    with patch.object(gis, 'urlopen') as request:
        request.return_value.__enter__.return_value.read.return_value = json.dumps({'country abbreviation': 'US', 'post code': '97467', 'places': [{'latitude': 'NaN', 'longitude': '-124', 'state abbreviation': 'OR'}]}).encode()
        with pytest.raises(HTTPException) as exc: fetch_zip_location('97467')
        assert exc.value.status_code == 503

@pytest.mark.parametrize('disposition,status', list(calls.OUTCOMES.items()))
def test_manual_disposition_logs_and_updates_contact(setup, disposition, status):
    client, db = setup
    contact = lead(db)
    lead(db)  # Keep another call pending so saved details remain visible.
    client.post('/call-list/generate', data={'states': 'OR'})
    followup = date.today() + timedelta(days=2)
    response = client.post(f'/call-list/{contact.id}/disposition', data={
        'outcome': disposition, 'notes': 'Manually dialed; requested information.',
        'next_follow_up': followup.isoformat()})
    assert response.status_code == 200
    log = db.scalar(select(CallLog).where(CallLog.lead_id == contact.id))
    assert log.direction == 'manual' and log.disposition == disposition
    assert log.notes == 'Manually dialed; requested information.'
    assert contact.status == status and contact.call_attempts == 1
    assert contact.next_follow_up == followup
    assert items(db)[0].outcome == disposition and items(db)[0].completed_at
    assert 'Manually dialed; requested information.' in response.text
    assert 'Call disposition' in response.text and 'Save Disposition' in response.text
    if status in {'Do Not Call', 'Wrong Number', 'Not Interested', 'Sold'}:
        assert contact.id not in {l.id for l in calls.candidates(db)}

@pytest.mark.parametrize('form', [{'outcome': ''}, {'outcome': 'Invalid'}, {'outcome': 'Callback', 'next_follow_up': 'not-a-date'}])
def test_invalid_disposition_does_not_complete_call(setup, form):
    client, db = setup
    contact = lead(db)
    client.post('/call-list/generate', data={})
    assert client.post(f'/call-list/{contact.id}/disposition', data=form).status_code == 400
    assert db.scalar(select(func.count()).select_from(CallLog)) == 0
    assert items(db)[0].completed_at is None
    assert contact.call_attempts == 0
