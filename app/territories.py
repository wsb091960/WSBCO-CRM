"""Underworked territory planning; aggregate exports contain no contact identity."""
import csv
from dataclasses import asdict, dataclass
import io
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.ma_county_map import load_geometry
from app.services import territories as service
from app.services.turning65 import population, STATES
from app.turning65 import safe_csv

router = APIRouter(prefix='/territories', tags=['Underworked territories'])
templates = Jinja2Templates(directory='app/templates')


@dataclass(frozen=True)
class Filters:
    state: str
    county: str
    lens: str
    days: int
    minimum: int
    empty: int
    map_view: str


def filters(state: str = Query('OR', max_length=2), county: str = Query('', max_length=5),
            lens: str = 'presence', days: int = 90, minimum: int = 0, empty: int = 0,
            map_view: str = 'esri'):
    state = state.upper()
    if (state not in STATES or lens not in {'presence', 'outreach'} or days not in {30, 60, 90, 180, 365}
            or minimum not in {0, 100, 500, 1000, 5000} or empty not in {0, 1} or map_view not in {'esri', 'outline'}):
        raise HTTPException(422, 'Choose a supported state and territory filters.')
    return Filters(state, county, lens, days, minimum, empty, map_view)


def link(f, path='/territories', **changes):
    return path + '?' + urlencode({k: v for k, v in (asdict(f) | changes).items() if v != ''})


def view_model(f, db):
    geometry = load_geometry(f.state)
    if f.county and f.county not in {c['id'] for c in geometry['counties']}:
        raise HTTPException(422, 'Choose a county in the selected state.')
    data = population(f.state)
    coverage = service.coverage(db, f.state, geometry['counties'], f.days)
    rows = []
    for c in geometry['counties']:
        numbers, stats = data['counties'][c['id']], coverage['counties'][c['id']]
        denominator = stats['contacts'] if f.lens == 'presence' else stats['worked']
        value = numbers['age64'] / (denominator + 1)
        scoped = numbers['age64'] >= f.minimum and (not f.empty or stats['contacts'] == 0)
        rows.append(c | numbers | stats | {'value': value, 'share': 0, 'in_scope': scoped,
            'bucket': sum(value >= t for t in [100, 500, 2000, 10000]), 'url': link(f, county=c['id']),
            'contacts_url': link(f, path='/territories/contacts', county=c['id']),
            'birthdays_url': '/turning65?' + urlencode({'state': f.state, 'county': c['id'], 'layer': 'contacts'}),
            'plans_url': '/ma-map?' + urlencode({'state': f.state, 'county': c['id'], 'year': 2027})})
    ranked = sorted((r for r in rows if r['in_scope']), key=lambda r: (-r['value'], -r['age64'], r['name']))
    selected = next((r for r in ranked if r['id'] == f.county), None)
    ids = {c['id'] for c in ranked}
    matches = [c for c in coverage['contacts'] if c['county_id'] in ids and (not selected or c['county_id'] == selected['id'])]
    totals = {k: sum(c[k] for c in ranked) for k in ('age64', 'contacts', 'worked', 'gap', 'calls', 'dnc')}
    totals['empty'] = sum(c['contacts'] == 0 for c in ranked)
    metric = 'Low CRM presence index' if f.lens == 'presence' else 'Low recent outreach index'
    map_config = {'state': f.state, 'selected': selected['id'] if selected else '', 'layer': 'population',
        'metric_label': metric, 'measure': 'count', 'features_url': '/ma-map/counties.geojson?state=' + f.state,
        'counties': [{k: c[k] for k in ('id', 'name', 'value', 'share', 'in_scope', 'url')} | {'details': [
            f"{c['age64']:,} residents age 64 · July 2025", f"{c['contacts']} CRM contacts · {c['worked']} recently worked"]} for c in rows],
        'points': [], 'point_total': 0, 'thresholds': [100, 500, 2000, 10000],
        'outside_label': 'Outside selected territory filters'}
    return {'f': f, 'states': STATES, 'state_name': STATES[f.state], 'geometry': geometry, 'population': data,
        'coverage': coverage, 'counties': rows, 'ranked': ranked, 'selected': selected, 'matches': matches,
        'totals': totals, 'metric': metric, 'map_config': map_config,
        'legend': ['<100', '100–<500', '500–<2,000', '2,000–<10,000', '10,000+'],
        'notice': 'The previous county is outside the selected territory filters.' if f.county and not selected else '',
        'state_links': {s: link(f, state=s, county='') for s in STATES},
        'esri_url': link(f, map_view='esri'), 'outline_url': link(f, map_view='outline'),
        'csv_url': link(f, path='/territories/export.csv', county=''), 'map_url': link(f),
        'clear_url': link(f, county='', minimum=0, empty=0),
        'contacts_url': link(f, path='/territories/contacts', county=selected['id'] if selected else '')}


