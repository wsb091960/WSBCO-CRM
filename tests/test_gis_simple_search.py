"""Shared four-field territory and manual-call searches; isolated synthetic data."""
from datetime import date, timedelta
import json
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import Lead
from app import gis_map as gis
from app import call_list_v1 as calls
from app.call_list_gis import ManualCallGeography


@pytest.fixture
def setup():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        app = FastAPI()
        app.include_router(gis.router)
        app.include_router(calls.router)
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as client:
            yield client, db
    engine.dispose()


def contact(db, **kwargs):
    data = dict(first_name='Synthetic', last_name='Contact', address='123 Example St',
                city='Reedsport', state='OR', county='Douglas', zip_code='97467', phone='555-0100')
    data.update(kwargs)
    item = Lead(**data)
    db.add(item)
    db.commit()
    return item


def cache_point(db, lead):
    gis._cache(db)
    db.execute(text('INSERT INTO gis_address_points (lead_id,address_hash,latitude,longitude,result) '
                    'VALUES (:id,:hash,43.7,-124.1,"matched")'),
               {'id': lead.id, 'hash': gis._fingerprint(lead)})
    db.commit()


def test_four_fields_match_identically_in_map_pins_summary_and_call_generation(setup):
    client, db = setup
    wanted = contact(db, city='  REEDSPORT ', county=' Douglas County ', state='or', zip_code='97467-1234')
    contact(db, city='Roseburg', zip_code='97470')
    contact(db, state='WA', city='Reedsport')
    contact(db, city='Reedsport East')
    cache_point(db, wanted)
    params = {'state': 'Oregon', 'county': 'Douglas', 'city': 'Reedsport', 'zip_code': '97467'}
    summary = client.get('/gis/summary', params=params).json()
    points = client.get('/gis/points', params=params).json()
    assert summary['total'] == 1 and points['total'] == 1
    assert [p['id'] for p in points['points']] == [wanted.id]
    assert points['points'][0]['name'] == 'Synthetic Contact'
    assert points['points'][0]['url'] == f'/leads/{wanted.id}'
    assert '123 Example St' in points['points'][0]['address']
    assert 'phone' not in points['points'][0]
    response = client.post('/call-list/generate', data=params)
    assert response.status_code == 200
    items = db.scalars(select(calls.ManualCallItem)).all()
    assert [i.lead_id for i in items] == [wanted.id]
    saved = json.loads(db.get(ManualCallGeography, items[0].batch_id).filters_json)
    assert saved['cities'] == 'reedsport' and saved['geo_mode'] == 'and'


@pytest.mark.parametrize('params,count', [({}, 3), ({'city':'Reedsport'}, 2),
    ({'state':'OR','city':'Reedsport'}, 1), ({'city':'Reedsport East'},0),
    ({'zip_code':'02108'},1)])
def test_single_fields_blanks_empty_results_and_leading_zeros(setup, params, count):
    client, db = setup
    contact(db)
    contact(db, state='MA', county='Suffolk', city='Boston', zip_code='02108-1234')
    contact(db, state='WA', city='Reedsport', county='King', zip_code='98101')
    assert client.get('/gis/summary',params=params).json()['total'] == count
    assert client.get('/gis/points',params=params).json()['total'] == count


def test_invalid_filters_never_broaden_map_or_generate_calls(setup):
    client, db = setup
    contact(db)
    for params in ({'state':'XX'}, {'zip_code':'974'}, {'zip_code':'974%'}):
        assert client.get('/gis/summary',params=params).status_code == 400
        assert client.get('/gis/points',params=params).status_code == 400
        assert client.post('/call-list/generate',data=params).status_code == 400
    assert not db.scalars(select(calls.ManualCallItem)).all()
    # Removed OR controls cannot widen either endpoint through an old URL.
    assert client.get('/gis/summary?state=WA&county=Douglas&mode=or').json()['total'] == 0


