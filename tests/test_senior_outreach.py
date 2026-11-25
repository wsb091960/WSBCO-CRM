"""Shared center outreach never bypasses owner auth outside its token-scoped API."""
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth, call_list_v1
from app.database import Base, get_db
from app.senior_outreach import GIS_URL, router

ORIGIN = 'https://wsbco-crm.onrender.com'
TOKEN = 'test-only-outreach-token-' + 'x' * 32
SERVICE = '/api/senior-outreach/service/records'
LOCAL = '/api/senior-outreach/records'


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv('CRM_PUBLIC_URL', ORIGIN)
    monkeypatch.setenv('SENIOR_OUTREACH_SERVICE_TOKEN', TOKEN)
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(auth, 'SessionLocal', factory)
    app = FastAPI(); app.include_router(router); app.add_middleware(auth.OwnerAuthMiddleware)
    def override_db():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = override_db
    with TestClient(app, base_url=ORIGIN, follow_redirects=False) as client:
        yield client, factory
    engine.dispose()


def payload(**changes):
    return dict(center_name='Bob Ross Senior Center', address='2219 Babcock Road, San Antonio, TX', type='comprehensive', status='contacted', contact_name='Center coordinator', last_contact_date='2026-11-25', next_follow_up='2026-11-27', notes='Arrange an introductory call.', version=0, **changes)


def service(client, method, path='', data=None, token=TOKEN):
    return client.request(method, SERVICE + path, headers={'Authorization': 'Bearer ' + token}, json=data)


def sign_in(client, factory):
    raw = 'a' * 64
    with factory.begin() as db:
        db.add(auth.CrmSession(token_hash=auth.digest(raw), owner_email=auth.owner_email(), expires_at=auth.now_utc()+timedelta(hours=1)))
    client.cookies.set(auth.SESSION_COOKIE, raw)


def test_token_endpoint_is_fail_closed_and_cannot_bypass_other_routes(setup, monkeypatch):
    client, _ = setup
    assert client.get(SERVICE).status_code == 401
    assert service(client, 'GET', token='wrong').status_code == 401
    monkeypatch.delenv('SENIOR_OUTREACH_SERVICE_TOKEN')
    assert service(client, 'GET').status_code == 503
    monkeypatch.setenv('SENIOR_OUTREACH_SERVICE_TOKEN', TOKEN)
    assert service(client, 'GET').json() == {'records': []}
    assert client.get(LOCAL, headers={'Authorization':'Bearer '+TOKEN}).status_code == 401
    assert client.get('/senior-outreach').status_code == 401
    assert client.post(SERVICE, headers={'Authorization':'Bearer '+TOKEN}, json=payload()).status_code == 401
    assert client.delete(SERVICE+'/bob-ross', headers={'Authorization':'Bearer '+TOKEN}).status_code == 401
    assert client.get(SERVICE+'/bad!').status_code == 401


def test_records_persist_and_stale_writes_do_not_overwrite(setup):
    client, _ = setup
    first = service(client, 'PUT', '/bob-ross', payload())
    assert first.status_code == 200
    record = first.json(); assert record['center_id'] == 'bob-ross' and record['version'] == 1
    assert record['updated_at'].endswith('+00:00')
    assert service(client, 'GET', '/bob-ross').json() == record
    assert service(client, 'GET').json()['records'] == [record]
    assert service(client, 'PUT', '/bob-ross', payload()).status_code == 409
    data = payload(); data.update(version=1, notes='Latest call saved.')
    second = service(client, 'PUT', '/bob-ross', data)
    assert second.status_code == 200 and second.json()['version'] == 2
    data['notes'] = 'Stale overwriting call'
    assert service(client, 'PUT', '/bob-ross', data).status_code == 409
    assert service(client, 'GET', '/bob-ross').json()['notes'] == 'Latest call saved.'
    assert service(client, 'GET', '/missing').status_code == 404


@pytest.mark.parametrize('field,value', [
    ('status','sold'),('last_contact_date','2026-02-30'),('next_follow_up','2026-11-2'),
    ('notes','x'*6001),('center_name',' '),('version',True),('version',-1),
    ('version','1'),('contact_phone','a'*81),('unexpected','value'),('type','beneficiary'),
])
def test_invalid_fields_are_rejected(setup, field, value):
    client, _ = setup
    data = payload(); data[field] = value
    assert service(client, 'PUT', '/bob-ross', data).status_code == 422
    assert service(client, 'GET').json()['records'] == []


def test_empty_dates_allowed_body_limit_and_content_type(setup):
    client, _ = setup
    data = payload(); data.update(last_contact_date='', next_follow_up='')
    assert service(client, 'PUT', '/bob-ross', data).status_code == 200
    headers={'Authorization':'Bearer '+TOKEN, 'Content-Type':'application/json'}
    assert client.put(SERVICE+'/another', headers=headers, content=' '*24001).status_code == 413
    headers['Content-Type']='text/plain'
    assert client.put(SERVICE+'/another', headers=headers, content='{}').status_code == 415


