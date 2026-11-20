"""Territory indices use recorded evidence and expose incomplete coverage."""
import csv
from datetime import datetime, timedelta, timezone
import io
import json
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth, call_list_v1
from app.database import Base, get_db
from app.gis_map import _cache, _fingerprint
from app.golf_integration import GolfProfile
from app.models import Lead, CallLog
from app.services import territories as service
from app.territories import router

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)  # 4 AM Pacific


@pytest.fixture
def setup(monkeypatch, tmp_path):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    app = FastAPI()
    app.include_router(router)
    def db():
        with sessions() as session:
            yield session
    app.dependency_overrides[get_db] = db
    monkeypatch.setattr(service, 'utc_now', lambda: NOW)
    activity = tmp_path / 'activity.db'
    with sqlite3.connect(activity) as con:
        con.execute('CREATE TABLE activities(lead_id INTEGER,activity_type TEXT,created_at TEXT)')
    monkeypatch.setattr(service, 'ACTIVITY_DB', activity)
    with TestClient(app) as client:
        yield client, sessions, activity
    engine.dispose()


def add(db, name, county='Bexar', state='TX', **changes):
    lead = Lead(first_name=name, county=county, state=state, address='123 Example Street',
                city='San Antonio', zip_code='78201', **changes)
    db.add(lead)
    db.flush()
    return lead


def event(path, lead_id, kind, at):
    with sqlite3.connect(path) as con:
        con.execute('INSERT INTO activities VALUES (?,?,?)', (lead_id, kind, at))


@pytest.mark.parametrize('state,count,total', [('OR',36,51489),('CA',58,450325),('WV',55,24012),('TX',254,332178)])
def test_real_county_geometry_and_empty_crm_are_ranked_truthfully(setup, state, count, total):
    client, _, _ = setup
    r = client.get('/territories', params={'state': state})
    assert r.status_code == 200
    c = r.context
    assert len(c['ranked']) == count and c['totals']['age64'] == total
    assert c['totals']['empty'] == count and c['totals']['contacts'] == 0
    assert all(row['value'] == row['age64'] for row in c['ranked'])
    assert c['ranked'][0]['value'] >= c['ranked'][1]['value']
    assert c['map_config']['points'] == []
    assert 'July 1, 2025' in r.text and 'Underworked Territories' in r.text
    assert r.headers['cache-control'] == 'no-store'


def test_distinct_worked_contacts_and_two_lenses_expose_underlying_counts(setup):
    client, sessions, activity = setup
    with sessions.begin() as db:
        first = add(db, 'Called', last_contact=NOW.replace(tzinfo=None) - timedelta(days=1))
        second = add(db, 'Email', status='Do Not Call')
        add(db, 'NoHistory')  # Missing DOB still contributes to CRM coverage.
        for _ in range(2):
            db.add(CallLog(lead_id=first.id, direction='manual', status='completed', started_at=NOW.replace(tzinfo=None)-timedelta(days=2)))
        ids = first.id, second.id
    event(activity, ids[0], 'call', '2026-11-19T10:00:00-08:00')
    event(activity, ids[1], 'email', '2026-11-19T10:00:00-08:00')
    event(activity, ids[1], 'call', '2026-11-19T11:00:00-08:00')
    r = client.get('/territories?state=TX&county=48029')
    s = r.context['selected']
    assert (s['contacts'], s['worked'], s['gap'], s['calls'], s['dnc']) == (3, 2, 1, 2, 1)
    assert s['value'] == 21564 / 4
    recent = client.get('/territories?state=TX&county=48029&lens=outreach').context['selected']
    assert recent['value'] == 21564 / 3
    assert 'county=48029' in s['birthdays_url'] and 'year=2027' in s['plans_url']
    listing = client.get(s['contacts_url'])
    assert listing.context['contact_count'] == 1 and 'NoHistory' in listing.text
    assert 'Called' not in listing.text and 'Email</a>' not in listing.text
    all_rows = client.get(s['contacts_url'] + '&gap=0')
    assert all_rows.context['contact_count'] == 3 and '<strong>Do Not Call</strong>' in all_rows.text
    for c in r.context['map_config']['counties']:
        assert 'name' in c and 'details' in c
    assert 'NoHistory' not in json.dumps(r.context['map_config'])


