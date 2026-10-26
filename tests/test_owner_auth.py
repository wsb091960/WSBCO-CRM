import base64
from datetime import timedelta
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth
from app import call_list_v1  # Register the existing batch table referenced by geography.
from app.database import Base, get_db
from app.models import Lead
from app.routers import leads
from app.golf_integration import router as golf_router
from app.website_leads import router as website_router

ORIGIN = 'https://wsbco-crm.onrender.com'
TEST_KEY = 'test-only-sign-in-key-' + '0' * 32
SCRIPT_URL = 'https://script.google.com/macros/s/test_deployment/exec'


@pytest.fixture
def setup(monkeypatch):
    auth.login_attempts.clear()
    monkeypatch.setenv('CRM_OWNER_EMAIL', 'williamsburton@gmail.com')
    monkeypatch.setenv('CRM_PUBLIC_URL', ORIGIN)
    monkeypatch.setenv('CRM_GOOGLE_SIGNING_KEY', TEST_KEY)
    monkeypatch.setenv('CRM_GOOGLE_LOGIN_URL', SCRIPT_URL)
    monkeypatch.setenv('GOLF_FORM_WEBHOOK_KEY', 'test-form-key')
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(auth, 'SessionLocal', factory)
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=['https://turning65medicaremadeeasy.com'],
                       allow_methods=['POST'], allow_headers=['Content-Type'])
    app.mount('/static', StaticFiles(directory='app/static'), name='static')
    for router in (leads.router, auth.router, golf_router, website_router):
        app.include_router(router)
    app.add_middleware(auth.OwnerAuthMiddleware)
    def db_override():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = db_override
    @app.get('/health')
    def health():
        return {'status': 'ok'}
    @app.post('/protected-change')
    def change():
        return {'saved': True}
    with factory() as db:
        db.add(Lead(first_name='PRIVATE', last_name='SENTINEL', phone='2025550147'))
        db.commit()
    with TestClient(app, base_url=ORIGIN, follow_redirects=False) as client:
        yield client, factory
    engine.dispose()


def sign(browser_nonce, **changes):
    now = int(time.time())
    payload = dict(iss='wsbco-private-google-login', aud=ORIGIN, email='williamsburton@gmail.com',
                   nonce=browser_nonce, iat=now, exp=now + 120)
    payload.update(changes)
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
    signature = base64.urlsafe_b64encode(hmac.new(TEST_KEY.encode(), encoded.encode(), hashlib.sha256).digest()).decode().rstrip('=')
    return encoded + '.' + signature


def begin(client, path='/leads'):
    result = client.get('/auth/google/start', params={'next': path})
    assert result.status_code == 303
    assert result.headers['location'].startswith(SCRIPT_URL)
    nonce = parse_qs(urlsplit(result.headers['location']).query)['nonce'][0]
    return nonce, result


def login(client, path='/leads'):
    nonce, _ = begin(client, path)
    return client.post('/auth/google/complete', data={'assertion': sign(nonce)})


def test_public_entry_never_queries_or_exposes_contact_data(setup):
    client, _ = setup
    response = client.get('/')
    assert response.status_code == 200
    assert 'Medicare' in response.text and 'Made Easy.' in response.text
    assert 'Continue with Google' in response.text and 'PRIVATE' not in response.text.replace('PRIVATE WORKSPACE', '')
    assert 'scenic_entry.css' in response.text
    assert client.get('/health').status_code == 200
    assert client.get('/static/images/coastal-golf-entry.webp').status_code == 200


@pytest.mark.parametrize('path', ['/leads', '/leads/1', '/gis/points', '/imports', '/call-list', '/calendar', '/docs', '/openapi.json', '/golf/contacts'])
def test_default_deny_guards_direct_pages_and_data_endpoints(setup, path):
    client, _ = setup
    response = client.get(path)
    assert response.status_code == 401
    assert 'SENTINEL' not in response.text
    browser = client.get(path, headers={'Accept': 'text/html'})
    assert browser.status_code == 303 and browser.headers['location'].startswith('/login?')


def test_login_establishes_secure_revocable_session_and_preserves_destination(setup):
    client, factory = setup
    nonce, start = begin(client, '/leads/1')
    cookie = start.headers['set-cookie']
    assert 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=none' in cookie and 'Domain=' not in cookie
    result = client.post('/auth/google/complete', data={'assertion': sign(nonce)})
    assert result.status_code == 303 and result.headers['location'] == '/leads/1'
    session_cookie = next(v for v in result.headers.get_list('set-cookie') if auth.SESSION_COOKIE in v)
    assert 'Secure' in session_cookie and 'HttpOnly' in session_cookie and 'SameSite=lax' in session_cookie
    raw_token = client.cookies.get(auth.SESSION_COOKIE)
    with factory() as db:
        stored = db.scalar(select(auth.CrmSession))
        assert stored.token_hash != raw_token and stored.token_hash == auth.digest(raw_token)
    page = client.get('/leads/1')
    assert page.status_code == 200 and 'SENTINEL' in page.text
    assert page.headers['cache-control'] == 'no-store'
    assert page.headers['x-frame-options'] == 'DENY'
    assert 'Welcome back' in client.get('/').text
    assert client.post('/logout', headers={'Origin': ORIGIN}).status_code == 303
    assert client.get('/leads/1').status_code == 401
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(auth.CrmSession)) == 0


