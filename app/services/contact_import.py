"""Bounded source readers, explicit validation, and conservative contact matching."""
import csv
import hashlib
import io
import json
import os
import re
import zipfile
from datetime import date, datetime
from urllib.parse import quote, urlparse

from sqlalchemy import select

from app.models import Lead

MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 10000
MAX_COLUMNS = 100
SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']
DATES = {'date_of_birth', 'medicare_effective_date', 'next_follow_up'}
BOOLS = {'interested_supplement', 'interested_advantage', 'interested_pdp', 'interested_dental'}
EXCLUDED = {'id', 'created', 'updated'}
FIELDS = {c.name: c for c in Lead.__table__.columns if c.name not in EXCLUDED}
LABELS = {k: k.replace('_', ' ').title() for k in FIELDS}
LABELS.update(date_of_birth='Date of birth', medicare_mbi='Medicare MBI', zip_code='ZIP code', interested_pdp='Interested in Part D', next_follow_up='Next follow-up')
STATUSES = ['New', 'In Progress', 'Attempt Again', 'Callback', 'Appointment Set', 'Interested', 'Sold', 'Not Interested', 'Do Not Call', 'Wrong Number']
ALIASES = {
    'firstname': 'first_name', 'first': 'first_name', 'lastname': 'last_name', 'last': 'last_name',
    'dob': 'date_of_birth', 'birthdate': 'date_of_birth', 'medicareeffective': 'medicare_effective_date',
    'medicaredate': 'medicare_effective_date', 'mbi': 'medicare_mbi', 'medicaid': 'medicaid_number',
    'medicaidno': 'medicaid_number', 'phone1': 'phone', 'homephone': 'phone', 'telephone': 'phone',
    'cell': 'mobile', 'cellphone': 'mobile', 'mobilephone': 'mobile', 'emailaddress': 'email',
    'street': 'address', 'streetaddress': 'address', 'zip': 'zip_code', 'postalcode': 'zip_code',
    'supp': 'interested_supplement', 'supplement': 'interested_supplement', 'medigap': 'interested_supplement',
    'adv': 'interested_advantage', 'advantage': 'interested_advantage', 'ma': 'interested_advantage',
    'pdp': 'interested_pdp', 'partd': 'interested_pdp', 'dental': 'interested_dental',
    'source': 'lead_source', 'nextfollowup': 'next_follow_up', 'lastcontact': 'last_contact',
    'followuptype': 'follow_up_type', 'agentname': 'agent',
}


class ImportProblem(ValueError):
    pass


def norm(value):
    return re.sub(r'[^a-z0-9]', '', str(value or '').lower())


ALIASES.update({norm(k): k for k in FIELDS})


def cell_text(value):
    if value is None:
        return ''
    if isinstance(value, datetime):
        return value.isoformat(sep=' ')
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return 'yes' if value else 'no'
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def table_from_rows(rows):
    """First row is always the header; never silently discard extra columns."""
    rows = iter(rows)
    try:
        headers = [cell_text(c) for c in next(rows)]
    except StopIteration:
        raise ImportProblem('The source is empty.')
    while headers and not headers[-1]:
        headers.pop()
    if not headers or len(headers) > MAX_COLUMNS:
        raise ImportProblem(f'Use 1–{MAX_COLUMNS} columns with headings on the first row.')
    if any(not h for h in headers) or len({h.casefold() for h in headers}) != len(headers):
        raise ImportProblem('Every column needs a unique, nonblank heading on the first row.')
    records = []
    for row_number, values in enumerate(rows, start=2):
        if row_number > MAX_ROWS + 1:
            raise ImportProblem(f'Import at most {MAX_ROWS:,} source rows at a time.')
        values = [cell_text(v) for v in values]
        if not any(values):
            continue
        if any(values[len(headers):]):
            raise ImportProblem(f'Row {row_number} has values beyond the last column heading.')
        values = (values + [''] * len(headers))[:len(headers)]
        if any(len(v) > 32767 for v in values):
            raise ImportProblem(f'Row {row_number} contains a cell longer than 32,767 characters.')
        records.append({'row': row_number, 'values': values})
    if not records:
        raise ImportProblem('There are headings but no data rows to import.')
    return {'headers': headers, 'rows': records}


