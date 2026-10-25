"""Manual contact entry and list entry must represent the same saved call."""
from datetime import date, timedelta
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import Lead, CallLog
from app.routers import leads
from app import call_list_v1 as calls, activity_v33 as activity
from app.services.manual_calls import save_manual_call, ManualCallSubmission

@pytest.fixture
def setup(tmp_path, monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(activity, 'DB', tmp_path/'activities.db')
    with Session(engine) as db:
        app = FastAPI()
        for router in (leads.router, calls.router, activity.router):
            app.include_router(router)
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as client:
            yield client, db
    engine.dispose()

def contact(db, **fields):
    lead = Lead(first_name='Test',last_name='Contact',phone='555-123-4567',**fields)
    db.add(lead);db.commit()
    return lead

def payload(**fields):
    return dict(outcome='No Answer',submission_token=str(uuid4()),notes='Manual phone call',**fields)

def count(db):
    return db.scalar(select(func.count()).select_from(CallLog))

def test_contact_defaults_to_unlocked_manual_form_without_logging(setup):
    client,db=setup;c=contact(db)
    page=client.get(f'/leads/{c.id}')
    assert page.status_code == 200
    assert f'action="/leads/{c.id}/manual-call"' in page.text
    assert 'MANUAL CALLING' in page.text and 'Start a call to record' not in page.text
    assert 'CALL CONTACT' not in page.text and page.text.count(f'action="/leads/{c.id}/call"')==1
    assert 'name="outcome" required' in page.text
    assert count(db)==0 and c.call_attempts==0

def test_standalone_call_is_saved_once_and_keeps_lead_status(setup):
    client,db=setup;c=contact(db,status='Interested')
    data=payload(next_follow_up=str(date.today()+timedelta(days=2)))
    for _ in range(2):
        assert client.post(f'/leads/{c.id}/manual-call',data=data).status_code==200
    assert count(db)==1 and c.call_attempts==1 and c.status=='Interested'
    assert c.follow_up_type=='Call' and c.next_follow_up==date.today()+timedelta(days=2)
    history=client.get(f'/api/leads/{c.id}/activities').json()['activities']
    assert len(history)==1 and history[0]['outcome']=='No Answer'
    assert history[0]['detail']=='Manual phone call'
    assert client.get('/').status_code==200

def test_save_next_syncs_list_and_contact_and_blocks_cross_page_duplicate(setup):
    client,db=setup;a=contact(db);b=contact(db)
    client.post('/call-list/generate')
    item=db.scalar(select(calls.ManualCallItem).where(calls.ManualCallItem.lead_id==a.id))
    data=payload(batch_item_id=str(item.id),after_save='next')
    r=client.post(f'/leads/{a.id}/manual-call',data=data,follow_redirects=False)
    assert r.status_code==303 and f'/leads/{b.id}' in r.headers['location']
    assert item.completed_at and a.call_attempts==1
    assert client.post(f'/call-list/{a.id}/disposition',data={'outcome':'Interested','batch_item_id':str(item.id)}).status_code==409
    assert client.post(f'/leads/{a.id}/manual-call',data=data).status_code==200
    assert count(db)==1
    page=client.get('/call-list').text
    assert '1 calls logged' in page and 'Manual phone call' in page

def test_list_save_appears_in_contact_timeline(setup):
    client,db=setup;c=contact(db)
    client.post('/call-list/generate')
    assert client.post(f'/call-list/{c.id}/disposition',data={'outcome':'Voicemail','notes':'Left callback number'}).status_code==200
    events=client.get(f'/api/leads/{c.id}/activities').json()['activities']
    assert len(events)==1 and events[0]['outcome']=='Voicemail'
    assert 'Completed list' in client.get('/call-list').text
    assert count(db)==1

def test_skip_never_logs_or_counts_call_and_dnc_does_not_trap_list(setup):
    client,db=setup;c=contact(db)
    client.post('/call-list/generate')
    item=db.scalar(select(calls.ManualCallItem))
    c.status='Do Not Call';db.commit()
    assert client.post(f'/call-list/items/{item.id}/skip').status_code==200
    assert client.post(f'/call-list/items/{item.id}/skip').status_code==200
    assert count(db)==0 and c.call_attempts==0 and c.last_contact is None
    page=client.get('/call-list').text
    assert '1 skipped' in page and 'Skipped — no call logged' in page
    assert db.get(calls.ManualCallBatch,item.batch_id).completed_at

@pytest.mark.parametrize('field,value',[('outcome','Bogus'),('next_follow_up','2026-99-99'),('submission_token','')])
def test_invalid_form_preserves_notes_and_saves_nothing(setup,field,value):
    client,db=setup;c=contact(db);data=payload();data[field]=value
    r=client.post(f'/leads/{c.id}/manual-call',data=data)
    assert r.status_code==400 and 'Manual phone call' in r.text
    assert count(db)==0 and c.call_attempts==0

def test_stale_dnc_or_missing_phone_rejected_at_save(setup):
    client,db=setup;c=contact(db)
    data=payload();c.status='Do Not Call';db.commit()
    assert client.post(f'/leads/{c.id}/manual-call',data=data).status_code==403
    c.status='New';c.phone='none';db.commit()
    assert client.post(f'/leads/{c.id}/manual-call',data=data).status_code==400
    assert count(db)==0

def test_stale_form_cannot_complete_new_batch(setup):
    client,db=setup;c=contact(db)
    client.post('/call-list/generate');old=db.scalar(select(calls.ManualCallItem))
    client.post(f'/call-list/items/{old.id}/skip')
    client.post('/call-list/generate')
    assert client.post(f'/call-list/{c.id}/disposition',data={'outcome':'Connected','batch_item_id':str(old.id)}).status_code==409
    assert count(db)==0

def test_open_form_before_list_creation_remains_idempotent(setup):
    client,db=setup;c=contact(db);data=payload()
    client.post('/call-list/generate')
    client.post(f'/leads/{c.id}/manual-call',data=data)
    client.post(f'/leads/{c.id}/manual-call',data=data)
    assert count(db)==1 and c.call_attempts==1

def test_old_standalone_form_does_not_complete_later_list(setup):
    client,db=setup;c=contact(db);data=payload()
    client.post(f'/leads/{c.id}/manual-call',data=data)
    # Make the contact eligible on another day, simulating a future list.
    c.last_contact=None
    for log in db.scalars(select(CallLog)).all():log.started_at=log.started_at-timedelta(days=2)
    db.commit();client.post('/call-list/generate')
    item=db.scalar(select(calls.ManualCallItem))
    client.post(f'/leads/{c.id}/manual-call',data=data)
    assert count(db)==1 and item.completed_at is None

def test_concurrent_duplicate_submission_has_one_log_and_increment(tmp_path):
    engine=create_engine('sqlite:///'+str(tmp_path/'concurrent.db'),connect_args={'check_same_thread':False})
    Base.metadata.create_all(engine)
    with Session(engine) as db:c=contact(db);lead_id=c.id
    data=payload()
    def save(_):
        with Session(engine) as db:return save_manual_call(db,db.get(Lead,lead_id),data)
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(save,range(2)))
    with Session(engine) as db:
        assert count(db)==1 and db.get(Lead,lead_id).call_attempts==1
    assert sorted(results)==[False,True]
    engine.dispose()
