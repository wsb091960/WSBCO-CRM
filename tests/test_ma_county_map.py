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
    page = client.get('/ma-map?map_view=outline')
    assert page.status_code == 200
    assert len(page.context['counties']) == 55
    assert {c['id'] for c in page.context['counties']} == set(ma.load_catalog(2027)['county_plans'])
    assert page.text.count('class="ma-county"') == 55
    assert 'aria-label="Kanawha County, 57 plans"' in page.text
    assert 'value="54039"' in page.text
    assert 'name="year"' in page.text and '2026' in page.text and '2027' in page.text
    assert not page.context['plans']  # Do not substitute a default county.


@pytest.mark.parametrize('state', list(ma.STATES))
def test_esri_is_default_and_outline_remains_usable_through_navigation(client, state):
    page = client.get('/ma-map', params={'state': state})
    assert page.status_code == 200 and page.context['map_view'] == 'esri'
    assert 'id="ma-esri-map"' in page.text and '<span>Preview</span>' not in page.text
    outline = client.get(page.context['outline_url'])
    assert outline.context['map_view'] == 'outline'
    assert 'class="ma-map"' in outline.text
    assert 'name="map_view" value="outline"' in outline.text
    county = client.get(outline.context['counties'][0]['url'])
    assert county.context['map_view'] == 'outline'


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


@pytest.mark.parametrize('state,county_id', [('WV', '54061'), ('OR', '41019'), ('CA', '06037'), ('TX', '48201')])
def test_esri_preview_preserves_county_year_filters_and_plan_comparison(client, state, county_id):
    plans = ma.plan_values(ma.load_catalog(2026, state), county_id, coverage='with')[:2]
    params = [('state', state), ('county', county_id), ('year', '2026'),
              ('map_view', 'esri'), ('coverage', 'with')] + [('selected_ids', p['id']) for p in plans]
    page = client.get('/ma-map', params=params)
    assert page.status_code == 200 and page.context['chosen'] == plans
    assert 'id="ma-esri-map"' in page.text and 'id="ma-map-config"' in page.text
    assert 'class="ma-map"' not in page.text
    assert page.text.count('name="map_view" value="esri"') == 3
    assert all('map_view=esri' in c['url'] for c in page.context['counties'])
    config = page.context['map_config']
    assert config['selected'] == county_id and config['year'] == 2026
    assert all(c['count'] == len(ma.load_catalog(2026, state)['county_plans'][c['id']]) for c in config['counties'])
    outline = client.get(page.context['outline_url'])
    assert outline.status_code == 200 and outline.context['chosen'] == plans
    assert 'class="ma-map"' in outline.text and 'id="ma-esri-map"' not in outline.text
    assert client.get(outline.context['esri_url']).context['chosen'] == plans


@pytest.mark.parametrize('state', list(ma.STATES))
def test_geographic_counties_match_catalog_and_valid_coordinates(client, state):
    response = client.get('/ma-map/counties.geojson', params={'state': state})
    assert response.status_code == 200
    layer = response.json()
    assert layer['type'] == 'FeatureCollection'
    assert len(layer['features']) == len(ma.load_geometry(state)['counties'])
    assert {f['properties']['id'] for f in layer['features']} == set(ma.load_catalog(2027, state)['county_plans'])
    for feature in layer['features']:
        geometry = feature['geometry']
        assert geometry['type'] in {'Polygon', 'MultiPolygon'}
        polygons = [geometry['coordinates']] if geometry['type'] == 'Polygon' else geometry['coordinates']
        for polygon in polygons:
            for ring in polygon:
                assert len(ring) >= 4 and ring[0] == ring[-1]
                assert all(-125 < x < -66 and 24 < y < 50 for x, y in ring)


def test_esri_preview_rejects_invalid_modes_and_boundary_states(client):
    assert client.get('/ma-map?map_view=unknown').status_code == 422
    assert client.get('/ma-map/counties.geojson?state=NY').status_code == 422


def test_missing_data_is_unavailable_not_no_plans(client, monkeypatch):
    def missing(*_):
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
    monkeypatch.setattr(ma, 'load_catalog', lambda *_: original)
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
        assert client.get('/ma-map?state=OR&county=41019').status_code == 401
        assert client.get('/ma-map?state=CA&county=06037').status_code == 401
        assert client.get('/ma-map?state=TX&county=48201').status_code == 401
        assert client.get('/ma-map/counties.geojson?state=OR').status_code == 401
        assert client.get('/ma-map', headers={'Accept': 'text/html'}).status_code == 303
        client.cookies.set(auth.SESSION_COOKIE, 'b' * 64)
        assert client.get('/ma-map?county=54039').status_code == 200
        assert client.get('/ma-map?state=OR&county=41019').status_code == 200
        assert client.get('/ma-map?state=CA&county=06037').status_code == 200
        assert client.get('/ma-map?state=TX&county=48201').status_code == 200
        assert client.get('/ma-map/counties.geojson?state=OR').status_code == 200
    engine.dispose()


