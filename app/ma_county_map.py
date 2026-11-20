"""County-level MA discovery backed by versioned, offline CMS data."""
from functools import lru_cache
import json
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse

router = APIRouter()
templates = Jinja2Templates(directory='app/templates')
DATA_DIR = Path(__file__).resolve().parent / 'data' / 'ma_map'
STATES = {'WV': 'West Virginia', 'OR': 'Oregon', 'CA': 'California', 'TX': 'Texas'}
CATALOG_FILES = {
    'WV': {2026: 'wv_2026.json', 2027: 'wv_2027.json'},
    'OR': {2026: 'or_2026.json', 2027: 'or_2027.json'},
    'CA': {2026: 'ca_2026.json', 2027: 'ca_2027.json'},
    'TX': {2026: 'tx_2026.json', 2027: 'tx_2027.json'},
}
COMPARE_FIELDS = [
    ('Insurance company / brand', 'carrier'), ('Parent organization', 'parent_organization'),
    ('CMS contract-plan-segment ID', 'id'), ('Plan type', 'plan_type'),
    ('Monthly plan premium', 'monthly_premium'), ('Part C premium', 'part_c_premium'),
    ('Part D premium', 'part_d_premium'), ('In-network medical out-of-pocket maximum', 'moop'),
    ('Prescription drug coverage', 'part_d'), ('Annual Part D deductible', 'drug_deductible'),
    ('Drug tier without deductible', 'tier_without_deductible'), ('Overall CMS star rating', 'stars'),
    ('Special Needs Plan', 'snp'), ('SNP eligibility type', 'snp_type'),
    ('C-SNP condition', 'snp_condition'), ('Institutional SNP type', 'snp_institutional'),
    ('D-SNP integration status', 'dual_integration'), ('Sanctioned plan', 'sanctioned'),
    ('Enrollment capacity', 'enrollment_capacity'),
    ('Medical deductible', 'medical_deductible'), ('Primary care / specialist copays', 'medical_copays'),
    ('Dental, vision and hearing benefits', 'supplemental_benefits'),
]


@lru_cache(maxsize=4)
def load_geometry(state='WV'):
    data = json.loads((DATA_DIR / f'{state.lower()}_counties.json').read_text())
    if data['state'] != state:
        raise ValueError('Map state does not match the selected area')
    return data


@lru_cache(maxsize=8)
def load_catalog(year, state='WV'):
    if state not in CATALOG_FILES or year not in CATALOG_FILES[state]:
        raise HTTPException(422, 'Choose an installed plan year: 2026 or 2027.')
    data = json.loads((DATA_DIR / CATALOG_FILES[state][year]).read_text())
    if data['year'] != year or data['state'] != state:
        raise ValueError('Catalog state/year does not match the selected area')
    return data


def plan_values(data, county_id, carrier='', coverage='all', eligibility='all'):
    plans = []
    for key in data['county_plans'][county_id]:
        source = data['plans'][key]
        # CMS marks consolidated C+D premium N/A for MA-only plans. Their
        # actual monthly plan premium is in the separate Part C column.
        plans.append({**source, 'monthly_premium': source['part_c_premium']
                      if source['part_d'] == 'No' else source['premium']})
    return [p for p in plans
            if (not carrier or p['carrier'] == carrier)
            and (coverage == 'all' or p['part_d'] == ('Yes' if coverage == 'with' else 'No'))
            and (eligibility == 'all' or p['snp'] == ('Yes' if eligibility == 'snp' else 'No'))]


@lru_cache(maxsize=4)
def load_county_features(state):
    return json.loads((DATA_DIR / f'{state.lower()}_counties.geojson').read_text())


@router.get('/ma-map/counties.geojson')
def county_features(state: str = Query('WV', max_length=2)):
    state = state.upper()
    if state not in STATES:
        raise HTTPException(422, 'Choose an installed map state.')
    return JSONResponse(load_county_features(state), headers={'Cache-Control': 'private, max-age=3600'})