def test_owner_local_api_has_csrf_and_native_dashboard(setup):
    client, factory = setup
    sign_in(client, factory)
    assert client.get('/senior-outreach').status_code == 200
    assert client.put(LOCAL+'/bob-ross', json=payload()).status_code == 403
    saved = client.put(LOCAL+'/bob-ross', headers={'Origin':ORIGIN}, json=payload())
    assert saved.status_code == 200
    response = client.get('/senior-outreach')
    assert response.status_code == 200 and 'Bob Ross Senior Center' in response.text
    assert GIS_URL in response.text and 'Edit' in response.text
    assert response.headers['cache-control'] == 'no-store'
    assert service(client,'GET').json()['records'][0]['center_id'] == 'bob-ross'
    assert client.put(LOCAL+'/bob-ross', headers={'Origin':'https://attacker.example'}, json=payload()).status_code == 403
    for template in ['app/templates/layouts/sidebar.html','app/templates/base_v2.html']:
        assert '/senior-outreach' in Path(template).read_text()


def test_csv_export_requires_owner_and_neutralizes_formulas(setup):
    client, factory = setup
    data = payload(); data['notes'] = '=HYPERLINK("https://bad.example")'
    assert service(client,'PUT','/bob-ross',data).status_code == 200
    assert client.get('/senior-outreach/export.csv').status_code == 401
    sign_in(client,factory)
    response = client.get('/senior-outreach/export.csv')
    assert response.status_code == 200 and "'=HYPERLINK" in response.text
    assert response.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('center_type', ['senior_center', 'nutrition_site', 'county_provider'])
def test_wv_center_types_can_be_saved_without_changing_service_contract(setup, center_type):
    client, _ = setup
    data = payload(); data.update(center_name='WV County Senior Services', type=center_type)
    response = service(client, 'PUT', '/wv-example-center', data)
    assert response.status_code == 200 and response.json()['type'] == center_type
    assert service(client, 'GET').json()['records'][0]['center_id'] == 'wv-example-center'


def test_territory_dashboard_counts_rows_links_and_export_are_scoped(setup):
    client, factory = setup
    sa = payload(); sa.update(center_name='San Antonio test center', status='completed', notes='SA_ONLY_NOTE')
    wv = payload(); wv.update(center_name='West Virginia test center', status='follow_up', next_follow_up='2020-01-01', type='senior_center', notes='WV_ONLY_NOTE')
    assert service(client, 'PUT', '/sa-example', sa).status_code == 200
    assert service(client, 'PUT', '/wv-example', wv).status_code == 200
    sign_in(client, factory)
    sa_view = client.get('/senior-outreach')
    assert sa_view.status_code == 200
    assert sa_view.context['territory'] == 'sa-clover'
    assert [row['center_id'] for row in sa_view.context['rows']] == ['sa-example']
    assert sa_view.context['counts']['completed'] == 1 and sa_view.context['counts']['follow_up'] == 0
    assert sa_view.context['due'] == 0
    assert 'SA_ONLY_NOTE' in sa_view.text and 'WV_ONLY_NOTE' not in sa_view.text
    assert '?territory=sa-clover&amp;center=sa-example' in sa_view.text
    wv_view = client.get('/senior-outreach?territory=wv-peak')
    assert wv_view.status_code == 200
    assert [row['center_id'] for row in wv_view.context['rows']] == ['wv-example']
    assert wv_view.context['counts']['follow_up'] == 1 and wv_view.context['counts']['completed'] == 0
    assert wv_view.context['due'] == 1
    assert 'WV_ONLY_NOTE' in wv_view.text and 'SA_ONLY_NOTE' not in wv_view.text
    assert GIS_URL + '/?territory=wv-peak' in wv_view.text
    assert '?territory=wv-peak&amp;center=wv-example' in wv_view.text
    sa_csv = client.get('/senior-outreach/export.csv').text
    wv_csv = client.get('/senior-outreach/export.csv?territory=wv-peak').text
    assert 'SA_ONLY_NOTE' in sa_csv and 'WV_ONLY_NOTE' not in sa_csv
    assert 'WV_ONLY_NOTE' in wv_csv and 'SA_ONLY_NOTE' not in wv_csv
    assert len(service(client, 'GET').json()['records']) == 2  # Shared API stays unfiltered.
    assert client.get('/senior-outreach?territory=invalid').status_code == 422
    assert client.get('/senior-outreach/export.csv?territory=invalid').status_code == 422
    for template in ['app/templates/layouts/sidebar.html','app/templates/base_v2.html']:
        source = Path(template).read_text()
        assert 'territory=wv-peak' in source and 'Peak Health WV Outreach' in source
        assert 'territory=sa-clover' in source and 'San Antonio Outreach' in source