def test_oregon_has_all_36_counties_with_state_in_links_and_forms(client):
    page = client.get('/ma-map?state=OR&county=41019')
    assert page.status_code == 200
    assert page.context['state_name'] == 'Oregon'
    assert len(page.context['counties']) == 36
    assert all(c['id'].startswith('41') and 'state=OR' in c['url'] for c in page.context['counties'])
    assert 'Oregon county map' in page.text and 'Browse all 36 counties' in page.text
    assert page.text.count('name="state" value="OR"') == 3
    assert 'Selected 2027 plans listed in Douglas County' not in page.text  # No selection yet.
    assert 'state=WV&amp;year=2027' in page.text
    assert 'action="/ma-map" class="ma-location-form"' in page.text


@pytest.mark.parametrize('year,rows,segments,brands,empty_counties', [
    (2026, 595, 101, 15, 6), (2027, 518, 95, 14, 5),
])
def test_oregon_catalog_integrity(year, rows, segments, brands, empty_counties):
    data = ma.load_catalog(year, 'OR')
    geometry = ma.load_geometry('OR')
    assert data['state'] == 'OR' and data['year'] == year
    assert len(data['county_plans']) == 36
    assert set(data['county_plans']) == {c['id'] for c in geometry['counties']}
    assert all(key.startswith('41') for key in data['county_plans'])
    assert data['county_plan_rows'] == sum(len(ids) for ids in data['county_plans'].values()) == rows
    assert len(data['plans']) == segments
    assert len({p['carrier'] for p in data['plans'].values()}) == brands
    assert len([ids for ids in data['county_plans'].values() if not ids]) == empty_counties
    assert {p['category'] for p in data['plans'].values()} == {'MA', 'MA-PD', 'SNP'}
    assert {p['year'] for p in data['plans'].values()} == {year}
    assert set(data['plans']) == {key for ids in data['county_plans'].values() for key in ids}
    assert all(len(ids) == len(set(ids)) for ids in data['county_plans'].values())
    assert 'All OR MA' in data['scope'] and len(data['source_sha256']) == 64


def test_oregon_coos_and_douglas_keep_year_specific_plans(client):
    assert client.get('/ma-map?state=OR&county=41011').context['total'] == 1
    douglas_2027 = client.get('/ma-map?state=OR&county=41019')
    douglas_2026 = client.get('/ma-map?state=OR&county=41019&year=2026')
    assert douglas_2027.context['total'] == 6
    assert douglas_2026.context['total'] == 14
    assert {p['carrier'] for p in douglas_2027.context['plans']} == {'ATRIO Health Plans', 'AllCare Advantage', 'Wellcare'}
    plans = douglas_2027.context['plans']
    chosen = [next(p for p in plans if p['carrier'] == brand) for brand in ['ATRIO Health Plans', 'AllCare Advantage', 'Wellcare']]
    params = [('state', 'OR'), ('county', '41019')] + [('selected_ids', p['id']) for p in chosen]
    comparison = client.get('/ma-map', params=params)
    assert comparison.status_code == 200 and comparison.context['chosen'] == chosen
    assert 'Selected 2027 plans listed in Douglas County, Oregon' in comparison.text


def test_oregon_empty_counties_are_clickable_and_do_not_show_other_counties(client):
    page = client.get('/ma-map?state=OR&county=41023&map_view=outline')  # Grant
    assert page.status_code == 200 and page.context['total'] == 0
    assert page.context['plans'] == [] and page.context['chosen'] == []
    assert 'No Medicare Advantage plans listed' in page.text
    assert 'lists no MA plans in Grant County, Oregon' in page.text
    assert 'aria-label="Grant County, 0 plans"' in page.text
    assert 'class="ma-county has-no-plans is-selected"' in page.text
    assert 'Gray counties: no MA plans listed for 2027' in page.text
    # Wheeler's coverage differs by year; zero plans is not a permanent county flag.
    assert client.get('/ma-map?state=OR&county=41069&year=2026').context['total'] == 0
    assert client.get('/ma-map?state=OR&county=41069&year=2027').context['total'] > 0


