"""Build offline WV or Oregon map/catalogs from Census and CMS ZIP files.

Run with the development-only pyshp package; the CRM needs no new dependency.
Example: python scripts/build_wv_ma_catalog.py --state OR --boundaries counties.zip \
    --landscape 2027=landscape2027.zip --landscape 2026=landscape2026.zip
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import re
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
STATES = {
    'WV': {'name': 'West Virginia', 'fips': '54', 'counties': 55, 'latitude': 39},
    'OR': {'name': 'Oregon', 'fips': '41', 'counties': 36, 'latitude': 44},
}
FIELDS = {
    'carrier': 'Organization Marketing Name',
    'parent_organization': 'Parent Organization Name',
    'contract_name': 'Contract Name',
    'plan_name': 'Plan Name',
    'plan_type': 'Plan Type',
    'category': 'Contract Category Type',
    'part_d': 'Part D Coverage Indicator',
    'snp': 'Special Needs Plan (SNP) Indicator',
    'snp_type': 'SNP Type',
    'snp_condition': 'Chronic or Disabling Condition SNP (C-SNP) Condition Type',
    'snp_institutional': 'SNP Institutional Type',
    'dual_integration': 'Dual Eligible SNP (D-SNP) Integration Status',
    'sanctioned': 'Sanctioned Plan',
    'premium': 'Monthly Consolidated Premium (Part C + D)',
    'part_c_premium': 'Part C Premium',
    'part_d_premium': 'Part D Total Premium',
    'drug_deductible': 'Annual Part D Deductible Amount',
    'moop': 'In-Network Maximum Out-of-Pocket (MOOP) Amount',
    'stars': 'Overall Star Rating',
    'tier_without_deductible': 'Offers Drug Tier with No Part D Deductible',
    'enrollment_capacity': 'Enrollment Capacity Limit Amount',
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def boundaries(path, state='WV'):
    import shapefile
    area = STATES[state]
    with ZipFile(path) as z:
        def part(ext):
            return io.BytesIO(z.read(next(n for n in z.namelist() if n.endswith(ext))))
        reader = shapefile.Reader(shp=part('.shp'), shx=part('.shx'), dbf=part('.dbf'))
        records = [r for r in reader.iterShapeRecords() if r.record.as_dict()['STATEFP'] == area['fips']]
    if len(records) != area['counties']:
        raise ValueError(f'Expected {area["counties"]} {area["name"]} counties')
    # Equirectangular projection at the state's latitude, with equal x/y scale.
    def project(point):
        return point[0] * math.cos(math.radians(area['latitude'])), -point[1]
    points = [project(p) for r in records for p in r.shape.points]
    xmin, xmax = min(p[0] for p in points), max(p[0] for p in points)
    ymin, ymax = min(p[1] for p in points), max(p[1] for p in points)
    scale = min(730 / (xmax - xmin), 610 / (ymax - ymin))
    def xy(p):
        x, y = project(p)
        return f'{20 + (x - xmin) * scale:.2f},{20 + (y - ymin) * scale:.2f}'
    counties = []
    for r in records:
        props = r.record.as_dict()
        starts = list(r.shape.parts) + [len(r.shape.points)]
        rings = [r.shape.points[starts[i]:starts[i + 1]] for i in range(len(starts) - 1)]
        counties.append({'id': props['GEOID'], 'name': props['NAME'],
                         'path': ' '.join('M' + ' L'.join(xy(p) for p in ring) + ' Z' for ring in rings)})
    return {'state': state, 'view_box': f'0 0 {(xmax-xmin)*scale+40:.2f} {(ymax-ymin)*scale+40:.2f}',
            'source_url': 'https://www2.census.gov/geo/tiger/GENZ2025/shp/cb_2025_us_county_5m.zip',
            'source_label': 'U.S. Census Bureau, 2025 county boundaries (1:5,000,000)',
            'source_sha256': digest(path), 'counties': sorted(counties, key=lambda c: c['name'])}


def catalog(path, year, counties, state='WV'):
    by_name = {c['name'].casefold(): c['id'] for c in counties}
    county_plans = {c['id']: [] for c in counties}
    plans, accepted, excluded = {}, 0, {}
    with ZipFile(path) as z:
        csv_name = next(n for n in z.namelist() if n.lower().endswith('.csv'))
        readme_name = next(n for n in z.namelist() if 'readme' in n.lower())
        readme = z.read(readme_name).decode('utf-8-sig')
        updated = re.search(r'Data Last Updated:\s*(\d{2}/\d{2}/\d{4})', readme)
        if not updated:
            raise ValueError('CMS source update date is missing')
        rows = csv.DictReader(io.TextIOWrapper(z.open(csv_name), encoding='utf-8-sig'))
        optional = {'Enrollment Capacity Limit Amount'} if year == 2026 else set()
        required = (set(FIELDS.values()) - optional) | {'Contract Year', 'State Territory Abbreviation', 'County Name',
                                          'Contract ID', 'Plan ID', 'Segment ID'}
        if not required.issubset(set(rows.fieldnames or [])):
            raise ValueError('CMS source columns changed; review before updating the catalog')
        for row in rows:
            if row['State Territory Abbreviation'].strip() != state:
                continue
            category = row['Contract Category Type'].strip()
            if category not in {'MA', 'MA-PD', 'SNP'}:
                excluded[category] = excluded.get(category, 0) + 1
                continue
            if row['Contract Year'].strip() != str(year):
                raise ValueError('Source year does not match the requested year')
            name = row['County Name'].strip().casefold()
            # Do not treat an unknown county as statewide coverage.
            targets = list(county_plans) if name == 'all counties' else [by_name[name]]
            plan_id = '-'.join([row['Contract ID'].strip(), row['Plan ID'].strip().zfill(3),
                                row['Segment ID'].strip().zfill(3)])
            plan = {key: row.get(column, '').strip() for key, column in FIELDS.items()}
            plan.update(id=plan_id, year=year)
            if plan_id in plans and plans[plan_id] != plan:
                raise ValueError(f'Conflicting county benefit values for {plan_id}; preserve county variants')
            plans[plan_id] = plan
            for county_id in targets:
                if plan_id in county_plans[county_id]:
                    raise ValueError(f'Duplicate county-plan row for {county_id}/{plan_id}')
                county_plans[county_id].append(plan_id)
                accepted += 1
    if not plans:
        raise ValueError(f'No {state} Medicare Advantage plans found')
    for ids in county_plans.values():
        ids.sort(key=lambda key: (plans[key]['carrier'], plans[key]['plan_name'], key))
    stamp = re.search(r'Landscape_(\d{6})', csv_name).group(1)
    return {'state': state, 'year': year, 'source_label': f'CMS CY{year} Landscape ({stamp})',
            'source_url': f'https://www.cms.gov/files/zip/cy{year}-landscape-{stamp}.zip',
            'source_page': 'https://www.cms.gov/medicare/coverage/prescription-drug-coverage',
            'source_updated': datetime.strptime(updated.group(1), '%m/%d/%Y').date().isoformat(),
            'imported_at': datetime.now(timezone.utc).isoformat(), 'source_sha256': digest(path),
            'source_csv': csv_name, 'county_plan_rows': accepted, 'excluded_categories': excluded,
            'scope': f'All {state} MA, MA-PD and SNP rows published in the CMS Landscape. CMS excludes employer-sponsored plans, Part B-only plans and National PACE plans.',
            'plans': plans, 'county_plans': county_plans}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', choices=sorted(STATES), default='WV')
    parser.add_argument('--boundaries', type=Path, required=True)
    parser.add_argument('--landscape', action='append', required=True, metavar='YEAR=ZIP')
    parser.add_argument('--output', type=Path, default=ROOT / 'app/data/ma_map')
    args = parser.parse_args()
    geometry = boundaries(args.boundaries, args.state)
    # Validate all inputs before replacing any generated output.
    prefix = args.state.lower()
    outputs = {f'{prefix}_counties.json': geometry}
    for entry in args.landscape:
        year, path = entry.split('=', 1)
        outputs[f'{prefix}_{int(year)}.json'] = catalog(path, int(year), geometry['counties'], args.state)
    args.output.mkdir(parents=True, exist_ok=True)
    for filename, value in outputs.items():
        target = args.output / filename
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n')
        temporary.replace(target)
        print(f'{filename}: {target.stat().st_size:,} bytes; {value.get("county_plan_rows", len(geometry["counties"]))} county records')


if __name__ == '__main__':
    main()
