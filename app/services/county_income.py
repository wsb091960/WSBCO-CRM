"""Verified county household income, separate from population ages and CRM records."""
from functools import lru_cache
import json
from pathlib import Path

from fastapi import HTTPException
from app.ma_county_map import load_geometry

DATA_DIR = Path(__file__).resolve().parents[1] / 'data/income'
THRESHOLDS = [50000, 65000, 80000, 100000]
PALETTE = ['#edf8fb', '#b3cde3', '#8c96c6', '#8856a7', '#810f7c']
LEGEND = ['Under $50,000', '$50,000–64,999', '$65,000–79,999', '$80,000–99,999', '$100,000+']


@lru_cache(maxsize=4)
def income(state):
    try:
        data = json.loads((DATA_DIR / f'{state.lower()}_2024.json').read_text())
        if data['state'] != state or data['income_year'] != 2024 or data['dollars_year'] != 2024:
            raise ValueError('Incorrect income snapshot')
        if set(data['counties']) != {c['id'] for c in load_geometry(state)['counties']}:
            raise ValueError('Incomplete county income coverage')
        if len(data['source_sha256']) != 64:
            raise ValueError('Missing income source provenance')
        for c in data['counties'].values():
            values = [c[k] for k in ('income_low', 'income', 'income_high')]
            if all(v is None for v in values):
                continue
            if any(type(v) is not int or v < 0 for v in values) or values != sorted(values):
                raise ValueError('Invalid household income or confidence bounds')
        return data
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(503, 'County income estimates are unavailable. Restore the verified Census snapshot.') from exc
