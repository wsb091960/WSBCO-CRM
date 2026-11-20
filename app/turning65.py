"""Turning 65 territory targeting: published estimates and private CRM cohorts."""
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
from app.services import turning65 as service

router = APIRouter(prefix='/turning65', tags=['Turning 65 targeting'])
templates = Jinja2Templates(directory='app/templates')


@dataclass(frozen=True)
class Filters:
    state: str
    year: int
    county: str
    carrier: str
    plan_id: str
    stars: str
    layer: str
    age: str
    measure: str
    window: str
    date_from: str
    date_to: str
    map_view: str


def filters(state: str = Query('OR', max_length=2), year: int = 2027,
            county: str = Query('', max_length=5), carrier: str = Query('', max_length=200),
            plan_id: str = Query('', max_length=40), stars: str = 'all',
            layer: str = 'population', age: str = '64', measure: str = 'count',
            window: str = '6', date_from: str = '', date_to: str = '', map_view: str = 'esri'):
    state = state.upper()
    choices = [(state, service.STATES), (year, {2026, 2027}), (stars, {'all', '4', '4.5', '5'}),
               (layer, {'population', 'contacts'}), (age, {'64', '65plus'}),
               (measure, {'count', 'share'}), (window, {'6', '12', 'custom', 'age64'}),
               (map_view, {'esri', 'outline'})]
    if any(value not in allowed for value, allowed in choices):
        raise HTTPException(422, 'Choose a supported state, plan year and targeting filters.')
    return Filters(state, year, county, carrier, plan_id, stars, layer, age, measure,
                   window, date_from, date_to, map_view)


def link(f, path='/turning65', **changes):
    values = asdict(f) | changes
    return path + '?' + urlencode({k: v for k, v in values.items() if v != ''})


def view_model(f, db):
    geometry = load_geometry(f.state)
    known = {c['id']: c for c in geometry['counties']}
    if f.county and f.county not in known:
        raise HTTPException(422, 'Choose a county in the selected state.')
    data = service.population(f.state)
    area = service.service_area(f.state, f.year, f.carrier, f.plan_id, f.stars)
    # A changed insurer/year can remove the previously selected county.
    selected = f.county if f.county in area['ids'] else ''
    notice = 'The previous county is outside the selected plan service area.' if f.county and not selected else ''
    today = service.local_today()
    targeting = service.contact_targeting(db, f.state, geometry['counties'], area['ids'],
                                         f.window, f.date_from, f.date_to, today)
    rows = []
    for source in geometry['counties']:
        county_id = source['id']
        numbers = data['counties'][county_id]
        stats = targeting['counties'][county_id]
        value = (numbers['age64'] if f.age == '64' else numbers['age65plus']) if f.layer == 'population' else stats['matching']
        share = value / numbers['population'] * 100 if numbers['population'] else 0
        rows.append({**source, **numbers, **stats, 'in_scope': county_id in area['ids'],
                     'value': value, 'share': share, 'url': link(f, county=county_id),
                     'contacts_url': link(f, path='/turning65/contacts', county=county_id),
                     'plans_url': '/ma-map?' + urlencode({'state': f.state, 'year': f.year, 'county': county_id,
                                                        'carrier': f.carrier})})
    scoped = [c for c in rows if c['in_scope']]
    ranked = sorted(scoped, key=lambda c: (-(c['share'] if f.measure == 'share' and f.layer == 'population' else c['value']), c['name']))
    selected_county = next((c for c in scoped if c['id'] == selected), None)
    totals = {key: sum(c[key] for c in scoped) for key in ('population', 'age64', 'age65plus', 'matching', 'contacts')}
    selected_matches = [c for c in targeting['matches'] if not selected or c['county_id'] == selected]
    map_config = {'state': f.state, 'selected': selected, 'layer': f.layer,
                  'metric_label': ('Residents age 64' if f.age == '64' else 'Residents age 65+')
                  if f.layer == 'population' else 'Matching CRM contacts',
                  'measure': f.measure if f.layer == 'population' else 'count',
                  'features_url': '/ma-map/counties.geojson?' + urlencode({'state': f.state}),
                  'counties': [{k: c[k] for k in ('id', 'name', 'value', 'share', 'in_scope', 'url')} for c in rows],
                  'points': targeting['points'][:5000] if f.layer == 'contacts' else [],
                  'point_total': len(targeting['points']) if f.layer == 'contacts' else 0}
    threshold = ([500, 2000, 10000, 20000] if f.age == '64' else [2000, 10000, 50000, 100000])
    labels = (['0–499', '500–1,999', '2,000–9,999', '10,000–19,999', '20,000+'] if f.age == '64'
              else ['0–1,999', '2,000–9,999', '10,000–49,999', '50,000–99,999', '100,000+'])
    if f.measure == 'share' and f.layer == 'population':
        threshold = [.8, 1.1, 1.4, 1.7] if f.age == '64' else [10, 15, 20, 25]
        labels = ['<0.8%', '0.8–1.09%', '1.1–1.39%', '1.4–1.69%', '1.7%+'] if f.age == '64' else ['<10%', '10–14.9%', '15–19.9%', '20–24.9%', '25%+']
    if f.layer == 'contacts':
        threshold, labels = [1, 5, 20, 100], ['0', '1–4', '5–19', '20–99', '100+']
    for county in rows:
        number = county['share'] if map_config['measure'] == 'share' else county['value']
        county['bucket'] = sum(number >= t for t in threshold)
    map_config['thresholds'] = threshold
    return {'f': f, 'states': service.STATES, 'state_name': service.STATES[f.state],
            'geometry': geometry, 'population': data, 'area': area, 'counties': rows,
            'scoped': scoped, 'ranked': ranked, 'selected': selected_county,
            'totals': totals, 'targeting': targeting, 'matches': selected_matches,
            'map_config': map_config, 'legend': labels, 'notice': notice,
            'state_links': {s: link(f, state=s, county='', carrier='', plan_id='', stars='all') for s in service.STATES},
            'outline_url': link(f, county=selected, map_view='outline'),
            'esri_url': link(f, county=selected, map_view='esri'),
            'contacts_url': link(f, path='/turning65/contacts', county=selected),
            'csv_url': link(f, path='/turning65/export.csv', county=''),
            'map_url': link(f, county=selected),
            'clear_url': link(f, carrier='', plan_id='', stars='all', county=''),
            'population_url': link(f, layer='population', county=selected),
            'birthdays_url': link(f, layer='contacts', county=selected),
            'custom_start': f.date_from or today.isoformat(),
            'custom_end': f.date_to or service.add_months(today, 6).isoformat()}


