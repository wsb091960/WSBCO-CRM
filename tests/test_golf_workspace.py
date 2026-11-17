from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth, call_list_v1
from app.database import Base, get_db
from app.golf_integration import GolfProfile, router as golf_router
from app.models import Lead
from app.routers.leads import router as leads_router


@pytest.fixture
def workspace(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(auth, 'SessionLocal', factory)
    monkeypatch.setenv('CRM_OWNER_EMAIL', 'williamsburton@gmail.com')
    monkeypatch.setenv('CRM_PUBLIC_URL', 'https://wsbco-crm.onrender.com')
    app = FastAPI()
    app.include_router(leads_router)
    app.include_router(golf_router)
    app.add_middleware(auth.OwnerAuthMiddleware)
    def override():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = override
    with factory() as db:
        for name, stage, status, contacted in [
            ('FreshGolfer', 'Inquiry', 'New', False),
            ('HandledGolfer', 'Contacted', 'New', False),
            ('ActiveGolfer', 'Active student', 'New', False),
            ('DncGolfer', 'Inquiry', 'Do Not Call', False),
            ('CalledGolfer', 'Inquiry', 'New', True),
        ]:
            lead = Lead(first_name=name, last_name='Example', phone='2025550147', status=status,
                        notes='Keep original notes', last_contact=datetime.utcnow() if contacted else None)
            db.add(lead)
            db.flush()
            db.add(GolfProfile(lead_id=lead.id, stage=stage, goal='<script>unsafe</script>'))
        db.add(Lead(first_name='InsuranceOnly', last_name='Example', status='New'))
        db.add(GolfProfile(lead_id=99999, stage='Inquiry'))
        db.add(auth.CrmSession(token_hash=auth.digest('a' * 64), owner_email='williamsburton@gmail.com',
                               expires_at=auth.now_utc() + timedelta(hours=1)))
        db.commit()
    with TestClient(app, base_url='https://wsbco-crm.onrender.com', follow_redirects=False) as client:
        client.cookies.set(auth.SESSION_COOKIE, 'a' * 64)
        yield client, factory
    engine.dispose()


def test_summary_counts_match_clickthrough_and_ignore_orphan_profiles(workspace):
    client, _ = workspace
    page = client.get('/leads')
    assert page.status_code == 200
    assert page.context['golf_count'] == 5
    assert page.context['new_golf_count'] == 1
    golfers = client.get('/leads?workspace=golf')
    assert len(golfers.context['leads']) == 5
    assert 'InsuranceOnly' not in golfers.text
    new = client.get('/leads?workspace=golf&golf_filter=new')
    assert [lead.first_name for lead in new.context['leads']] == ['FreshGolfer']
    assert 'View Golf Contacts' in page.text
    assert '<script>unsafe</script>' not in golfers.text
    assert '&lt;script&gt;unsafe&lt;/script&gt;' in golfers.text


def test_workspace_search_status_and_empty_results(workspace):
    client, _ = workspace
    page = client.get('/leads?workspace=golf&q=InsuranceOnly')
    assert page.context['leads'] == []
    assert 'name="workspace" value="golf"' in page.text
    assert len(client.get('/leads?workspace=golf&status=Do%20Not%20Call').context['leads']) == 1
    assert [lead.first_name for lead in client.get('/leads?workspace=medicare').context['leads']] == ['InsuranceOnly']
    assert len(client.get('/leads').context['leads']) == 6


def test_mark_contacted_updates_count_without_changing_insurance_or_logging_a_call(workspace):
    client, factory = workspace
    new = client.get('/leads?workspace=golf&golf_filter=new')
    lead_id = new.context['leads'][0].id
    assert 'Mark Contacted' in client.get(f'/leads/{lead_id}').text
    for _ in range(2):
        response = client.post(f'/golf/contacts/{lead_id}/contacted', headers={'Origin': 'https://wsbco-crm.onrender.com'})
        assert response.status_code == 303
    assert client.get('/leads').context['new_golf_count'] == 0
    assert client.get('/leads').context['golf_count'] == 5
    with factory() as db:
        lead = db.get(Lead, lead_id)
        assert lead.status == 'New' and lead.notes == 'Keep original notes'
        assert lead.call_attempts == 0 and lead.last_contact is None
        assert db.scalar(select(GolfProfile).where(GolfProfile.lead_id == lead_id)).stage == 'Contacted'
    assert client.post('/golf/contacts/6/contacted', headers={'Origin': 'https://wsbco-crm.onrender.com'}).status_code == 404
    assert 'caught up' in client.get('/leads?workspace=golf&golf_filter=new').text


def test_counts_require_owner_and_contacted_action_requires_same_origin(workspace):
    client, _ = workspace
    home = client.get('/')
    assert home.context['golf_count'] == 5 and 'New Golf Requests' in home.text
    assert client.post('/golf/contacts/1/contacted', headers={'Origin': 'https://untrusted.example'}).status_code == 403
    client.cookies.clear()
    home = client.get('/')
    assert 'golf_count' not in home.context and 'New Golf Requests' not in home.text
    assert client.get('/leads?workspace=golf').status_code == 401
    assert client.post('/golf/contacts/1/contacted').status_code == 401