@router.get('/ma-map')
def map_page(request: Request, year: int = 2027, state: str = Query('WV', max_length=2),
             county: str = Query('', max_length=5),
             carrier: str = Query('', max_length=200), coverage: str = 'all', eligibility: str = 'all',
             selected_ids: list[str] = Query(default=[]), map_view: str = 'esri'):
    state = state.upper()
    if state not in STATES:
        raise HTTPException(422, 'Choose an installed state: ' + ', '.join(STATES.values()) + '.')
    if map_view not in {'outline', 'esri'}:
        raise HTTPException(422, 'Choose the outline or Esri map view.')
    if year not in CATALOG_FILES[state]:
        raise HTTPException(422, 'Choose an installed plan year: 2026 or 2027.')
    if coverage not in {'all', 'with', 'without'} or eligibility not in {'all', 'general', 'snp'}:
        raise HTTPException(422, 'Invalid coverage or eligibility filter.')
    geometry = load_geometry(state)
    counties = {c['id']: c for c in geometry['counties']}
    if county and county not in counties:
        raise HTTPException(422, f'Choose a {STATES[state]} county from the map or county list.')
    if len(selected_ids) > 3 or len(selected_ids) != len(set(selected_ids)):
        raise HTTPException(422, 'Choose up to three different plans for comparison.')
    if selected_ids and not county:
        raise HTTPException(422, 'Choose a county before selecting plans.')
    error, data = '', None
    try:
        data = load_catalog(year, state)
    except (OSError, ValueError, KeyError):
        error = 'Plan data is unavailable for this year. Please try again after the catalog is restored.'
    plans, chosen, carriers, total, insurer_count = [], [], [], 0, 0
    if data:
        county_data = data['county_plans']
        if set(county_data) != set(counties):
            raise HTTPException(503, 'The county catalog is incomplete; please restore the verified data.')
        if county:
            all_plans = plan_values(data, county)
            carriers = sorted({p['carrier'] for p in all_plans})
            if carrier and carrier not in carriers:
                raise HTTPException(422, 'That insurer is not listed in this county and plan year.')
            total, insurer_count = len(all_plans), len(carriers)
            plans = plan_values(data, county, carrier, coverage, eligibility)
            available = {p['id']: p for p in plans}
            if any(key not in available for key in selected_ids):
                raise HTTPException(422, 'A selected plan is not in this county, year or filter. Select plans again.')
            chosen = [available[key] for key in selected_ids]
    links = []
    for c in geometry['counties']:
        count = len(data['county_plans'][c['id']]) if data else None
        params = {'state': state, 'year': year, 'county': c['id'], 'map_view': map_view}
        links.append({**c, 'count': count, 'url': '/ma-map?' + urlencode(params)})
    map_params = [('state', state), ('year', year), ('county', county), ('carrier', carrier),
                  ('coverage', coverage), ('eligibility', eligibility)]
    map_params += [('selected_ids', key) for key in selected_ids]
    map_config = {'state': state, 'year': year, 'selected': county,
                  'features_url': '/ma-map/counties.geojson?' + urlencode({'state': state}),
                  'counties': [{k: c[k] for k in ('id', 'name', 'count', 'url')} for c in links]}
    response = templates.TemplateResponse(request=request, name='ma_county_map.html', context={
        'geometry': geometry, 'counties': links, 'county': counties.get(county),
        'year': year, 'years': sorted(CATALOG_FILES[state], reverse=True), 'catalog': data,
        'state': state, 'state_name': STATES[state], 'states': STATES,
        'map_view': map_view, 'map_config': map_config,
        'outline_url': '/ma-map?' + urlencode(map_params + [('map_view', 'outline')]),
        'esri_url': '/ma-map?' + urlencode(map_params + [('map_view', 'esri')]),
        'plans': plans, 'chosen': chosen, 'selected_ids': selected_ids, 'compare_fields': COMPARE_FIELDS,
        'carriers': carriers, 'carrier': carrier, 'coverage': coverage, 'eligibility': eligibility,
        'total': total, 'insurer_count': insurer_count, 'data_error': error,
    }, status_code=503 if error else 200)
    response.headers['Cache-Control'] = 'no-store'
    return response