def read_file(filename, content, worksheet=''):
    if not content or len(content) > MAX_BYTES:
        raise ImportProblem('Choose a nonempty file no larger than 10 MB.')
    extension = filename.lower().rsplit('.', 1)[-1]
    if extension == 'csv':
        text = None
        for encoding in ('utf-8-sig', 'cp1252'):
            try:
                text = content.decode(encoding)
                break
            except UnicodeDecodeError:
                pass
        if text is None or '\x00' in text:
            raise ImportProblem('Save the file as UTF-8 CSV and try again.')
        try:
            dialect = csv.Sniffer().sniff(text[:8192], delimiters=',;\t|')
        except csv.Error:
            dialect = csv.excel
        try:
            return table_from_rows(csv.reader(io.StringIO(text, newline=''), dialect, strict=True))
        except csv.Error:
            raise ImportProblem('The CSV has malformed quoting or delimiters. Save it again as CSV.')
    if extension == 'xlsx':
        from openpyxl import load_workbook
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if sum(i.file_size for i in archive.infolist()) > 100 * 1024 * 1024:
                    raise ImportProblem('The expanded workbook is too large. Export just the contact tab.')
            workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True, keep_links=False)
            try:
                if worksheet and worksheet not in workbook.sheetnames:
                    raise ImportProblem('That worksheet was not found. Enter its exact tab name.')
                sheet = workbook[worksheet] if worksheet else workbook.worksheets[0]
                # Do not trust XLSX dimension metadata; stop at our own row/column limits.
                sheet.reset_dimensions()
                table = table_from_rows(sheet.iter_rows(values_only=True))
                table['worksheet'] = sheet.title
                return table
            finally:
                workbook.close()
        except ImportProblem:
            raise
        except Exception:
            raise ImportProblem('Cannot read that Excel file. Use a valid, unencrypted .xlsx file.')
    if extension == 'xls':
        import xlrd
        try:
            workbook = xlrd.open_workbook(file_contents=content, on_demand=True)
            try:
                sheet = workbook.sheet_by_name(worksheet) if worksheet else workbook.sheet_by_index(0)
                if sheet.nrows > MAX_ROWS + 1 or sheet.ncols > MAX_COLUMNS:
                    raise ImportProblem('This worksheet exceeds 10,000 rows or 100 columns.')
                rows = []
                for i in range(sheet.nrows):
                    values = []
                    for cell in sheet.row(i):
                        value = cell.value
                        if cell.ctype == xlrd.XL_CELL_DATE:
                            value = xlrd.xldate_as_datetime(value, workbook.datemode)
                        elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                            value = bool(value)
                        values.append(value)
                    rows.append(values)
                table = table_from_rows(rows)
                table['worksheet'] = sheet.name
                return table
            finally:
                workbook.release_resources()
        except ImportProblem:
            raise
        except Exception:
            raise ImportProblem('Cannot read that .xls worksheet. Check the tab name or save as .xlsx.')
    raise ImportProblem('Choose a .csv, .xlsx, or .xls file.')


def suggested_mapping(headers):
    used = set()
    mapping = []
    for header in headers:
        field = ALIASES.get(norm(header), '')
        if field in used:
            field = ''
        mapping.append(field)
        if field:
            used.add(field)
    return mapping


def sheets_credentials():
    from google.oauth2 import service_account
    raw = os.getenv('GOOGLE_SHEETS_CREDENTIALS_JSON', '').strip()
    path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS', '').strip()
    if not raw and not path:
        raise ImportProblem('Google Sheets is not connected yet. Follow the Google Sheets setup in the installation guide, or download the sheet as CSV/Excel and upload it here.')
    try:
        if raw:
            return service_account.Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
        return service_account.Credentials.from_service_account_file(path, scopes=SCOPES)
    except Exception:
        raise ImportProblem('The Google Sheets connection needs attention. Check the server credentials.')