def test_state_switch_links_reset_county_and_comparison_and_bad_states_rejected(client):
    for url in ['/ma-map?state=ZZ', '/ma-map?state=OR&county=54039', '/ma-map?state=WV&county=41019']:
        assert client.get(url).status_code == 422
    page = client.get('/ma-map?state=or')
    assert page.status_code == 200 and page.context['state'] == 'OR'
    assert page.context['county'] is None and not page.context['chosen']
    # State navigation retains plan year and map view, never a stale county or selection.
    assert '<a href="/ma-map?state=WV&amp;year=2027&amp;map_view=esri"' in page.text
    wv_id = ma.plan_values(ma.load_catalog(2027), '54039')[0]['id']
    assert client.get('/ma-map', params={'state': 'OR', 'county': '41019', 'selected_ids': wv_id}).status_code == 422


def test_oregon_filters_preserve_source_values_and_distinguish_empty_filter_result(client):
    page = client.get('/ma-map?state=OR&county=41051')  # Multnomah
    plans = page.context['plans']
    assert {p['part_d'] for p in plans} == {'Yes', 'No'}
    assert {p['snp'] for p in plans} == {'Yes', 'No'}
    filtered = client.get('/ma-map?state=OR&county=41051&coverage=without&eligibility=general')
    assert filtered.context['plans']
    assert all(p['part_d'] == 'No' and p['snp'] == 'No' and p['monthly_premium'] == p['part_c_premium'] for p in filtered.context['plans'])
    no_match = client.get('/ma-map?state=OR&county=41051&coverage=without&eligibility=snp')
    assert no_match.context['total'] > 0 and no_match.context['plans'] == []
    assert 'No plans match these filters' in no_match.text
    assert 'No Medicare Advantage plans listed</h3>' not in no_match.text
    assert 'state=OR&amp;year=2027&amp;county=41051' in no_match.text


def test_california_map_preserves_all_58_leading_zero_county_ids(client):
    page = client.get('/ma-map?state=CA&county=06037')
    assert page.status_code == 200 and page.context['state_name'] == 'California'
    assert len(page.context['counties']) == 58
    assert all(c['id'].startswith('06') and len(c['id']) == 5 and 'state=CA' in c['url'] for c in page.context['counties'])
    assert page.context['county']['id'] == '06037'
    assert page.context['county']['name'] == 'Los Angeles'
    assert 'California county map' in page.text and 'Browse all 58 counties' in page.text
    assert page.text.count('name="state" value="CA"') == 3
    assert 'value="06037" selected' in page.text
    assert set(page.context['states']) == {'WV', 'OR', 'CA', 'TX'}


@pytest.mark.parametrize('year,rows,segments,brands,empty_counties', [
    (2026, 1334, 402, 41, 2), (2027, 1278, 394, 38, 3),
])
def test_california_catalog_integrity(year, rows, segments, brands, empty_counties):
    data = ma.load_catalog(year, 'CA')
    geometry = ma.load_geometry('CA')
    assert data['state'] == 'CA' and data['year'] == year
    assert len(data['county_plans']) == 58
    assert set(data['county_plans']) == {c['id'] for c in geometry['counties']}
    assert all(key.startswith('06') and len(key) == 5 for key in data['county_plans'])
    assert data['county_plan_rows'] == sum(len(ids) for ids in data['county_plans'].values()) == rows
    assert len(data['plans']) == segments
    assert len({p['carrier'] for p in data['plans'].values()}) == brands
    assert sum(not ids for ids in data['county_plans'].values()) == empty_counties
    assert {p['category'] for p in data['plans'].values()} == {'MA', 'MA-PD', 'SNP'}
    assert {p['year'] for p in data['plans'].values()} == {year}
    assert set(data['plans']) == {key for ids in data['county_plans'].values() for key in ids}
    assert all(len(ids) == len(set(ids)) for ids in data['county_plans'].values())
    assert 'All CA MA' in data['scope'] and len(data['source_sha256']) == 64


def test_california_large_county_comparison_and_year_specific_values(client):
    page = client.get('/ma-map?state=CA&county=06037')
    assert page.context['total'] == 124 and page.context['insurer_count'] == 21
    assert client.get('/ma-map?state=CA&county=06037&year=2026').context['total'] == 121
    plans = page.context['plans']
    brands = sorted({p['carrier'] for p in plans})[:3]
    chosen = [next(p for p in plans if p['carrier'] == brand) for brand in brands]
    params = [('state', 'CA'), ('county', '06037')] + [('selected_ids', p['id']) for p in chosen]
    result = client.get('/ma-map', params=params)
    assert result.status_code == 200 and result.context['chosen'] == chosen
    assert 'Selected 2027 plans listed in Los Angeles County, California' in result.text
    assert 'Not supplied in CMS Landscape' in result.text
    assert all(p['monthly_premium'] in result.text for p in chosen)