def test_search_clear_and_navigation_preserve_pending_calls_and_city_snapshot(setup):
    client, db = setup
    wanted = contact(db)
    contact(db, city='Roseburg')
    client.post('/call-list/generate', data={'cities':'Reedsport'})
    item = db.scalar(select(calls.ManualCallItem))
    batch_id = item.batch_id
    result = client.post(f'/call-list/{wanted.id}/disposition', data={'outcome':'Callback', 'notes':'Follow up'})
    assert result.status_code == 200
    # Finish first list then generate another saved-city list with two pending calls.
    contact(db)
    contact(db)
    client.post('/call-list/generate',data={'cities':'Reedsport'})
    batch = calls.active_batch(db)
    before = [(i.id,i.lead_id,i.completed_at) for i in db.scalars(select(calls.ManualCallItem)).all()]
    client.get('/call-list?states=&counties=&cities=&zips=')
    client.get('/call-list?cities=Roseburg')
    client.post('/call-list/generate',data={'cities':'Roseburg'})
    assert before == [(i.id,i.lead_id,i.completed_at) for i in db.scalars(select(calls.ManualCallItem)).all()]
    response = client.get('/call-list')
    assert 'value="reedsport"' in response.text
    assert 'City: reedsport' in response.text
    assert batch.id != batch_id
    assert db.get(ManualCallGeography,batch.id)


def test_old_or_snapshot_keeps_saved_calls_while_new_search_is_simple(setup):
    client, db = setup
    lead = contact(db)
    batch = calls.ManualCallBatch()
    db.add(batch); db.flush()
    db.add(calls.ManualCallItem(batch_id=batch.id,lead_id=lead.id))
    original = json.dumps({'states':'WA','counties':'Douglas','geo_mode':'or','zips':''})
    db.add(ManualCallGeography(batch_id=batch.id,filters_json=original)); db.commit()
    assert client.get('/call-list').status_code == 200
    assert 'State: WA OR County: douglas' in client.get('/call-list').text
    client.get('/call-list?states=OR&cities=Roseburg')
    assert db.get(ManualCallGeography,batch.id).filters_json == original
    assert db.scalar(select(calls.ManualCallItem)).lead_id == lead.id


def test_geocode_processes_only_the_selected_city(setup, monkeypatch):
    client, db = setup
    selected = contact(db)
    contact(db,city='Roseburg')
    monkeypatch.setenv('ARCGIS_API_KEY','synthetic-token')
    processed=[]
    def fake(lead, token):
        processed.append(lead.id)
        return (43.7,-124.1,99,'PointAddress')
    monkeypatch.setattr(gis,'_geocode',fake)
    result=client.post('/gis/geocode-batch?city=Reedsport')
    assert result.status_code == 200 and result.json()['matched'] == 1
    assert processed == [selected.id]


def test_forms_are_simple_and_map_link_keeps_city(setup):
    import re
    client, db = setup
    contact(db)
    for url, form_id, names in [('/gis','gis-form',['state','county','city','zip_code']),
                                ('/call-list','geo-search',['states','counties','cities','zips'])]:
        html=client.get(url).text
        form=re.search(r'<form[^>]*id="'+form_id+r'"[^>]*>(.*?)</form>',html,re.S).group(1)
        assert re.findall(r'<input[^>]*name="([^"]+)"',form) == names
        assert '<select' not in form
        assert 'id="mode"' not in form and 'id="geo-mode"' not in form
    html=client.get('/call-list?cities=Reedsport').text
    url=re.search(r'href="([^"]+)"[^>]*>View Territory Map</a>',html).group(1)
    from html import unescape
    assert parse_qs(urlparse(unescape(url)).query)['city'] == ['reedsport']


def test_geocoding_recognizes_full_state_names_and_rejects_nonfinite_coordinates(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    item = SimpleNamespace(address='123 Example St', city='Seattle', state='WA', zip_code='98101')
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b''
    monkeypatch.setattr(gis, 'urlopen', lambda *a, **kw: response)
    candidate = {'score':99, 'attributes':{'Region':'Washington','Postal':'98101','Addr_type':'PointAddress'},
                 'location':{'x':-122.3,'y':47.6}}
    monkeypatch.setattr(gis.json, 'load', lambda _: {'candidates':[candidate]})
    assert gis._geocode(item, 'synthetic-token') == (47.6,-122.3,99.0,'PointAddress')
    candidate['location']['y'] = float('nan')
    assert gis._geocode(item,'synthetic-token') is None