def read_google_sheet(link, worksheet='', session=None):
    parsed = urlparse(link.strip())
    match = re.fullmatch(r'/spreadsheets/d/([A-Za-z0-9_-]+)(?:/.*)?', parsed.path)
    if parsed.scheme != 'https' or parsed.netloc != 'docs.google.com' or not match:
        raise ImportProblem('Paste a Google Sheets link beginning https://docs.google.com/spreadsheets/d/.')
    spreadsheet_id = match.group(1)
    own_session = session is None
    if own_session:
        from google.auth.transport.requests import AuthorizedSession
        session = AuthorizedSession(sheets_credentials())
    try:
        # Resolve the selected tab by exact name or the URL gid, then request a bounded range.
        metadata = session.get(f'https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}', params={'fields': 'sheets.properties'}, timeout=30)
        if metadata.status_code != 200:
            raise ImportProblem('Cannot open that Google Sheet. Share it with the configured Google connection as Viewer and enable the Sheets API.')
        tabs = [s['properties'] for s in metadata.json().get('sheets', [])]
        gid = re.search(r'(?:^|[&#?])gid=(\d+)(?:&|$)', parsed.fragment or parsed.query)
        if worksheet:
            tab = next((t for t in tabs if t['title'] == worksheet), None)
        elif gid:
            tab = next((t for t in tabs if str(t['sheetId']) == gid.group(1)), None)
        else:
            tab = tabs[0] if tabs else None
        if not tab:
            raise ImportProblem('That worksheet was not found. Enter its exact tab name.')
        title = tab['title']
        # Request the full tab; a bounded stream prevents hidden truncation or oversized reads.
        range_name = "'" + title.replace("'", "''") + "'"
        response = session.get(f'https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{quote(range_name, safe="")}', params={'valueRenderOption': 'FORMATTED_VALUE'}, timeout=30, stream=True)
        if response.status_code != 200:
            raise ImportProblem('Cannot read that tab. Check the sheet connection and try again.')
        try:
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ImportProblem('The Google Sheet is too large. Import a smaller contact tab.')
                chunks.append(chunk)
            table = table_from_rows(json.loads(b''.join(chunks)).get('values', []))
        finally:
            response.close()
        table['worksheet'] = title
        return table
    except ImportProblem:
        raise
    except Exception:
        raise ImportProblem('The Google Sheets connection failed or timed out. Try again, or upload a CSV/Excel export.')
    finally:
        if own_session:
            session.close()


def parse_date(value, with_time=False):
    # US numeric dates deliberately require a four-digit year.
    for fmt in (['%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M'] if with_time else []) + ['%Y-%m-%d', '%m/%d/%Y', '%m-%d-%Y', '%Y-%m-%d %H:%M:%S']:
        try:
            result = datetime.strptime(value, fmt)
            return result if with_time else result.date()
        except ValueError:
            pass
    raise ValueError('use YYYY-MM-DD or MM/DD/YYYY' + (' with optional HH:MM:SS' if with_time else ''))


def validate_values(values, mapping):
    data, errors = {}, []
    for value, field in zip(values, mapping):
        if not field or not value.strip():
            continue  # Blanks never erase existing values.
        value = value.strip()
        try:
            if field in DATES or field == 'last_contact':
                data[field] = parse_date(value, field == 'last_contact')
            elif field in BOOLS:
                if value.casefold() not in {'yes', 'no', 'true', 'false', '1', '0', 'y', 'n', 'on', 'off'}:
                    raise ValueError('use Yes/No, True/False, or 1/0')
                data[field] = value.casefold() in {'yes', 'true', '1', 'y', 'on'}
            elif field == 'call_attempts':
                if not value.isdecimal() or int(value) > 2147483647:
                    raise ValueError('use a nonnegative whole number')
                data[field] = int(value)
            else:
                if field == 'email':
                    value = value.lower()
                    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
                        raise ValueError('enter a valid email address')
                if field in {'state', 'medicare_mbi', 'plan_id'}:
                    value = value.upper()
                if field == 'state' and not re.fullmatch('[A-Z]{2}', value):
                    raise ValueError('use a two-letter state abbreviation')
                if field == 'zip_code':
                    if value.isdecimal() and len(value) < 5:
                        value = value.zfill(5)
                    if not re.fullmatch(r'\d{5}(?:-\d{4})?', value):
                        raise ValueError('use a five-digit ZIP or ZIP+4')
                if field == 'status':
                    canonical = next((s for s in STATUSES if s.casefold() == value.casefold()), None)
                    if not canonical:
                        raise ValueError('use a CRM status such as New, Sold, or Do Not Call')
                    value = canonical
                if field == 'priority':
                    canonical = next((s for s in ['Low', 'Normal', 'High'] if s.casefold() == value.casefold()), None)
                    if not canonical:
                        raise ValueError('use Low, Normal, or High')
                    value = canonical
                max_length = getattr(FIELDS[field].type, 'length', None)
                if max_length and len(value) > max_length:
                    raise ValueError(f'maximum {max_length} characters')
                data[field] = value
        except ValueError as exc:
            errors.append(f'{LABELS[field]}: {exc}.')
    for field in ('first_name', 'last_name'):
        if not data.get(field):
            errors.append(f'{LABELS[field]} is required.')
    return data, errors


def json_data(data):
    return {k: v.isoformat() if isinstance(v, (date, datetime)) else v for k, v in data.items()}


def hydrate(data):
    return {k: (datetime.fromisoformat(v) if k == 'last_contact' else date.fromisoformat(v)) if v and (k in DATES or k == 'last_contact') else v for k, v in data.items()}