def test_pacific_window_boundaries_future_dates_and_non_outreach_are_excluded(setup):
    client, sessions, activity = setup
    # Last 30 calendar days includes Oct 22 midnight PDT = 07:00 UTC.
    start = datetime(2026, 10, 22, 7)
    with sessions.begin() as db:
        inside = add(db, 'Boundary', last_contact=start)
        add(db, 'Before', last_contact=start-timedelta(microseconds=1))
        add(db, 'Future', last_contact=NOW.replace(tzinfo=None)+timedelta(seconds=1))
        not_worked = add(db, 'NotesOnly')
        failed = add(db, 'FailedSetup')
        db.add(CallLog(lead_id=failed.id, status='failed', started_at=NOW.replace(tzinfo=None)))
        db.add(CallLog(lead_id=inside.id, status='completed', started_at=start))
        outside_call = add(db, 'FutureCall')
        db.add(CallLog(lead_id=outside_call.id, status='completed', started_at=NOW.replace(tzinfo=None)+timedelta(seconds=1)))
        now_contact = add(db, 'Now')
        ids = not_worked.id, now_contact.id
    for kind in ['note', 'status', 'followup', 'disposition']:
        event(activity, ids[0], kind, NOW.isoformat())
    event(activity, ids[0], 'email', 'bad date')
    event(activity, ids[0], 'call', (NOW+timedelta(seconds=1)).isoformat())
    event(activity, ids[1], 'email', NOW.isoformat())
    s = client.get('/territories?state=TX&county=48029&days=30').context['selected']
    assert (s['contacts'], s['worked'], s['gap'], s['calls']) == (7, 2, 5, 1)
    assert s['last_worked'] == '2026-11-20T04:00:00-08:00'
    old = client.get('/territories?state=TX&county=48029&days=60').context['selected']
    assert old['worked'] == 3


def test_normalization_golf_and_unresolved_counties_do_not_pollute_totals(setup):
    client, sessions, _ = setup
    with sessions() as db:
        _cache(db)
        add(db, 'Resolved', county='  BEXAR County ', state='Texas')
        add(db, 'Unknown', county='')
        stale = add(db, 'ChangedAddress')
        db.execute(text("INSERT INTO gis_address_points(lead_id,address_hash,result) VALUES (:id,'old','matched')"), {'id': stale.id})
        conflict = add(db, 'CountyConflict')
        db.execute(text("UPDATE contact_geocoding_jobs SET reason='county_conflict' WHERE lead_id=:id"), {'id': conflict.id})
        golfer = add(db, 'Golf')
        db.add(GolfProfile(lead_id=golfer.id))
        add(db, 'OtherState', county='Coos', state='OR')
        db.commit()
    c = client.get('/territories?state=TX&county=48029').context
    assert c['selected']['contacts'] == 1
    assert c['coverage']['unresolved'] == 3
    assert {r['name'] for r in c['matches']} == {'Resolved'}


def test_population_and_empty_filters_do_not_silently_broaden_contact_lists(setup):
    client, sessions, _ = setup
    with sessions.begin() as db:
        add(db, 'PRIVATE PERSON', phone='5415550100')
    r = client.get('/territories?state=TX&county=48029&empty=1&minimum=5000&map_view=outline')
    c = r.context
    assert c['selected'] is None and c['notice']
    assert all(row['contacts'] == 0 and row['age64'] >= 5000 for row in c['ranked'])
    assert 't65-esri-map' not in r.text and 'Outside selected territory filters' in r.text
    assert len(c['counties']) == 254
    listing = client.get('/territories/contacts?state=TX&county=48029&empty=1&gap=0')
    assert listing.context['contact_count'] == 0 and 'PRIVATE PERSON' not in listing.text
    empty = client.get('/territories?state=WV&minimum=5000')
    assert empty.context['ranked'] == [] and 'No counties match these filters' in empty.text
    assert all('county=' not in url for url in c['state_links'].values())


