"""Market snapshots, real plan areas, and synthetic private birthday cohorts."""
import csv
from datetime import date, timedelta
import io
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth, call_list_v1
from app.database import Base, get_db
from app.gis_map import _cache, _fingerprint
from app.golf_integration import GolfProfile
from app.models import Lead
from app.services import turning65 as service
from app.turning65 import router, safe_csv
from app.services import county_income


@pytest.fixture
def setup(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    app = FastAPI()
    app.include_router(router)
    def db():
        with sessions() as session:
            yield session
    app.dependency_overrides[get_db] = db
    monkeypatch.setattr(service, 'local_today', lambda: date(2026, 11, 19))
    with TestClient(app) as client:
        yield client, sessions, app
    engine.dispose()


@pytest.mark.parametrize('state,count', [('OR',36),('CA',58),('WV',55),('TX',254)])
def test_income_coverage_preserves_counties_and_reports_confidence_bounds(setup, state, count):
    client, _, _ = setup
    response = client.get('/turning65', params={'state':state, 'overlay':'income'})
    assert response.status_code == 200
    c = response.context
    assert len(c['scoped']) == count
    assert c['income']['income_year'] == 2024 and c['population']['reference_date'] == '2025-07-01'
    assert len(c['income']['source_sha256']) == 64
    for row in c['scoped']:
        assert 0 < row['income_low'] <= row['income'] <= row['income_high']
        assert row['shade_value'] == row['income']
    values = [row['income'] for row in c['ranked']]
    assert values == sorted(values, reverse=True)
    assert 'all households' in response.text and '2024 dollars' in response.text
    assert c['map_config']['points'] == []


@pytest.mark.parametrize('age,measure', [('64','count'),('64','share'),('65plus','count'),('65plus','share')])
def test_both_overlays_keep_age_and_income_separate_and_retain_selection(setup, age, measure):
    client, _, _ = setup
    response = client.get('/turning65', params={'state':'TX','county':'48029', 'overlay':'both',
        'age':age, 'measure':measure, 'carrier':'Clover Health', 'map_view':'outline'})
    assert response.status_code == 200
    c = response.context
    assert len(c['scoped']) == 7
    selected = c['selected']
    assert selected['value'] == selected['age64' if age == '64' else 'age65plus']
    assert selected['shade_value'] == selected['income']
    assert selected['bubble_radius'] > 0
    # Circle area scales with the chosen age count/share; income does not affect circle size.
    smaller, larger = sorted(c['scoped'], key=lambda r:r['bubble_radius'])[::6]
    key = 'share' if measure == 'share' else 'value'
    assert (larger['bubble_radius']/smaller['bubble_radius'])**2 == pytest.approx(larger[key]/smaller[key])
    for url in [c['outline_url'],c['esri_url'],c['csv_url'],c['contacts_url'],*c['state_links'].values()]:
        assert 'overlay=both' in url
    assert 'county=48029' in c['overlay_links']['income']
    assert 't65-age-bubble' in response.text and '90% confidence range' in response.text
    assert 'Income &amp; Age Layers' in response.text


def test_income_csv_is_county_based_and_does_not_sum_medians(setup):
    client, _, _ = setup
    response = client.get('/turning65/export.csv?state=OR&overlay=both')
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == 36
    assert all(row['Income year']=='2024' and row['Income dollars year']=='2024' for row in rows)
    assert all(row['Selected overlay']=='both' for row in rows)
    assert all(row['Income source'].startswith('https://www2.census.gov/') for row in rows)
    assert all(int(row['Median household income']) > 0 for row in rows)
    assert not any('email' in key.lower() or 'phone' in key.lower() for key in rows[0])


def test_income_no_data_is_distinct_and_contacts_do_not_use_income_shading(setup, monkeypatch):
    client, _, _ = setup
    original = county_income.income('OR')
    data = {**original, 'counties': {k:dict(v) for k,v in original['counties'].items()}}
    data['counties']['41019'] = dict.fromkeys(('income','income_low','income_high'))
    monkeypatch.setattr(county_income, 'income', lambda _:data)
    response = client.get('/turning65?county=41019&overlay=income&map_view=outline')
    assert response.status_code == 200 and response.context['selected']['bucket'] is None
    assert '--t65-fill:#a5b3bc' in response.text and 'Unavailable' in response.text
    assert response.context['ranked'][-1]['id'] == '41019'
    contacts = client.get('/turning65?layer=contacts&overlay=both')
    assert contacts.context['map_config']['overlay']=='age'
    assert contacts.context['map_config']['thresholds']==[1,5,20,100]
    assert 'County data overlays' not in contacts.text


def test_invalid_overlay_rejected_on_map_contacts_and_export(setup):
    client, _, _ = setup
    for path in ('/turning65','/turning65/contacts','/turning65/export.csv'):
        assert client.get(path+'?overlay=invalid').status_code==422


def test_income_snapshot_failure_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(county_income, 'DATA_DIR', tmp_path)
    county_income.income.cache_clear()
    try:
        with pytest.raises(Exception) as exc:
            county_income.income('OR')
        assert exc.value.status_code==503
        (tmp_path/'or_2024.json').write_text('{}')
        with pytest.raises(Exception) as exc:
            county_income.income('OR')
        assert exc.value.status_code==503
    finally:
        county_income.income.cache_clear()


@pytest.mark.parametrize('state,count,total', [('OR',36,51489),('CA',58,450325),('WV',55,24012),('TX',254,332178)])
def test_full_state_has_correct_counties_and_exact_age64_totals(setup,state,count,total):
    client,_,_=setup
    response=client.get('/turning65',params={'state':state})
    assert response.status_code==200
    c=response.context
    assert len(c['scoped'])==count and c['totals']['age64']==total
    assert len(c['map_config']['counties'])==count
    assert all(row['id'].startswith(service.FIPS[state]) for row in c['counties'])
    assert 'July 1, 2025' in response.text and 'Turning 65 Heat Map' in response.text
    assert response.headers['cache-control']=='no-store'
    assert c['totals']['matching']==0 and c['map_config']['points']==[]


def test_clover_area_deduplicates_two_five_star_plans_and_keeps_population_year(setup):
    client,_,_=setup
    response=client.get('/turning65',params={'state':'TX','carrier':'Clover Health','stars':'5'})
    assert response.status_code==200
    c=response.context
    assert {r['name'] for r in c['scoped']}=={'Atascosa','Bandera','Bexar','Comal','Guadalupe','Medina','Wilson'}
    assert len(c['area']['plans'])==2
    assert c['totals']['age65plus']==423939
    assert c['area']['catalog']['year']==2027 and c['population']['reference_date']=='2025-07-01'
    exact=client.get('/turning65',params={'state':'TX','plan_id':'H5141-025-000','stars':'5'})
    assert {r['id'] for r in exact.context['scoped']}=={r['id'] for r in c['scoped']}
    old=client.get('/turning65',params={'state':'TX','carrier':'Clover Health','stars':'5','year':2026})
    assert old.status_code==200 and old.context['scoped']==[]
    assert 'No counties match' in old.text


def test_bexar_selection_share_view_outline_and_plan_links(setup):
    client,_,_=setup
    response=client.get('/turning65?state=TX&county=48029&map_view=outline&measure=share')
    c=response.context
    assert c['selected']['age64']==21564 and c['selected']['age65plus']==309662
    assert c['selected']['population']==2160088
    assert c['selected']['share']==pytest.approx(21564/2160088*100)
    assert 'county=48029' in c['selected']['plans_url'] and 'year=2027' in c['selected']['plans_url']
    assert response.text.count('class="t65-county t65-bucket-')==254
    assert 't65-esri-map' not in response.text
    assert c['ranked'][0]['share']>=c['ranked'][1]['share']
    for url in c['state_links'].values():
        assert 'carrier=' not in url and 'county=' not in url and 'plan_id=' not in url


def test_service_area_filter_clears_out_of_area_selection_without_broadening(setup):
    client,_,_=setup
    response=client.get('/turning65?state=TX&county=48201&carrier=Clover%20Health')
    assert response.status_code==200 and response.context['selected'] is None
    assert len(response.context['scoped'])==7 and response.context['notice']


@pytest.mark.parametrize('query', ['state=FL','state=TX&county=41019','year=2028','stars=3',
    'window=99','age=60to64','measure=bad','layer=leads','map_view=bad',
    'state=OR&carrier=Clover%20Health','state=TX&plan_id=bad',
    'window=custom&date_from=2020-01-01&date_to=2027-01-01',
    'window=custom&date_from=2027-03-01&date_to=2027-02-01',
    'window=custom&date_from=not-a-date'])
def test_invalid_filters_do_not_return_an_unfiltered_market(setup,query):
    client,_,_=setup
    assert client.get('/turning65?'+query).status_code==422
    assert client.get('/turning65/export.csv?'+query).status_code==422


def add(db,name,dob,county='Bexar',state='TX',**changes):
    lead=Lead(first_name=name,last_name='Synthetic',date_of_birth=dob,county=county,state=state,
              address='123 Example Street',city='San Antonio',zip_code='78201',**changes)
    db.add(lead);db.flush()
    return lead


def pin(db,lead,address_hash=None,lat=29.4,lon=-98.5):
    db.execute(text('INSERT INTO gis_address_points (lead_id,address_hash,latitude,longitude,result) '
                    'VALUES (:id,:hash,:lat,:lon,\'matched\')'),
               {'id':lead.id,'hash':address_hash or _fingerprint(lead),'lat':lat,'lon':lon})


def test_dob_targeting_includes_boundaries_excludes_unknowns_golf_and_stale_locations(setup):
    client,sessions,_=setup
    with sessions() as db:
        _cache(db)
        first=add(db,'Today',date(1961,11,19),phone='541-555-0100')
        last=add(db,'Boundary',date(1962,5,19))
        add(db,'AfterWindow',date(1962,5,20))
        add(db,'BeforeWindow',date(1961,11,18))
        add(db,'MissingDOB',None)
        add(db,'FutureDOB',date(2030,1,1))
        add(db,'Unassigned',date(1962,1,1),county='')
        stale=add(db,'OldAddress',date(1962,1,1))
        add(db,'OtherCounty',date(1962,1,1),county='Harris')
        golf=add(db,'GolfOnly',date(1962,1,1))
        db.add(GolfProfile(lead_id=golf.id))
        pin(db,first)
        pin(db,last,lat=float('inf'))
        pin(db,stale,address_hash='outdated')
        db.commit()
    response=client.get('/turning65?state=TX&county=48029&layer=contacts')
    c=response.context
    assert {m['name'].split()[0] for m in c['matches']}=={'Today','Boundary'}
    assert c['selected']['matching']==2
    assert c['targeting']['counts']['missing_dob']==1 and c['targeting']['counts']['invalid_dob']==1
    assert c['targeting']['counts']['unresolved_county']==2
    assert len(c['map_config']['points'])==1
    assert c['map_config']['points'][0]['name']=='Today Synthetic'
    assert 'date_of_birth' not in json.dumps(c['map_config'])
    listing=client.get(c['contacts_url'])
    assert listing.context['contact_count']==2
    assert '541-555-0100' in listing.text and 'BeforeWindow' not in listing.text
    assert 'MissingDOB' not in listing.text and 'OtherCounty' not in listing.text
    twelve=client.get('/turning65/contacts?state=TX&county=48029&window=12')
    assert twelve.context['contact_count']==3
    current64=client.get('/turning65/contacts?state=TX&county=48029&window=age64')
    assert current64.context['contact_count']==2  # Already-65 contacts are not age 64.
    custom=client.get('/turning65/contacts?state=TX&county=48029&window=custom&date_from=2027-05-20&date_to=2027-05-20')
    assert [m['name'] for m in custom.context['matches']]==['AfterWindow Synthetic']


def test_contact_popup_payload_and_html_keep_contact_text_inert(setup):
    client,sessions,_=setup
    with sessions() as db:
        _cache(db)
        lead=add(db,'</script><img src=x onerror=alert(1)>',date(1962,1,1),notes='PRIVATE NOTE',medicare_mbi='PRIVATE MBI')
        pin(db,lead);db.commit()
    r=client.get('/turning65?state=TX&layer=contacts')
    assert '</script><img src=x' not in r.text
    assert 'PRIVATE NOTE' not in r.text and 'PRIVATE MBI' not in r.text
    listing=client.get('/turning65/contacts?state=TX')
    assert '&lt;/script&gt;&lt;img' in listing.text


def test_birthday_calendar_arithmetic_handles_leap_days_and_month_ends():
    assert service.birthday_in_year(date(1960,2,29),2025)==date(2025,2,28)
    assert service.current_age(date(1960,2,29),date(2025,2,27))==64
    assert service.current_age(date(1960,2,29),date(2025,2,28))==65
    assert service.add_months(date(2026,8,31),6)==date(2027,2,28)
    assert service.add_months(date(2027,12,31),2)==date(2028,2,29)
    assert service.current_age(date(2027,1,1),date(2026,12,31)) is None
    assert service.current_age(None,date(2026,12,31)) is None


def test_export_uses_unique_counties_exact_counts_sources_and_no_contact_identity(setup):
    client,sessions,_=setup
    with sessions.begin() as db:
        add(db,'PRIVATE CONTACT',date(1962,1,1),phone='5415550100')
    response=client.get('/turning65/export.csv?state=TX&carrier=Clover%20Health&stars=5')
    rows=list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows)==7
    assert sum(int(r['Residents age 65+']) for r in rows)==423939
    bexar=next(r for r in rows if r['County']=='Bexar')
    assert int(bexar['Residents exactly age 64'])==21564
    assert bexar['Plan year']=='2027' and bexar['Population reference date']=='2025-07-01'
    assert len(bexar['Census SHA256'])==64 and 'census.gov' in bexar['Census source']
    assert 'PRIVATE CONTACT' not in response.text and '5415550100' not in response.text
    assert response.headers['cache-control']=='no-store'
    assert safe_csv('=SUM(A1:A2)').startswith("'")


def test_missing_population_file_fails_explicitly_without_inventing_zero(setup,monkeypatch,tmp_path):
    client,_,_=setup
    service.population.cache_clear()
    monkeypatch.setattr(service,'DATA_DIR',tmp_path)
    try:
        r=client.get('/turning65?state=WV')
        assert r.status_code==503 and 'unavailable' in r.text
    finally:
        service.population.cache_clear()


def test_contact_pages_map_and_csv_require_owner_session(setup,monkeypatch):
    _,sessions,_=setup
    app=FastAPI()
    app.include_router(router)
    def db():
        with sessions() as session:
            yield session
    app.dependency_overrides[get_db]=db
    monkeypatch.setattr(auth,'SessionLocal',sessions)
    app.add_middleware(auth.OwnerAuthMiddleware)
    with TestClient(app,base_url='https://wsbco-crm.onrender.com',follow_redirects=False) as client:
        for path in ['/turning65','/turning65/contacts','/turning65/export.csv']:
            r=client.get(path,headers={'Accept':'application/json'})
            assert r.status_code==401
        r=client.get('/turning65?state=CA',headers={'Accept':'text/html'})
        assert r.status_code==303 and 'next=' in r.headers['location']