def test_california_zero_plan_counties_are_year_specific_and_clickable(client):
    page = client.get('/ma-map?state=CA&county=06033&map_view=outline')  # Lake
    assert page.status_code == 200 and page.context['total'] == 0
    assert page.context['plans'] == []
    assert 'lists no MA plans in Lake County, California' in page.text
    assert 'aria-label="Lake County, 0 plans"' in page.text
    assert 'class="ma-county has-no-plans is-selected"' in page.text
    assert client.get('/ma-map?state=CA&county=06033&year=2026').context['total'] == 1


def test_california_filters_and_state_boundaries_remain_isolated(client):
    for url in ['/ma-map?state=CA&county=41019', '/ma-map?state=CA&county=54039', '/ma-map?state=OR&county=06037', '/ma-map?state=CA&county=6037']:
        assert client.get(url).status_code == 422
    wv_id = ma.plan_values(ma.load_catalog(2027), '54039')[0]['id']
    assert client.get('/ma-map', params={'state': 'CA', 'county': '06037', 'selected_ids': wv_id}).status_code == 422
    filtered = client.get('/ma-map?state=CA&county=06037&coverage=without&eligibility=general')
    assert filtered.context['plans']
    assert all(p['part_d'] == 'No' and p['snp'] == 'No' and p['monthly_premium'] == p['part_c_premium'] for p in filtered.context['plans'])
    brand = filtered.context['plans'][0]['carrier']
    brand_page = client.get('/ma-map', params={'state': 'CA', 'county': '06037', 'carrier': brand})
    assert all(p['carrier'] == brand for p in brand_page.context['plans'])
    blank = client.get('/ma-map?state=ca')
    assert blank.status_code == 200 and blank.context['state'] == 'CA'
    assert blank.context['county'] is None and not blank.context['chosen']
    assert '<a href="/ma-map?state=CA&amp;year=2027&amp;map_view=esri" aria-current="page"' in blank.text


def test_california_missing_catalog_retains_map_without_fallback(client, monkeypatch):
    original = ma.load_catalog
    def missing(year, state='WV'):
        if state == 'CA':
            raise FileNotFoundError()
        return original(year, state)
    monkeypatch.setattr(ma, 'load_catalog', missing)
    page = client.get('/ma-map?state=CA&county=06037')
    assert page.status_code == 503 and len(page.context['counties']) == 58
    assert 'Plan data unavailable' in page.text
    assert not page.context['plans']
    assert client.get('/ma-map?state=OR&county=41019').status_code == 200


def test_texas_has_all_254_county_links_and_four_state_navigation(client):
    page = client.get('/ma-map?state=TX&county=48201')
    assert page.status_code == 200 and page.context['state_name'] == 'Texas'
    assert len(page.context['counties']) == 254
    assert all(c['id'].startswith('48') and len(c['id']) == 5 and 'state=TX' in c['url'] for c in page.context['counties'])
    assert page.context['county']['name'] == 'Harris'
    assert page.context['county']['id'] == '48201'
    assert 'Texas county map' in page.text and 'Browse all 254 counties' in page.text
    assert page.text.count('name="state" value="TX"') == 3
    assert set(page.context['states']) == {'WV', 'OR', 'CA', 'TX'}


@pytest.mark.parametrize('year,rows,segments,brands', [
    (2026, 10378, 423, 28), (2027, 9363, 421, 22),
])
def test_texas_catalog_integrity_and_complete_county_coverage(year, rows, segments, brands):
    data = ma.load_catalog(year, 'TX')
    geometry = ma.load_geometry('TX')
    assert data['state'] == 'TX' and data['year'] == year
    assert len(data['county_plans']) == 254
    assert set(data['county_plans']) == {c['id'] for c in geometry['counties']}
    assert all(key.startswith('48') and len(key) == 5 for key in data['county_plans'])
    assert data['county_plan_rows'] == sum(len(ids) for ids in data['county_plans'].values()) == rows
    assert len(data['plans']) == segments
    assert len({p['carrier'] for p in data['plans'].values()}) == brands
    assert all(data['county_plans'].values())  # Both source years have records for every TX county.
    assert {p['category'] for p in data['plans'].values()} == {'MA', 'MA-PD', 'SNP'}
    assert {p['year'] for p in data['plans'].values()} == {year}
    assert set(data['plans']) == {key for ids in data['county_plans'].values() for key in ids}
    assert all(len(ids) == len(set(ids)) for ids in data['county_plans'].values())
    assert 'All TX MA' in data['scope'] and len(data['source_sha256']) == 64


