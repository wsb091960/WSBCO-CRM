"""Build county median household income snapshots from the Census SAIPE file.

python scripts/build_county_income.py --source /tmp/est24all.txt
Download the pinned source_url below explicitly before running; no runtime lookups.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATES = {'OR': '41', 'CA': '06', 'WV': '54', 'TX': '48'}
SOURCE_URL = 'https://www2.census.gov/programs-surveys/saipe/datasets/2024/2024-state-and-county/est24all.txt'
LAYOUT_URL = 'https://www2.census.gov/programs-surveys/saipe/technical-documentation/file-layouts/state-county/2024-estimate-layout.txt'


def build(content, state):
    counties = {}
    for line in content.decode('utf-8-sig').splitlines():
        if line[:2] != STATES[state] or int(line[3:6]) == 0:
            continue
        county_id = line[:2] + line[3:6].strip().zfill(3)
        if county_id in counties or line[239:241] != state or '07JAN2026' not in line[242:]:
            raise ValueError('Duplicate, wrong-state or unexpected SAIPE source record')
        raw = [line[133:139].strip(), line[140:146].strip(), line[147:153].strip()]
        if all(value == '.' for value in raw):
            values = [None, None, None]
        else:
            values = [int(value) for value in raw]
            if not 0 <= values[1] <= values[0] <= values[2]:
                raise ValueError('Invalid median household income or confidence bounds')
        counties[county_id] = dict(zip(('income', 'income_low', 'income_high'), values))
    geometry = json.loads((ROOT / 'app/data/ma_map' / f'{state.lower()}_counties.json').read_text())
    if set(counties) != {c['id'] for c in geometry['counties']}:
        raise ValueError('Income county coverage differs from the map')
    return dict(sorted(counties.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'app/data/income')
    args = parser.parse_args()
    content = args.source.read_bytes()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for state in STATES:
        data = {'state': state, 'income_year': 2024, 'dollars_year': 2024,
                'source_label': 'U.S. Census Bureau, SAIPE 2024', 'source_release': 'January 2026',
                'source_url': SOURCE_URL, 'source_layout': LAYOUT_URL,
                'source_sha256': hashlib.sha256(content).hexdigest(),
                'built_at': datetime.now(timezone.utc).isoformat(), 'counties': build(content, state)}
        (args.output_dir / f'{state.lower()}_2024.json').write_text(json.dumps(data, indent=2) + '\n')
        print(state, len(data['counties']), 'county income estimates')


if __name__ == '__main__':
    main()