@pytest.mark.parametrize('query', ['state=FL','state=TX&county=41019','days=0','days=999','minimum=-1',
    'minimum=123','empty=2','lens=bad','map_view=bad','state=TX&county=4802'])
def test_invalid_filters_rejected_consistently(setup, query):
    client, _, _ = setup
    for path in ['/territories', '/territories/contacts', '/territories/export.csv']:
        assert client.get(path+'?'+query).status_code == 422


def test_missing_activity_history_is_visible_read_only_and_never_invented(setup, tmp_path, monkeypatch):
    client, sessions, _ = setup
    absent = tmp_path / 'absent.db'
    monkeypatch.setattr(service, 'ACTIVITY_DB', absent)
    with sessions.begin() as db:
        add(db, 'LastContact', last_contact=NOW.replace(tzinfo=None))
    r = client.get('/territories?state=TX&county=48029&lens=outreach')
    assert r.context['selected']['worked'] == 1
    assert r.context['coverage']['activity_available'] is False
    assert 'Activity history is unavailable' in r.text
    assert not absent.exists()


def test_csv_has_reproducible_rankings_sources_and_no_contact_identity(setup):
    client, sessions, _ = setup
    with sessions.begin() as db:
        add(db, 'PRIVATE PERSON', phone='5415550100', notes='SECRET NOTE', medicare_mbi='SECRET MBI')
    r = client.get('/territories/export.csv?state=TX&lens=outreach&days=30')
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 254
    b = next(row for row in rows if row['County']=='Bexar')
    assert b['Residents exactly age 64'] == '21564' and b['Targeting index'] == '21564.0'
    assert b['Medicare CRM contacts all ages'] == '1'
    assert b['Formula'] == 'age64 / (recently worked contacts + 1)'
    assert b['Population reference date'] == '2025-07-01' and len(b['Census SHA256']) == 64
    assert b['Window start Pacific'] == '2026-10-22'
    for private in ['PRIVATE PERSON','5415550100','SECRET NOTE','SECRET MBI']:
        assert private not in r.text
    assert r.headers['cache-control'] == 'no-store'


def test_contact_output_escapes_text_and_paginates_without_losing_filters(setup):
    client, sessions, _ = setup
    with sessions.begin() as db:
        for i in range(51):
            add(db, f'<script>{i:02}</script>')
    r = client.get('/territories/contacts?state=TX&county=48029&days=60')
    assert r.context['contact_count'] == 51 and len(r.context['matches']) == 50
    assert '<script>00</script>' not in r.text and '&lt;script&gt;00&lt;/script&gt;' in r.text
    next_page = client.get(r.context['next_url'])
    assert len(next_page.context['matches']) == 1 and next_page.context['f'].days == 60
    assert next_page.context['selected']['id'] == '48029'


def test_all_territory_routes_require_owner_session(setup, monkeypatch):
    _, sessions, _ = setup
    app = FastAPI()
    app.include_router(router)
    monkeypatch.setattr(auth, 'SessionLocal', sessions)
    app.add_middleware(auth.OwnerAuthMiddleware)
    with TestClient(app, base_url='https://wsbco-crm.onrender.com', follow_redirects=False) as client:
        for path in ['/territories','/territories/contacts','/territories/export.csv']:
            assert client.get(path, headers={'Accept':'application/json'}).status_code == 401
        r = client.get('/territories?state=CA', headers={'Accept':'text/html'})
        assert r.status_code == 303 and 'next=' in r.headers['location']
