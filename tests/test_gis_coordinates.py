"""Verified coordinate restoration uses synthetic data and never calls a geocoder."""
import csv,io,json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine,select,text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.database import Base,get_db
from app.models import Lead
from app import gis_map as gis,imports_v35 as imports,call_list_v1 as calls


@pytest.fixture
def setup():
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        app=FastAPI();app.include_router(gis.router);app.include_router(imports.router)
        app.dependency_overrides[get_db]=lambda:db
        with TestClient(app) as client:
            lead=Lead(first_name='Test',last_name='Person',address='123 Main St',city='Reedsport',county='Douglas',state='OR',zip_code='97467',phone='555-0100',notes='Retain notes',status='Callback')
            db.add(lead);db.commit()
            client.get('/imports')
            yield client,db,lead
    engine.dispose()


def source(**overrides):
    row={'Contact ID':'999999','First Name':'TEST','Last Name':'Person','Address1':'123 Main St.','City':'Reedsport','State':'Oregon','Zip':'97467-1234','GIS Status':'Matched','Needs Review':'No','GIS County':'Douglas County','GIS State':'OR','GIS ZIP':'97467','GIS Latitude':'43.7','GIS Longitude':'-124.1','GIS Source':'Synthetic verified source','Coordinate Precision':'Street-range estimate'}
    row.update(overrides)
    return row


def data(rows):
    f=io.StringIO(newline='');w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    return f.getvalue().encode()


def post(client,rows,**fields):
    return client.post('/gis/coordinates/restore',data={'csrf':client.cookies.get('crm_import_browser'),**fields},files={'file':('gis.csv',data(rows),'text/csv')})


def test_preview_commit_restore_and_repeat_preserves_existing(setup):
    client,db,lead=setup
    preview=post(client,[source()]);assert preview.status_code==200
    assert preview.json()['matched']==1
    assert client.get('/gis/points?county=Douglas').json()['points']==[]
    result=post(client,[source()],commit='1',signature=preview.json()['signature'])
    assert result.status_code==200 and result.json()['restored']==1
    points=client.get('/gis/points?county=Douglas').json()['points']
    assert len(points)==1 and points[0]['id']==lead.id and points[0]['lat']==43.7
    assert lead.status=='Callback' and lead.notes=='Retain notes'
    assert db.scalar(select(Lead.id))==lead.id
    assert post(client,[source()],commit='1',signature=preview.json()['signature']).json()['preserved']==1


@pytest.mark.parametrize('change',[{'GIS Status':'Review candidate'},{'Needs Review':'Yes'},
    {'GIS Latitude':'nan'},{'GIS Longitude':'inf'},{'GIS Latitude':'-124'},
    {'GIS State':'WA'},{'GIS ZIP':'00001'},{'First Name':'Another person'}])
def test_review_invalid_and_unrelated_coordinates_are_not_restored(setup,change):
    client,db,lead=setup
    preview=post(client,[source(**change)]).json()
    assert preview['matched']==0
    result=post(client,[source(**change)],commit='1',signature=preview['signature'])
    assert result.json()['restored']==0
    assert client.get('/gis/points?county=Douglas').json()['points']==[]


def test_conflicting_coordinates_for_same_identity_require_review(setup):
    client,db,lead=setup
    result=post(client,[source(),source(**{'GIS Longitude':'-123.8'})]).json()
    assert result['matched']==0 and result['ambiguous']==1


def test_changed_address_between_preview_and_commit_does_not_get_stale_coordinates(setup):
    client,db,lead=setup
    preview=post(client,[source()]).json()
    lead.address='987 Another St';db.commit()
    assert post(client,[source()],commit='1',signature=preview['signature']).status_code==409


def test_county_conflict_and_csrf_protection(setup):
    client,db,lead=setup
    assert client.post('/gis/coordinates/restore',data={'csrf':'invalid'},files={'file':('gis.csv',data([source()]))}).status_code==403
    assert post(client,[source(**{'GIS County':'Coos'})]).json()['ambiguous']==1