def identity_keys(data):
    keys = set()
    if data.get('medicare_mbi'):
        keys.add(('mbi', norm(data['medicare_mbi'])))
    if data.get('email'):
        keys.add(('email', data['email'].strip().casefold()))
    for field in ('phone', 'mobile'):
        digits = re.sub(r'\D', '', data.get(field) or '')
        if len(digits) == 11 and digits.startswith('1'):
            digits = digits[1:]
        if len(digits) >= 7:
            keys.add(('phone', digits))
    if data.get('date_of_birth') and data.get('first_name') and data.get('last_name'):
        keys.add(('name_dob', norm(data['first_name']) + ':' + norm(data['last_name']) + ':' + str(data['date_of_birth'])))
    # Names alone are too weak: flag exact unidentifiable repeats within a source separately.
    return keys


def preview_import(db, table, mapping, mode):
    if mode not in {'skip', 'update'}:
        raise ImportProblem('Choose whether to skip or update matching contacts.')
    selected = [f for f in mapping if f]
    if len(mapping) != len(table['headers']) or any(f not in FIELDS for f in selected):
        raise ImportProblem('Invalid column matching. Match the columns again.')
    if len(selected) != len(set(selected)):
        raise ImportProblem('Each CRM field can be matched to only one source column.')
    if not {'first_name', 'last_name'}.issubset(selected):
        raise ImportProblem('Match both First Name and Last Name before previewing.')
    leads = db.scalars(select(Lead)).all()
    existing = {lead.id: {k: getattr(lead, k) for k in FIELDS} for lead in leads}
    index = {}
    for lead_id, data in existing.items():
        for key in identity_keys(data):
            index.setdefault(key, set()).add(lead_id)
    existing_names = {}
    for lead_id, values in existing.items():
        existing_names.setdefault((norm(values['first_name']), norm(values['last_name'])), []).append(lead_id)
    seen = set()
    seen_keys = set()
    seen_names_without_keys = set()
    results = []
    for item in table['rows']:
        data, errors = validate_values(item['values'], mapping)
        keys = identity_keys(data)
        matches = set().union(*(index.get(key, set()) for key in keys)) if keys else set()
        action, lead_id = 'create', None
        name_key = (norm(data.get('first_name')), norm(data.get('last_name')))
        if not keys and (name_key in existing_names or name_key in seen_names_without_keys):
            errors.append('This name already appears, but there is no identifier to confirm a match. Add email, phone, Medicare MBI, or date of birth.')
        if len(matches) > 1:
            errors.append('Identifiers match multiple contacts. Resolve these conflicts before importing this row.')
        elif matches:
            lead_id = next(iter(matches))
            old = existing[lead_id]
            same_name = all(norm(data.get(k)) == norm(old.get(k)) for k in ('first_name', 'last_name'))
            exact_mbi = bool(data.get('medicare_mbi')) and norm(data['medicare_mbi']) == norm(old.get('medicare_mbi'))
            if not same_name and not exact_mbi:
                errors.append('A phone or email belongs to a different name. Review the contact rather than merging automatically.')
            action = mode
            if mode == 'update':
                if old.get('status') == 'Do Not Call' and data.get('status', 'Do Not Call') != 'Do Not Call':
                    errors.append('Import cannot remove an existing Do Not Call status. Review it in the contact console.')
                if old.get('medicare_mbi') and data.get('medicare_mbi') and norm(old['medicare_mbi']) != norm(data['medicare_mbi']):
                    errors.append('Medicare MBI conflicts with the matching contact.')
        fingerprint = json.dumps(json_data(data), sort_keys=True)
        if not errors:
            if fingerprint in seen or keys & seen_keys:
                action = 'skip'
                message = 'Repeated contact within this import; first valid row takes precedence.'
            else:
                message = {'create': 'New contact', 'skip': f'Matches contact #{lead_id}; skipped', 'update': f'Update nonblank matched fields on contact #{lead_id}'}[action]
            seen.add(fingerprint)
            seen_keys.update(keys)
            if not keys:
                seen_names_without_keys.add(name_key)
        else:
            action, message = 'error', ' '.join(errors)
        results.append({'row': item['row'], 'action': action, 'lead_id': lead_id, 'name': f"{data.get('first_name', '')} {data.get('last_name', '')}".strip(), 'message': message, 'data': json_data(data), 'before': json_data(existing[lead_id]) if lead_id else None})
    return {'rows': results, 'counts': {a: sum(r['action'] == a for r in results) for a in ['create', 'update', 'skip', 'error']}, 'mode': mode}


def signature(preview):
    return hashlib.sha256(json.dumps(preview, sort_keys=True).encode()).hexdigest()
