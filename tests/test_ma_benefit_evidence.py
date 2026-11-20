"""Protect development benefit evidence against false matches and lost context."""
import io
from zipfile import ZipFile

import openpyxl
import pytest

from scripts import build_ma_benefit_evidence as benefit


def catalog(segment='000', year=2027, name='Example Plan'):
    key = f'H1234-001-{segment}'
    return {'state': 'OR', 'year': year, 'plans': {
        key: {'id': key, 'year': year, 'plan_name': name}}, 'county_plans': {'41019': [key]}}


def archive(tmp_path, *, segment='0', name='Example Plan', different_version=False,
            repeated_groups=False, wrong_readme=False):
    workbook = openpyxl.Workbook()
    workbook.active.append(['FILE', 'NAME', 'TYPE', 'TITLE', 'SERVICE CATEGORY', 'CODES', 'CODE_VALUES'])
    workbook.active.append(['pbp_b7_health_prof', 'copay_yn', 'CHAR', 'Copayment indicator', '7a', '1', 'Yes'])
    workbook.active.append(['pbp_b7_health_prof', 'copay_yn', '', '', '', '2', 'No'])
    stream = io.BytesIO()
    workbook.save(stream)
    path = tmp_path / 'pbp.zip'
    with ZipFile(path, 'w') as z:
        z.writestr('PBP_Benefits_2027_dictionary.xlsx', stream.getvalue())
        z.writestr('Readme_PBP_Benefits_2027.txt',
                   'The CY 2026 PBP Benefits file' if wrong_readme else 'The CY 2027 PBP Benefits file')
        for section, filename in benefit.SECTIONS.items():
            headers = [*benefit.IDENTITY_FIELDS, 'version', 'pbp_a_plan_name', 'copay_yn', 'amount', 'group']
            values = ['H1234', '001', segment,
                      '2' if different_version and section == 'dental' else '1', name, '1', '0.00', 'A']
            data = '\t'.join(headers) + '\n' + '\t'.join(values) + '\n'
            if repeated_groups and section == 'out_of_network_groups':
                data += '\t'.join(values[:-2] + ['25.00', 'B']) + '\n'
            z.writestr(filename, data)
    return path


def build(path, catalogs=None):
    return benefit.build_evidence(path, 2027, catalogs or [catalog()],
                                  'https://www.cms.gov/files/zip/pbp-benefits-2027.zip')


def test_exact_plan_and_year_match_keeps_provenance_and_is_never_release_ready(tmp_path):
    result = build(archive(tmp_path))
    plan = result['plans']['H1234-001-000']
    assert plan['identity_match'] and plan['review_issues'] == []
    assert not plan['release_ready'] and not result['release_ready']
    assert not plan['carrier_document_verified']
    assert plan['sections']['dental'][0]['source_line'] == 2
    assert len(result['source']['zip_sha256']) == 64
    assert len(result['source']['member_sha256']) == len(benefit.SECTIONS) + 2
    assert benefit.coverage_summary(result)['OR']['exact_identity_matches'] == 1


def test_other_segment_cannot_supply_missing_plan_benefits(tmp_path):
    result = build(archive(tmp_path, segment='1'))
    plan = result['plans']['H1234-001-000']
    assert not plan['identity_match'] and plan['sections'] == {}
    assert plan['review_issues'] and 'dental' in plan['missing_sections']


def test_source_and_catalog_year_must_match(tmp_path):
    with pytest.raises(ValueError, match='year'):
        benefit.build_evidence(tmp_path / 'not-read.zip', 2026, [catalog()], 'unused')
    with pytest.raises(ValueError, match='confirm the requested year'):
        build(archive(tmp_path, wrong_readme=True))


def test_repeated_group_rows_are_preserved_instead_of_overwriting_network_conditions(tmp_path):
    result = build(archive(tmp_path, repeated_groups=True))
    rows = result['plans']['H1234-001-000']['sections']['out_of_network_groups']
    assert [(row['raw_fields']['group'], row['raw_fields']['amount']) for row in rows] == [('A', '0.00'), ('B', '25.00')]
    assert [row['source_line'] for row in rows] == [2, 3]


def test_source_version_and_plan_name_differences_need_review(tmp_path):
    result = build(archive(tmp_path, different_version=True, name='Different Plan'))
    issues = result['plans']['H1234-001-000']['review_issues']
    assert any('plan names differ' in issue for issue in issues)
    assert any('source version differs' in issue for issue in issues)
    assert benefit.coverage_summary(result)['OR']['plans_with_review_issues'] == 1


def test_duplicate_columns_only_collapse_if_their_values_agree():
    header = '\t'.join([*benefit.IDENTITY_FIELDS, 'copay', 'copay'])
    good = (header + '\nH1234\t1\t0\t0.00\t0.00\n').encode()
    assert list(benefit.read_table(good, 'example.txt'))[0][1]['copay'] == '0.00'
    bad = (header + '\nH1234\t1\t0\t0.00\t50.00\n').encode()
    with pytest.raises(ValueError, match='conflicting duplicate'):
        list(benefit.read_table(bad, 'example.txt'))
    with pytest.raises(ValueError, match='field count'):
        list(benefit.read_table((header + '\nH1234\t1\t0\n').encode(), 'example.txt'))


def test_blank_zero_no_and_undecoded_multiselect_are_distinct():
    definitions = {name: {'title': name, 'service_category': '', 'codes': codes}
                   for name, codes in [('amount', {}), ('missing_amount', {}),
                                       ('flag', {'1': 'Yes', '2': 'No'}),
                                       ('mask', {'1 in 1': 'Routine', '1 in 2': 'Other'})]}
    fields = benefit.evidence_fields({'amount': '0.00', 'missing_amount': '',
                                      'flag': '2', 'mask': '11'}, definitions)
    assert fields['amount']['raw'] == '0.00' and fields['amount']['status'] == 'raw'
    assert fields['missing_amount']['raw'] == '' and fields['missing_amount']['status'] == 'missing'
    assert fields['flag']['meaning'] == 'No'
    assert fields['mask']['meaning'] is None and fields['mask']['status'] == 'unresolved_code'


def test_bad_identity_and_unreconciled_county_catalog_are_rejected(tmp_path):
    for values in [('H1234', '1', ''), ('H1234', '1', '-1'), ('fake', '1', '0')]:
        with pytest.raises(ValueError, match='identity'):
            benefit.plan_id(dict(zip(benefit.IDENTITY_FIELDS, values)))
    bad = catalog()
    bad['county_plans']['41019'] = []
    with pytest.raises(ValueError, match='do not reconcile'):
        build(tmp_path / 'not-read.zip', [bad])