@router.get('')
def territory_map(request: Request, f: Filters = Depends(filters), db: Session = Depends(get_db)):
    response = templates.TemplateResponse(request=request, name='territories.html', context=view_model(f, db))
    response.headers['Cache-Control'] = 'no-store'
    return response


@router.get('/contacts')
def territory_contacts(request: Request, f: Filters = Depends(filters), db: Session = Depends(get_db),
                       gap: int = Query(1, ge=0, le=1), page: int = Query(1, ge=1)):
    context = view_model(f, db)
    # Never silently broaden a county-specific contact list after filter changes.
    matches = [] if context['notice'] else [c for c in context['matches'] if not gap or not c['worked']]
    pages = max(1, (len(matches) + 49) // 50)
    page = min(page, pages)
    context |= {'contact_count': len(matches), 'matches': matches[(page-1)*50:page*50], 'gap': gap,
        'page': page, 'pages': pages, 'all_url': link(f, path='/territories/contacts', gap=0),
        'gap_url': link(f, path='/territories/contacts', gap=1),
        'previous_url': link(f, path='/territories/contacts', gap=gap, page=page-1),
        'next_url': link(f, path='/territories/contacts', gap=gap, page=page+1)}
    response = templates.TemplateResponse(request=request, name='territory_contacts.html', context=context)
    response.headers['Cache-Control'] = 'no-store'
    return response


@router.get('/export.csv')
def export_territories(f: Filters = Depends(filters), db: Session = Depends(get_db)):
    c = view_model(f, db)
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['Rank', 'State', 'County FIPS', 'County', 'Targeting index', 'Ranking lens', 'Formula',
        'Residents exactly age 64', 'Medicare CRM contacts all ages', 'Recently worked contacts',
        'Contacts without recent outreach', 'Saved call logs in window', 'Do Not Call contacts',
        'Latest recorded outreach Pacific', 'Window start Pacific', 'CRM as of Pacific', 'Outreach days',
        'Minimum age64 filter', 'Only empty counties filter', 'Population reference date', 'Census source',
        'Census SHA256', 'Activity history available', 'State contacts with unresolved county'])
    for rank, row in enumerate(c['ranked'], 1):
        writer.writerow([safe_csv(v) for v in [rank, f.state, row['id'], row['name'], round(row['value'], 6),
            f.lens, 'age64 / (CRM contacts + 1)' if f.lens == 'presence' else 'age64 / (recently worked contacts + 1)',
            row['age64'], row['contacts'], row['worked'], row['gap'], row['calls'], row['dnc'], row['last_worked'],
            c['coverage']['start'], c['coverage']['as_of'], f.days, f.minimum, f.empty, c['population']['reference_date'],
            c['population']['source_url'], c['population']['source_sha256'], c['coverage']['activity_available'],
            c['coverage']['unresolved']]])
    return Response(output.getvalue(), media_type='text/csv', headers={
        'Content-Disposition': f'attachment; filename="underworked_{f.state}_territories.csv"', 'Cache-Control': 'no-store'})
