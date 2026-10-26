import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import Lead
from app.golf_integration import router, GolfProfile, GolfInquiryReceipt
from app.services.golf_intake_backup import backup_before_golf_intake


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv('GOLF_FORM_WEBHOOK_KEY', 'test-only-form-key')
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as client:
            yield client, db
    engine.dispose()


def inquiry(**changes):
    return dict(submission_id='form-response-1', first_name='Test', last_name='Golfer',
                phone='202-555-0147', email='', goal='Improve balance',
                experience='New to golf', preferred_contact='Phone call', **changes)


def post(client, payload):
    return client.post('/golf/inquiries', json=payload, headers={'X-Golf-Form-Key': 'test-only-form-key'})


def test_auth_rejects_missing_and_wrong_keys_without_writes(setup):
    client, db = setup
    for headers in ({}, {'X-Golf-Form-Key': 'wrong'}):
        assert client.post('/golf/inquiries', json=inquiry(), headers=headers).status_code == 403
    assert db.scalar(select(func.count()).select_from(Lead)) == 0


def test_creates_golf_lead_with_visible_notes_and_preserves_insurance(setup):
    client, db = setup
    existing = Lead(first_name='Existing', last_name='Insurance', status='Enrolled', notes='Keep me')
    db.add(existing); db.commit()
    result = post(client, inquiry())
    assert result.status_code == 201
    lead = db.get(Lead, result.json()['crm_contact_id'])
    assert lead.lead_source == 'Reedsport Golf lesson form'
    assert 'Improve balance' in lead.notes and 'New to golf' in lead.notes and 'Phone call' in lead.notes
    assert not lead.interested_supplement and not lead.interested_advantage
    assert db.scalar(select(GolfProfile).where(GolfProfile.lead_id == lead.id)).goal == 'Improve balance'
    assert db.scalar(select(func.count()).select_from(GolfInquiryReceipt)) == 1
    db.refresh(existing)
    assert existing.status == 'Enrolled' and existing.notes == 'Keep me'


def test_same_response_retry_returns_same_contact_without_duplicates(setup):
    client, db = setup
    first = post(client, inquiry()).json()
    retry = post(client, inquiry()).json()
    assert first['crm_contact_id'] == retry['crm_contact_id']
    assert not first['already_saved'] and retry['already_saved']
    for model in (Lead, GolfProfile, GolfInquiryReceipt):
        assert db.scalar(select(func.count()).select_from(model)) == 1


def test_separate_responses_never_merge_existing_people_by_name(setup):
    client, db = setup
    a = inquiry(); b = inquiry(); b['submission_id'] = 'form-response-2'
    assert post(client, a).json()['crm_contact_id'] != post(client, b).json()['crm_contact_id']


def test_single_name_and_optional_email_are_supported(setup):
    client, db = setup
    p = inquiry(); p['last_name'] = ''; p['first_name'] = '  Pat  '
    response = post(client, p)
    assert response.status_code == 201
    assert db.get(Lead, response.json()['crm_contact_id']).first_name == 'Pat'


@pytest.mark.parametrize('field,value', [('phone', '123'), ('first_name', '   '), ('submission_id', ''), ('email', 'bad-email')])
def test_invalid_fields_do_not_create_contacts(setup, field, value):
    client, db = setup
    p = inquiry(); p[field] = value
    assert post(client, p).status_code == 422
    assert db.scalar(select(func.count()).select_from(Lead)) == 0


def test_unconfigured_endpoint_fails_closed(setup, monkeypatch):
    client, db = setup
    monkeypatch.delenv('GOLF_FORM_WEBHOOK_KEY')
    assert post(client, inquiry()).status_code == 403


def test_backup_preserves_existing_database_and_runs_only_before_schema(tmp_path):
    path = tmp_path / 'crm.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE sentinel (value TEXT)')
        db.execute("INSERT INTO sentinel VALUES ('existing-contact')")
    engine = create_engine('sqlite:///' + str(path))
    backup_before_golf_intake(engine)
    backups = list((tmp_path / 'backups').glob('*.db'))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as db:
        assert db.execute('SELECT value FROM sentinel').fetchone()[0] == 'existing-contact'
    Base.metadata.create_all(engine)
    backup_before_golf_intake(engine)
    assert len(list((tmp_path / 'backups').glob('*.db'))) == 1
    engine.dispose()
