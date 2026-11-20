"""Synthetic addresses and mocked Esri only; no live contacts or provider calls."""
import io
import json
import threading
import time
from urllib.parse import parse_qs

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, get_db
from app import call_list_v1  # Register the referenced manual-call batch table.
from app.gis_map import _fingerprint, router as gis_router
from app.models import Lead
from app.routers.leads import router as leads_router
from app.imports_v35 import COOKIE, router as imports_router
from app.golf_integration import router as golf_router
from app import website_leads
from app.services import geocoding as geo


@pytest.fixture
def setup(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + str(tmp_path / 'contacts.db'),
                           connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    geo.initialize_cache(engine)
    factory = sessionmaker(engine)
    app = FastAPI()
    for router in (leads_router, imports_router, gis_router, golf_router, website_leads.router):
        app.include_router(router)
    def db():
        with factory() as session:
            yield session
    app.dependency_overrides[get_db] = db
    monkeypatch.setattr(website_leads, 'SessionLocal', factory)
    website_leads.hits.clear()
    monkeypatch.setenv('GOLF_FORM_WEBHOOK_KEY', 'test-form-key')
    with TestClient(app, follow_redirects=False) as client:
        yield client, factory, engine
    engine.dispose()


def contact(**changes):
    return dict(first_name='Synthetic', last_name='Contact', address='123 Example Street',
                city='Roseburg', state='OR', zip_code='97470', **changes)


def match(lead):
    return dict(status='matched', reason='', lat=43.21, lon=-123.35,
                score=99, match_type='StreetAddress', county='Douglas County')


def test_manual_save_returns_before_lookup_then_maps_and_fills_county(setup):
    client, factory, engine = setup
    response = client.post('/leads/new', data=contact(notes='Keep notes', phone='541-555-0100'))
    assert response.status_code == 303
    location = response.headers['location']
    assert 'Locating address' in client.get(location).text
    assert client.get('/gis/points').json()['points'] == []
    assert geo.process_next(engine, lookup=match)
    page = client.get(location)
    assert 'Address located' in page.text and 'Douglas County' in page.text
    points = client.get('/gis/points').json()['points']
    assert len(points) == 1 and points[0]['lat'] == 43.21
    assert points[0]['precision'] == 'Estimated street-range location'
    with factory() as db:
        lead = db.scalar(select(Lead))
        assert lead.notes == 'Keep notes' and lead.phone == '541-555-0100'
        assert db.get(geo.GeocodingJob, lead.id).attempts == 1
    assert not geo.process_next(engine, lookup=lambda _: pytest.fail('Duplicate lookup'))


def test_import_preview_has_no_job_commit_queues_every_new_contact(setup):
    client, factory, engine = setup
    client.get('/imports')
    csrf = client.cookies[COOKIE]
    result = client.post('/imports/source', data={'csrf': csrf, 'source_type': 'file'},
                         files={'file': ('contacts.csv', b'First,Last,Address,City,State,ZIP\nAnn,Example,123 Example St,Roseburg,OR,97470\nBob,Example,456 Example St,Roseburg,OR,97470\n')})
    url = result.headers['location']
    fields = ['first_name', 'last_name', 'address', 'city', 'state', 'zip_code']
    client.post(url + '/preview', data={'csrf': csrf, **{f'column_{i}': f for i, f in enumerate(fields)}})
    with factory() as db:
        assert db.scalars(select(geo.GeocodingJob)).all() == []
    assert client.post(url + '/commit', data={'csrf': csrf, 'confirm': 'yes'}).status_code == 303
    with factory() as db:
        assert [j.status for j in db.scalars(select(geo.GeocodingJob))] == ['pending', 'pending']
    assert geo.process_next(engine, lookup=match) and geo.process_next(engine, lookup=match)


def test_website_and_golf_without_street_wait_for_address(setup):
    client, factory, engine = setup
    response = client.post('/api/website/leads', headers={'Origin': 'https://turning65medicaremadeeasy.com'}, json={
        'first_name': 'Web', 'last_name': 'Example', 'phone': '541-555-0100',
        'email': 'web@example.com', 'zip_code': '97470', 'state': 'OR', 'consent': True})
    assert response.status_code == 201
    response = client.post('/golf/inquiries', headers={'X-Golf-Form-Key': 'test-form-key'}, json={
        'submission_id': 'test-1', 'first_name': 'Golf', 'last_name': 'Example', 'phone': '541-555-0101'})
    assert response.status_code == 201
    with factory() as db:
        assert [j.status for j in db.scalars(select(geo.GeocodingJob))] == ['incomplete', 'incomplete']
        lead_id = db.scalar(select(Lead.id).where(Lead.first_name == 'Web'))
    assert not geo.process_next(engine, lookup=lambda _: pytest.fail('Missing street sent'))
    assert 'Address needed' in client.get(f'/leads/{lead_id}').text
    assert client.post(f'/leads/{lead_id}/edit', data=contact()).status_code == 303
    assert geo.process_next(engine, lookup=match)


def test_transaction_rollback_and_deletion_do_not_leave_jobs(setup):
    _, factory, engine = setup
    with factory() as db:
        lead = Lead(**contact())
        db.add(lead)
        db.flush()
        assert db.get(geo.GeocodingJob, lead.id)
        db.rollback()
    assert not geo.process_next(engine, lookup=lambda _: pytest.fail('Rolled-back contact sent'))
    with factory.begin() as db:
        lead = Lead(**contact())
        db.add(lead)
    with factory.begin() as db:
        db.delete(db.scalar(select(Lead)))
    assert not geo.process_next(engine, lookup=lambda _: pytest.fail('Deleted contact sent'))


def test_transient_failure_retries_after_restart_and_preserves_county(setup):
    _, factory, engine = setup
    with factory.begin() as db:
        db.add(Lead(**contact(county='Coos', notes='Unchanged')))
    assert geo.process_next(engine, lookup=lambda _: {'status': 'retry', 'reason': 'service_error'}, now=100)
    with factory() as db:
        job = db.scalar(select(geo.GeocodingJob))
        assert job.next_attempt == 130 and job.status == 'retry'
    assert not geo.process_next(engine, lookup=match, now=129)
    engine.dispose()  # persisted queue survives a fresh database connection
    assert geo.process_next(engine, lookup=match, now=131)
    with factory() as db:
        lead = db.scalar(select(Lead))
        assert lead.county == 'Coos' and lead.notes == 'Unchanged'
        assert db.get(geo.GeocodingJob, lead.id).reason == 'county_conflict'


def test_address_change_during_lookup_discards_result_and_requeues(setup):
    _, factory, engine = setup
    with factory.begin() as db:
        db.add(Lead(**contact()))
    def changing_address(lead):
        with factory.begin() as db:
            db.get(Lead, lead.id).address = '999 New Street'
        return match(lead)
    assert geo.process_next(engine, lookup=changing_address)
    with factory() as db:
        assert db.execute(text('SELECT * FROM gis_address_points')).all() == []
        assert db.scalar(select(geo.GeocodingJob)).status == 'pending'
    assert geo.process_next(engine, lookup=match)
    with factory.begin() as db:
        lead = db.scalar(select(Lead))
        assert db.execute(text('SELECT address_hash FROM gis_address_points')).scalar() == _fingerprint(lead)
        lead.notes = 'Note-only edit'
    assert not geo.process_next(engine, lookup=lambda _: pytest.fail('Note edit requeued'))


def test_lease_excludes_other_worker_and_recovers_abandoned_job(setup):
    _, factory, engine = setup
    with factory.begin() as db:
        db.add(Lead(**contact()))
    def second_worker(lead):
        assert not geo.process_next(engine, lookup=lambda _: pytest.fail('Duplicate worker'), now=101)
        return match(lead)
    assert geo.process_next(engine, lookup=second_worker, now=100)
    with factory.begin() as db:
        job = db.scalar(select(geo.GeocodingJob))
        job.status, job.lease_until = 'processing', 200
    assert not geo.process_next(engine, lookup=match, now=199)
    assert geo.process_next(engine, lookup=match, now=201)


@pytest.mark.parametrize('address', ['PO Box 123', 'P.O. Box 123', 'Post Office Box 123'])
def test_po_boxes_are_visible_review_cases_without_provider_request(setup, address):
    client, factory, engine = setup
    data = contact()
    data['address'] = address
    response = client.post('/leads/new', data=data)
    assert 'residential street address' in client.get(response.headers['location']).text
    assert not geo.process_next(engine, lookup=lambda _: pytest.fail('PO box sent'))


def candidate(**changes):
    return dict(score=99, location={'x': -123.35, 'y': 43.21}, attributes={
        'Addr_type': 'StreetAddress', 'Region': 'Oregon', 'Postal': '97470', 'Subregion': 'Douglas County'}, **changes)


def provider(monkeypatch, result, sent):
    monkeypatch.setenv('ARCGIS_API_KEY', 'test-only-key')
    def request(req, timeout):
        sent.append(parse_qs(req.data.decode()))
        assert timeout == 12
        return io.StringIO(json.dumps(result))
    monkeypatch.setattr(geo, 'urlopen', request)


def test_provider_sends_address_only_with_storage_and_crs(monkeypatch):
    sent = []
    provider(monkeypatch, {'candidates': [candidate()]}, sent)
    result = geo.lookup_address(Lead(**contact(notes='PRIVATE', medicare_mbi='SECRET')))
    assert result['status'] == 'matched' and result['county'] == 'Douglas County'
    payload = sent[0]
    assert payload['forStorage'] == ['true'] and payload['outSR'] == ['4326']
    assert payload['SingleLine'] == ['123 Example Street, Roseburg, OR, 97470']
    assert 'SECRET' not in str(payload) and 'PRIVATE' not in str(payload) and 'Synthetic' not in str(payload)


@pytest.mark.parametrize('change', ['low_score', 'state', 'zip', 'type', 'nan', 'zero', 'ambiguous'])
def test_unreliable_matches_are_not_promoted(monkeypatch, change):
    c = candidate()
    others = []
    if change == 'low_score': c['score'] = 94
    if change == 'state': c['attributes']['Region'] = 'California'
    if change == 'zip': c['attributes']['Postal'] = '97467'
    if change == 'type': c['attributes']['Addr_type'] = 'Postal'
    if change == 'nan': c['location']['y'] = float('nan')
    if change == 'zero': c['location'] = {'x': 0, 'y': 0}
    if change == 'ambiguous':
        other = candidate()
        other['location']['x'] = -123.9
        others.append(other)
    provider(monkeypatch, {'candidates': [c] + others}, [])
    assert geo.lookup_address(Lead(**contact()))['status'] == 'review'


def test_missing_configuration_and_provider_errors_are_retryable(monkeypatch):
    monkeypatch.delenv('ARCGIS_API_KEY', raising=False)
    assert geo.lookup_address(Lead(**contact())) == {'status': 'retry', 'reason': 'configuration'}
    provider(monkeypatch, {'error': {'code': 498}}, [])
    assert geo.lookup_address(Lead(**contact())) == {'status': 'retry', 'reason': 'configuration'}
    monkeypatch.setattr(geo, 'urlopen', lambda *a, **k: (_ for _ in ()).throw(TimeoutError()))
    assert geo.lookup_address(Lead(**contact())) == {'status': 'retry', 'reason': 'service_error'}


def test_upgrade_does_not_queue_historical_contacts(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'old.db'))
    # Simulate the pre-feature schema and a contact written by that version.
    Lead.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(Lead.__table__.insert().values(**contact()))
    Base.metadata.create_all(engine)
    geo.initialize_cache(engine)
    assert not geo.process_next(engine, lookup=lambda _: pytest.fail('Historical backfill'))
    engine.dispose()


def test_application_lifecycle_processes_jobs_without_request_and_stops(setup, monkeypatch):
    _, factory, engine = setup
    from app import main
    monkeypatch.setattr(main, 'engine', engine)
    called = threading.Event()
    def lookup(lead):
        called.set()
        return match(lead)
    monkeypatch.setattr(geo, 'lookup_address', lookup)
    with factory.begin() as db:
        db.add(Lead(**contact()))
    with TestClient(main.app) as client:
        assert client.get('/health').status_code == 200
        assert called.wait(5)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with factory() as db:
                if db.scalar(select(geo.GeocodingJob.status)) == 'matched':
                    break
            time.sleep(0.01)
        else:
            pytest.fail('Background geocoding did not persist its result')
        worker = main.app.state.geocoding_worker
        assert worker.thread.is_alive()
    assert not worker.thread.is_alive()
