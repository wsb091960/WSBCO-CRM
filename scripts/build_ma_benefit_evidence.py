"""Development-only CMS PBP evidence audit. Does not change CRM plan benefits.

Read the official PBP ZIP, join exact contract/plan/segment/year identities,
and retain source rows and dictionary meanings for review. This deliberately
does not turn conditional cost-sharing fields into client-facing benefits.
"""
import argparse
from collections import defaultdict
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import unicodedata
from zipfile import ZipFile

IDENTITY_FIELDS = ('pbp_a_hnumber', 'pbp_a_plan_identifier', 'segment_id')
SECTIONS = {
    'plan_identity': 'pbp_Section_A.txt',
    'medical_deductible_and_combined_limits': 'pbp_Section_D.txt',
    'professional_services': 'pbp_b7_health_prof.txt',
    'inpatient_hospital': 'pbp_b1a_inpat_hosp.txt',
    'dental': 'pbp_b16_dental.txt',
    'vision': 'pbp_b17_eye_exams_wear.txt',
    'hearing': 'pbp_b18_hearing_exams_aids.txt',
    'out_of_network': 'pbp_Section_C.txt',
    'out_of_network_groups': 'pbp_Section_C_OON.txt',
    'point_of_service': 'pbp_Section_C_POS.txt',
    'supplemental_services': 'pbp_b13_other_services.txt',
    'eligibility_and_uniform_flexibility': 'pbp_b19a_model_test_vbid_uf.txt',
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def plan_id(row):
    contract, plan, segment = (row.get(field, '').strip() for field in IDENTITY_FIELDS)
    if not re.fullmatch(r'[A-Z]\d{4}', contract) or not re.fullmatch(r'\d{1,3}', plan) or not re.fullmatch(r'\d{1,3}', segment):
        raise ValueError('Invalid CMS contract/plan/segment identity')
    return f'{contract}-{int(plan):03d}-{int(segment):03d}'


def read_table(data, filename):
    """Do not silently overwrite repeated columns or discard malformed rows."""
    reader = csv.reader(io.StringIO(data.decode('cp1252')), delimiter='\t', quoting=csv.QUOTE_NONE)
    headers = [name.strip().lower() for name in next(reader)]
    if not set(IDENTITY_FIELDS).issubset(headers):
        raise ValueError(f'Missing plan identity columns in {filename}')
    for line, cells in enumerate(reader, 2):
        if len(cells) != len(headers):
            raise ValueError(f'{filename}:{line}: field count does not match header')
        row = {}
        for key, value in zip(headers, cells):
            if key in row and row[key] != value:
                raise ValueError(f'{filename}:{line}: conflicting duplicate column {key}')
            row[key] = value
        yield line, row


def read_dictionary(data):
    # Development dependency only; no runtime import or installation is needed.
    import openpyxl
    workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    sheet = workbook.active
    rows = sheet.iter_rows(values_only=True)
    header = next(rows)
    required = {'FILE', 'NAME', 'TYPE', 'TITLE', 'SERVICE CATEGORY', 'CODES', 'CODE_VALUES'}
    if not required.issubset(header):
        raise ValueError('CMS dictionary columns changed; review before importing')
    result = defaultdict(dict)
    for line, values in enumerate(rows, 2):
        row = dict(zip(header, values))
        table, name = row['FILE'], row['NAME']
        if not table or not name:
            continue
        field = result[str(table).lower()].setdefault(str(name).lower(), {
            'title': '', 'type': '', 'service_category': '', 'codes': {}, 'dictionary_rows': []})
        for target, source in [('title', 'TITLE'), ('type', 'TYPE'), ('service_category', 'SERVICE CATEGORY')]:
            if row[source] not in (None, ''):
                field[target] = str(row[source])
        if row['CODES'] not in (None, ''):
            code, label = str(row['CODES']), str(row['CODE_VALUES'] or '')
            if code in field['codes'] and field['codes'][code] != label:
                raise ValueError(f'Conflicting dictionary code for {table}/{name}/{code}')
            field['codes'][code] = label
        field['dictionary_rows'].append(line)
    workbook.close()
    return dict(result)


def evidence_fields(row, definitions):
    result = {}
    for name, raw in row.items():
        definition = definitions.get(name)
        result[name] = {'raw': raw, 'meaning': None, 'status': 'missing' if raw == '' else 'raw'}
        if definition:
            codes = definition['codes']
            result[name]['title'] = definition['title']
            result[name]['service_category'] = definition['service_category']
            if raw and codes:
                # Bit-position masks and category lists need contextual decoding.
                # An exact dictionary code is the only meaning assigned here.
                result[name]['meaning'] = codes.get(raw)
                result[name]['status'] = 'coded' if raw in codes else 'unresolved_code'
        elif raw:
            result[name]['status'] = 'undocumented'
    return result


def normalized_name(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def build_evidence(archive, year, catalogs, source_url, last_modified=None):
    if year not in {2026, 2027}:
        raise ValueError('Only the installed 2026/2027 catalog years are supported')
    requested, states = {}, {}
    for catalog in catalogs:
        if catalog['year'] != year:
            raise ValueError('PBP year and county catalog year must match')
        state = catalog['state']
        if state in states:
            raise ValueError('Duplicate state catalog')
        ids = set(catalog['plans'])
        linked = set().union(*map(set, catalog['county_plans'].values()))
        if ids != linked:
            raise ValueError('Catalog plans and county availability do not reconcile')
        states[state] = sorted(ids)
        for key, plan in catalog['plans'].items():
            if plan['id'] != key or plan['year'] != year:
                raise ValueError('Catalog plan identity/year does not match its key')
            if key in requested and normalized_name(requested[key]['plan_name']) != normalized_name(plan['plan_name']):
                raise ValueError('Conflicting plan names across state catalogs')
            requested[key] = plan
    archive = Path(archive)
    artifacts, identities, hashes, definitions = {}, {}, {}, {}
    with ZipFile(archive) as z:
        dictionary_name = f'PBP_Benefits_{year}_dictionary.xlsx'
        readme_name = f'Readme_PBP_Benefits_{year}.txt'
        readme = z.read(readme_name).decode('utf-8-sig')
        if f'The CY {year} PBP Benefits file' not in readme:
            raise ValueError('CMS source readme does not confirm the requested year')
        dictionary_bytes = z.read(dictionary_name)
        dictionary = read_dictionary(dictionary_bytes)
        hashes[dictionary_name] = sha256(dictionary_bytes)
        hashes[readme_name] = sha256(z.read(readme_name))
        for section, filename in SECTIONS.items():
            data = z.read(filename)
            hashes[filename] = sha256(data)
            definitions[filename] = dictionary.get(Path(filename).stem.lower(), {})
            for line, row in read_table(data, filename):
                key = plan_id(row)
                if section == 'plan_identity':
                    if key in identities:
                        raise ValueError(f'Ambiguous duplicate Section A identity: {key}')
                    identities[key] = row
                if key not in requested:
                    continue
                artifacts.setdefault(key, defaultdict(list))[section].append({
                    'source_file': filename, 'source_line': line,
                    'version': row.get('version', ''), 'raw_fields': row})
    plans = {}
    for key, catalog_plan in requested.items():
        identity = identities.get(key)
        issues = []
        if not identity:
            issues.append('No exact contract/plan/segment match in CMS PBP Section A')
        elif normalized_name(identity.get('pbp_a_plan_name', '')) != normalized_name(catalog_plan['plan_name']):
            issues.append('CMS PBP and county catalog plan names differ; review required')
        records = dict(artifacts.get(key, {}))
        for section, rows in records.items():
            if identity and any(row['version'] != identity.get('version', '') for row in rows):
                issues.append(f'{section}: source version differs from Section A')
        missing = [section for section in SECTIONS if section not in records]
        plans[key] = {'id': key, 'year': year, 'plan_name': catalog_plan['plan_name'],
                      'identity_match': identity is not None, 'review_issues': issues,
                      'missing_sections': missing, 'sections': records,
                      'carrier_document_verified': False, 'release_ready': False}
    return {'schema_version': 1, 'purpose': 'development_review_only', 'release_ready': False,
            'year': year, 'generated_at': datetime.now(timezone.utc).isoformat(),
            'source': {'publisher': 'CMS', 'url': source_url,
                       'source_page': 'https://www.cms.gov/data-research/statistics-trends-and-reports/medicare-advantagepart-d-contract-and-enrollment-data/benefits-data/pbp-benefits-' + str(year),
                       'http_last_modified': last_modified, 'zip_sha256': sha256(archive.read_bytes()),
                       'member_sha256': hashes, 'dictionary': dictionary_name},
            'states': states, 'plans': plans, 'field_definitions': definitions}


def coverage_summary(evidence):
    result = {}
    for state, ids in evidence['states'].items():
        rows = [evidence['plans'][key] for key in ids]
        result[state] = {'catalog_plans': len(rows),
                         'exact_identity_matches': sum(p['identity_match'] for p in rows),
                         'plans_with_review_issues': sum(bool(p['review_issues']) for p in rows),
                         'missing_section_records': {
                             section: sum(section in p['missing_sections'] for p in rows)
                             for section in SECTIONS if section != 'plan_identity'}}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-zip', required=True, type=Path)
    parser.add_argument('--year', required=True, type=int)
    parser.add_argument('--catalog', required=True, action='append', type=Path)
    parser.add_argument('--source-url', required=True)
    parser.add_argument('--last-modified')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = build_evidence(args.source_zip, args.year,
                            [json.loads(path.read_text()) for path in args.catalog],
                            args.source_url, args.last_modified)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'benefit_evidence.json').write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':')) + '\n')
    summary = {'year': args.year, 'release_ready': False, 'source': result['source'],
               'coverage': coverage_summary(result),
               'review_issues': {key: p['review_issues'] for key, p in result['plans'].items() if p['review_issues']}}
    (args.output / 'coverage_audit.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary['coverage'], indent=2))


if __name__ == '__main__':
    main()
