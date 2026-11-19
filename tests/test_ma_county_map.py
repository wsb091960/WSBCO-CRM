from datetime import timedelta
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth, ma_county_map as ma
from app.database import Base


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(ma.router)
    with TestClient(app) as client:
        yield client


def test_map_has_all_55_real_counties_and_keyboard_links(client):
    page = client.get('/ma-map')
    assert page.status_code == 200
    assert len(page.context['counties']) == 55
    assert {c['id'] for c in page.context['counties']} == set(ma.load_catalog(2027)['county_plans'])
    assert page.text.count('class="ma-county"') == 55
    assert 'aria-label="Kanawha County, 57 plans"' in page.text
    assert 'value="54039"' in page.text
    assert 'name="year"' in page.text and '2026' in page.text and '2027' in page.text
    assert not page.context['plans']  # Do not substitute a default county.


@pytest.mark.parametrize('year,rows', [(2026, 2526), (2027, 2519)])
def test_bundled_catalog_has_every_county_and_no_pdp_or_duplicate_rows(year, rows):
    data = ma.load_catalog(year)
    assert data['county_plan_rows'] == rows
    assert sum(len(ids) for ids in data['county_plans'].values()) == rows
    linked = set()
    for county_id, ids in data['county_plans'].items():
        assert county_id.startswith('54') and len(county_id) == 5
        assert len(ids) == len(set(ids))
        linked.update(ids)
    assert linked == set(data['plans'])
    assert {p['category'] for p in data['plans'].values()} == {'MA', 'MA-PD', 'SNP'}
    assert {p['year'] for p in data['plans'].values()} == {year}
    assert data['source_updated'] and len(data['source_sha256']) == 64


def test_all_insurers_and_coverage_types_are_default_then_filters_apply(client):
    page = client.get('/ma-map?county=54039')
    all_plans = page.context['plans']
    assert len(all_plans) == 57 and page.context['insurer_count'] == 9
    assert {p['part_d'] for p in all_plans} == {'Yes', 'No'}
    assert {p['snp'] for p in all_plans} == {'Yes', 'No'}
    with_drugs = client.get('/ma-map?county=54039&coverage=with').context['plans']
    without_drugs = client.get('/ma-map?county=54039&coverage=without').context['plans']
    assert len(with_drugs) + len(without_drugs) == len(all_plans)
    assert all(p['part_d'] == 'No' for p in without_drugs)
    assert all(p['monthly_premium'] == p['part_c_premium'] for p in without_drugs)
    assert all(p['monthly_premium'] == p['premium'] for p in with_drugs)
    snps = client.get('/ma-map?county=54039&eligibility=snp').context['plans']
    general = client.get('/ma-map?county=54039&eligibility=general').context['plans']
    assert len(snps) + len(general) == len(all_plans)
    brand = all_plans[0]['carrier']
    filtered = client.get('/ma-map', params={'county': '54039', 'carrier': brand}).context['plans']
    assert filtered and all(p['carrier'] == brand for p in filtered)


def test_comparison_uses_selected_county_and_year_values_without_invented_benefits(client):
    plans = client.get('/ma-map?county=54039&year=2026').context['plans'][:3]
    params = [('county', '54039'), ('year', '2026')] + [('selected_ids', p['id']) for p in plans]
    page = client.get('/ma-map', params=params)
    assert page.status_code == 200
    assert page.context['chosen'] == plans
    assert 'Selected 2026 plans listed in Kanawha County' in page.text
    for plan in plans:
        assert plan['premium'] in page.text and plan['moop'] in page.text
    assert 'Not supplied in CMS Landscape' in page.text
    assert 'not saved to a contact' in page.text


def test_invalid_counties_years_and_plan_selections_are_rejected(client):
    ids = list(ma.load_catalog(2027)['plans'])
    invalid = [
        [('county', '41019')], [('county', 'fake')], [('year', '2028')],
        [('coverage', 'wrong')], [('eligibility', 'wrong')], [('selected_ids', ids[0])],
        [('county', '54039'), ('carrier', 'Invented insurer')],
        [('county', '54039'), ('selected_ids', '<script>fake</script>')],
        [('county', '54039'), ('selected_ids', ids[0]), ('selected_ids', ids[0])],
        [('county', '54039')] + [('selected_ids', key) for key in ids[:4]],
    ]
    for params in invalid:
        assert client.get('/ma-map', params=params).status_code == 422
    kanawha = ma.plan_values(ma.load_catalog(2027), '54039')
    # A real plan from another county must not enter a comparison here.
    foreign = next(key for key in ids if key not in {p['id'] for p in kanawha})
    assert client.get('/ma-map', params={'county': '54039', 'selected_ids': foreign}).status_code == 422
    no_drugs = next(p for p in kanawha if p['part_d'] == 'No')
    assert client.get('/ma-map', params={'county': '54039', 'coverage': 'with', 'selected_ids': no_drugs['id']}).status_code == 422


def test_missing_data_is_unavailable_not_no_plans(client, monkeypatch):
    def missing(_):
        raise FileNotFoundError()
    monkeypatch.setattr(ma, 'load_catalog', missing)
    page = client.get('/ma-map?county=54039')
    assert page.status_code == 503
    assert 'Plan data unavailable' in page.text
    assert '0 listed plans' not in page.text
    assert len(page.context['counties']) == 55


def test_empty_county_and_filters_do_not_substitute_other_areas(client, monkeypatch):
    original = json.loads(json.dumps(ma.load_catalog(2027)))
    original['county_plans']['54039'] = []
    monkeypatch.setattr(ma, 'load_catalog', lambda _: original)
    page = client.get('/ma-map?county=54039')
    assert page.status_code == 200 and page.context['total'] == 0
    assert page.context['plans'] == []


def test_map_and_comparison_keep_existing_owner_access(monkeypatch):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(auth, 'SessionLocal', factory)
    app = FastAPI()
    app.include_router(ma.router)
    app.add_middleware(auth.OwnerAuthMiddleware)
    with factory() as db:
        db.add(auth.CrmSession(token_hash=auth.digest('b' * 64), owner_email=auth.owner_email(),
                               expires_at=auth.now_utc() + timedelta(hours=1)))
        db.commit()
    with TestClient(app, base_url='https://wsbco-crm.onrender.com', follow_redirects=False) as client:
        assert client.get('/ma-map?county=54039').status_code == 401
        assert client.get('/ma-map', headers={'Accept': 'text/html'}).status_code == 303
        client.cookies.set(auth.SESSION_COOKIE, 'b' * 64)
        assert client.get('/ma-map?county=54039').status_code == 200
    engine.dispose()
