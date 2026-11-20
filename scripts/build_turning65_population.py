"""Build auditable county targeting snapshots from Census single-year ages.

Run explicitly, never during web requests. Example:
python scripts/build_turning65_population.py --source-dir /tmp/census-age-source
Existing files in source-dir are reused, supporting an offline rebuild.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import csv
import hashlib
import io
import json
from pathlib import Path
from urllib.request import urlopen

STATES = {'OR': '41', 'CA': '06', 'WV': '54', 'TX': '48'}
ROOT = Path(__file__).resolve().parents[1]


def build(content, state):
    counties = defaultdict(lambda: {'population': 0, 'age64': None, 'age65plus': 0})
    seen = set()
    for row in csv.DictReader(io.StringIO(content.decode('utf-8-sig'))):
        if row['YEAR'] != '7':
            continue
        if row['STATE'] != STATES[state] or row['SUMLEV'] != '050':
            raise ValueError('Wrong state or summary level in Census input')
        county_id = row['STATE'] + row['COUNTY'].zfill(3)
        age = int(row['AGE'])
        key = county_id, age
        if key in seen or not 0 <= age <= 85:
            raise ValueError('Duplicate or unsupported single-year age')
        seen.add(key)
        total = int(row['TOT_POP'])
        if total < 0 or total != int(row['TOT_MALE']) + int(row['TOT_FEMALE']):
            raise ValueError('Census sex totals do not reconcile')
        county = counties[county_id]
        county['name'] = row['CTYNAME'].removesuffix(' County')
        county['population'] += total
        if age == 64:
            county['age64'] = total
        if age >= 65:
            county['age65plus'] += total
    expected = json.loads((ROOT / 'app/data/ma_map' / f'{state.lower()}_counties.json').read_text())
    if set(counties) != {c['id'] for c in expected['counties']}:
        raise ValueError('Census county coverage differs from the map')
    if len(seen) != len(counties) * 86 or any(c['age64'] is None for c in counties.values()):
        raise ValueError('Incomplete single-year age coverage')
    return dict(sorted(counties.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'app/data/turning65')
    args = parser.parse_args()
    args.source_dir.mkdir(parents=True, exist_ok=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for state, fips in STATES.items():
        name = f'cc-est2025-syasex-{fips}.csv'
        source = args.source_dir / name
        url = 'https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/counties/asrh/' + name
        if not source.exists():
            with urlopen(url, timeout=60) as response:
                content = response.read(30 * 1024 * 1024 + 1)
            if len(content) > 30 * 1024 * 1024:
                raise ValueError('Unexpectedly large Census file')
            source.write_bytes(content)
        content = source.read_bytes()
        counties = build(content, state)
        data = {'state': state, 'vintage': 2025, 'reference_date': '2025-07-01',
                'source_label': 'U.S. Census Bureau, CC-EST2025-SYASEX',
                'source_release': 'June 2026', 'source_url': url,
                'source_page': 'https://www.census.gov/data/tables/time-series/demo/popest/2020s-counties-detail.html',
                'source_layout': 'https://www2.census.gov/programs-surveys/popest/technical-documentation/file-layouts/2020-2025/CC-EST2025-SYASEX.pdf',
                'source_sha256': hashlib.sha256(content).hexdigest(),
                'built_at': datetime.now(timezone.utc).isoformat(), 'counties': counties}
        (args.output_dir / f'{state.lower()}_2025.json').write_text(json.dumps(data, indent=2) + '\n')
        print(state, len(counties), 'counties;', sum(c['age64'] for c in counties.values()), 'age 64', flush=True)


if __name__ == '__main__':
    main()