@pytest.mark.parametrize('changes', [
    {'email':'other@example.com'}, {'aud':'https://attacker.example'}, {'iss':'golf-relay'},
    {'nonce':'a'*64}, {'iat':int(time.time())-600,'exp':int(time.time())-500},
    {'exp':int(time.time())+3600}, {'iat':int(time.time())+100},
])
def test_wrong_account_audience_nonce_and_lifetime_are_rejected(setup, changes):
    client, factory = setup
    nonce, _ = begin(client)
    result = client.post('/auth/google/complete', data={'assertion':sign(nonce, **changes)})
    assert result.headers['location'] == '/login?error=expired'
    assert client.get('/leads').status_code == 401
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(auth.CrmSession)) == 0


def test_tampering_missing_cookie_and_replay_fail_closed(setup):
    client, factory = setup
    nonce, _ = begin(client)
    assertion = sign(nonce)
    bad = assertion[:-1] + ('a' if assertion[-1] != 'a' else 'b')
    assert client.post('/auth/google/complete', data={'assertion':bad}).headers['location'].endswith('expired')
    saved_nonce = client.cookies.get(auth.CHALLENGE_COOKIE)
    client.cookies.clear()
    assert client.post('/auth/google/complete', data={'assertion':assertion}).headers['location'].endswith('expired')
    client.cookies.set(auth.CHALLENGE_COOKIE, saved_nonce)
    assert client.post('/auth/google/complete', data={'assertion':assertion}).headers['location'] == '/leads'
    # Reusing the signed assertion and original challenge cannot create a second session.
    client.cookies.set(auth.CHALLENGE_COOKIE, saved_nonce)
    assert client.post('/auth/google/complete', data={'assertion':assertion}).headers['location'].endswith('expired')
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(auth.CrmSession)) == 1


def test_expired_and_forged_sessions_cannot_read_contacts(setup):
    client, factory = setup
    login(client)
    with factory() as db:
        db.query(auth.CrmSession).update({'expires_at':auth.now_utc()-timedelta(seconds=1)})
        db.commit()
    assert client.get('/leads').status_code == 401
    client.cookies.clear(); client.cookies.set(auth.SESSION_COOKIE, 'f'*64)
    assert client.get('/leads').status_code == 401


def test_authenticated_mutations_require_same_origin(setup):
    client, _ = setup
    login(client)
    assert client.post('/protected-change', headers={'Origin':ORIGIN}).status_code == 200
    for headers in ({}, {'Origin':'https://attacker.example'}, {'Origin':'null'}):
        assert client.post('/protected-change', headers=headers).status_code == 403
    for origin in ('', 'null'):
        headers = {'Sec-Fetch-Site':'same-origin'}
        if origin:
            headers['Origin'] = origin
        assert client.post('/protected-change', headers=headers).status_code == 200
    for site in ('same-site', 'cross-site', 'none'):
        assert client.post('/protected-change', headers={'Origin':'null','Sec-Fetch-Site':site}).status_code == 403
    assert client.post('/protected-change', headers={'Origin':'https://attacker.example','Sec-Fetch-Site':'same-origin'}).status_code == 403


@pytest.mark.parametrize('value', ['//attacker.example', 'https://attacker.example', '/\\attacker', '/auth/google/start', '/logout', '/login', '/x\n'])
def test_return_destination_cannot_leave_crm_or_restart_login(setup, value):
    client, _ = setup
    nonce, _ = begin(client, value)
    result = client.post('/auth/google/complete', data={'assertion':sign(nonce)})
    assert result.headers['location'] == '/leads'


def test_absent_configuration_does_not_open_unprotected_mode(setup, monkeypatch):
    client, _ = setup
    monkeypatch.delenv('CRM_GOOGLE_SIGNING_KEY')
    assert client.get('/auth/google/start').headers['location'] == '/login?error=unavailable'
    assert client.get('/leads').status_code == 401
    monkeypatch.setenv('CRM_GOOGLE_SIGNING_KEY', TEST_KEY)
    monkeypatch.setenv('CRM_GOOGLE_LOGIN_URL','https://attacker.example/exec')
    assert client.get('/auth/google/start').headers['location'] == '/login?error=unavailable'


def test_golf_form_intake_keeps_its_own_authentication_and_creates_lead(setup):
    client, _ = setup
    payload = {'submission_id':'auth-release-form-check','first_name':'Form','last_name':'Test','phone':'2025550147'}
    assert client.post('/golf/inquiries', json=payload).status_code == 403
    result = client.post('/golf/inquiries', json=payload, headers={'X-Golf-Form-Key':'test-form-key'})
    assert result.status_code == 201 and result.json()['crm_contact_id']
    assert client.post('/api/website/leads', json={}).status_code == 422
    assert client.get('/golf/inquiries').status_code == 401
    preflight = client.options('/api/website/leads', headers={
        'Origin':'https://turning65medicaremadeeasy.com',
        'Access-Control-Request-Method':'POST', 'Access-Control-Request-Headers':'content-type'})
    assert preflight.status_code == 200
    assert preflight.headers['access-control-allow-origin'] == 'https://turning65medicaremadeeasy.com'


def test_login_challenge_creation_is_rate_limited(setup):
    client, factory = setup
    for _ in range(30):
        assert client.get('/auth/google/start').status_code == 303
    assert client.get('/auth/google/start').status_code == 429
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(auth.LoginChallenge)) == 30