@router.get('')
def map_page(request: Request, f: Filters = Depends(filters), db: Session = Depends(get_db)):
    context = view_model(f, db)
    response = templates.TemplateResponse(request=request, name='turning65.html', context=context)
    response.headers['Cache-Control'] = 'no-store'
    return response


@router.get('/contacts')
def contacts_page(request: Request, f: Filters = Depends(filters), page: int = Query(1, ge=1),
                  db: Session = Depends(get_db)):
    context = view_model(f, db)
    count = len(context['matches'])
    pages = max(1, (count + 49) // 50)
    page = min(page, pages)
    context |= {'contact_count': count, 'page': page, 'pages': pages,
                'matches': context['matches'][(page - 1) * 50:page * 50],
                'previous_url': link(f, path='/turning65/contacts', page=page - 1),
                'next_url': link(f, path='/turning65/contacts', page=page + 1)}
    response = templates.TemplateResponse(request=request, name='turning65_contacts.html', context=context)
    response.headers['Cache-Control'] = 'no-store'
    return response


def safe_csv(value):
    value = str(value)
    return "'" + value if value.startswith(('=', '+', '-', '@', '\t', '\r')) else value


@router.get('/export.csv')
def export_territory(f: Filters = Depends(filters), db: Session = Depends(get_db)):
    context = view_model(f, db)
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['State', 'County FIPS', 'County', 'Population reference date', 'Total residents',
                     'Residents exactly age 64', 'Age 64 percent', 'Residents age 65+', 'Age 65+ percent',
                     'Existing Medicare contacts', 'Matching CRM birthdays', 'Birthday window', 'CRM as-of date',
                     'Plan year', 'Insurer filter', 'Plan filter', 'Minimum star filter', 'Census source',
                     'Census SHA256', 'CMS source date'])
    for row in context['ranked']:
        writer.writerow([safe_csv(v) for v in [f.state, row['id'], row['name'], context['population']['reference_date'],
            row['population'], row['age64'], round(row['age64'] / row['population'] * 100, 4) if row['population'] else 0,
            row['age65plus'], round(row['age65plus'] / row['population'] * 100, 4) if row['population'] else 0,
            row['contacts'], row['matching'], context['targeting']['window_label'], context['targeting']['today'],
            f.year, f.carrier, f.plan_id, f.stars, context['population']['source_url'],
            context['population']['source_sha256'], context['area']['catalog']['source_updated']]])
    return Response(output.getvalue(), media_type='text/csv', headers={
        'Content-Disposition': f'attachment; filename="turning65_{f.state}_territory.csv"', 'Cache-Control': 'no-store'})