def test_texas_harris_county_comparison_and_year_specific_plan_values(client):
    page = client.get('/ma-map?state=TX&county=48201')
    assert page.context['total'] == 99 and page.context['insurer_count'] == 16
    assert client.get('/ma-map?state=TX&county=48201&year=2026').context['total'] == 114
    general = client.get('/ma-map?state=TX&county=48201&eligibility=general').context['plans']
    brands = sorted({p['carrier'] for p in general})[:3]
    chosen = [next(p for p in general if p['carrier'] == brand) for brand in brands]
    params = [('state', 'TX'), ('county', '48201'), ('eligibility', 'general')] + [('selected_ids', p['id']) for p in chosen]
    result = client.get('/ma-map', params=params)
    assert result.status_code == 200 and result.context['chosen'] == chosen
    assert 'Selected 2027 plans listed in Harris County, Texas' in result.text
    assert all(p['monthly_premium'] in result.text and p['moop'] in result.text for p in chosen)
    assert 'Not supplied in CMS Landscape' in result.text


def test_texas_rural_counties_keep_their_own_year_specific_listings(client):
    gaines = client.get('/ma-map?state=TX&county=48165')
    assert gaines.context['county']['name'] == 'Gaines'
    assert gaines.context['total'] == 9
    assert client.get('/ma-map?state=TX&county=48165&year=2026').context['total'] == 7
    loving = client.get('/ma-map?state=TX&county=48301')
    assert loving.context['county']['name'] == 'Loving'
    assert loving.context['total'] == 12
    assert client.get('/ma-map?state=TX&county=48301&year=2026').context['total'] == 19


def test_texas_filters_preserve_coverage_eligibility_and_premium_semantics(client):
    base = '/ma-map?state=TX&county=48201'
    all_plans = client.get(base).context['plans']
    with_drugs = client.get(base + '&coverage=with').context['plans']
    no_drugs = client.get(base + '&coverage=without').context['plans']
    snp = client.get(base + '&eligibility=snp').context['plans']
    general = client.get(base + '&eligibility=general').context['plans']
    assert with_drugs and no_drugs and snp and general
    assert len(with_drugs) + len(no_drugs) == len(all_plans)
    assert len(snp) + len(general) == len(all_plans)
    assert all(p['part_d'] == 'No' and p['monthly_premium'] == p['part_c_premium'] for p in no_drugs)
    assert all(p['snp'] == 'Yes' for p in snp)
    brand = all_plans[0]['carrier']
    filtered = client.get('/ma-map', params={'state': 'TX', 'county': '48201', 'carrier': brand})
    assert filtered.context['plans'] and all(p['carrier'] == brand for p in filtered.context['plans'])


def test_texas_rejects_foreign_state_counties_and_foreign_county_plans(client):
    for url in ['/ma-map?state=TX&county=06037', '/ma-map?state=TX&county=41019', '/ma-map?state=TX&county=54039', '/ma-map?state=CA&county=48201']:
        assert client.get(url).status_code == 422
    data = ma.load_catalog(2027, 'TX')
    foreign = next(key for key in data['plans'] if key not in data['county_plans']['48201'])
    assert client.get('/ma-map', params={'state': 'TX', 'county': '48201', 'selected_ids': foreign}).status_code == 422
    blank = client.get('/ma-map?state=tx')
    assert blank.status_code == 200 and blank.context['county'] is None
    assert blank.context['state'] == 'TX' and not blank.context['chosen']
    assert '<a href="/ma-map?state=TX&amp;year=2027&amp;map_view=esri" aria-current="page"' in blank.text


def test_texas_missing_catalog_does_not_fall_back_to_another_state(client, monkeypatch):
    original = ma.load_catalog
    def missing(year, state='WV'):
        if state == 'TX':
            raise FileNotFoundError()
        return original(year, state)
    monkeypatch.setattr(ma, 'load_catalog', missing)
    page = client.get('/ma-map?state=TX&county=48201')
    assert page.status_code == 503 and len(page.context['counties']) == 254
    assert 'Plan data unavailable' in page.text and not page.context['plans']
    assert client.get('/ma-map?state=CA&county=06037').status_code == 200
