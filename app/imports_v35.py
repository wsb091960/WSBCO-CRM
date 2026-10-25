"""Browser-bound, restart-safe import preview and transactional commit."""
import csv
import hashlib
import io
import os
import json
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import DateTime, String, Text, delete, select, update
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.database import Base, get_db
from app.models import Lead
from app.services.contact_import import (
    FIELDS, LABELS, MAX_BYTES, ImportProblem, bulk_correct, hydrate, preview_import,
    read_file, read_google_sheet, signature, suggested_mapping,
)
from app.services.esri_import import eligible_rows, enrich_next_batch

router = APIRouter(prefix='/imports', tags=['Contact imports'])
templates = Jinja2Templates(directory='app/templates')
COOKIE = 'crm_import_browser'


class ContactImportBatch(Base):
    __tablename__ = 'contact_import_batches'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(20), default='mapping')
    payload: Mapped[str] = mapped_column(Text)
    expires: Mapped[datetime] = mapped_column(DateTime, index=True)


def owner_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def browser(request):
    value = request.cookies.get(COOKIE, '')
    return value if len(value) >= 32 else ''


def require_form(request, form):
    token = browser(request)
    if not token or not secrets.compare_digest(str(form.get('csrf', '')), token):
        raise HTTPException(403, 'Open Import Data again, then resubmit the form.')
    return token


def page(request, **context):
    response = templates.TemplateResponse(request=request, name='imports_v35.html', context={
        'signature': signature, 'step': 'source', 'labels': LABELS, 'fields': FIELDS, 'csrf': browser(request), **context,
    })
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'same-origin'
    return response


def get_batch(db, batch_id, token):
    batch = db.get(ContactImportBatch, batch_id)
    if not batch or not token or not secrets.compare_digest(batch.owner, owner_hash(token)):
        raise HTTPException(404, 'Import not found. Open Import Data to start again.')
    if batch.expires < datetime.utcnow():
        db.delete(batch)
        db.commit()
        raise HTTPException(410, 'This import expired. Upload the source again.')
    return batch


@router.get('')
def start(request: Request):
    token = browser(request) or secrets.token_urlsafe(32)
    response = page(request, csrf=token)
    response.set_cookie(COOKIE, token, httponly=True, secure=request.url.scheme == 'https', samesite='strict', max_age=86400)
    return response


@router.get('/template.csv')
def template():
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(list(FIELDS))
    # Header-only template avoids accidentally importing demonstration contacts.
    return Response(output.getvalue(), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="WSBCO_Contact_Import_Template.csv"'})


@router.post('/source')
async def source(request: Request, db: Session = Depends(get_db)):
    form = await request.form(max_files=1, max_fields=10)
    token = require_form(request, form)
    try:
        worksheet = str(form.get('worksheet', '')).strip()
        if len(worksheet) > 100:
            raise ImportProblem('The worksheet name is too long.')
        if form.get('source_type') == 'sheets':
            from starlette.concurrency import run_in_threadpool
            table = await run_in_threadpool(read_google_sheet, str(form.get('sheet_url', '')), worksheet)
            label = 'Google Sheets · ' + table['worksheet']
        elif form.get('source_type') == 'file':
            upload = form.get('file')
            if not hasattr(upload, 'read'):
                raise ImportProblem('Choose a CSV or Excel file.')
            content = await upload.read(MAX_BYTES + 1)
            await upload.close()
            from starlette.concurrency import run_in_threadpool
            table = await run_in_threadpool(read_file, upload.filename or '', content, worksheet)
            label = (upload.filename or 'File').replace('\\', '/').rsplit('/', 1)[-1][:150]
            if table.get('worksheet'):
                label += ' · ' + table['worksheet']
        else:
            raise ImportProblem('Choose a file upload or Google Sheets.')
    except ImportProblem as exc:
        return page(request, error=str(exc))
    db.execute(delete(ContactImportBatch).where(ContactImportBatch.expires < datetime.utcnow()))
    batch = ContactImportBatch(id=secrets.token_urlsafe(24), owner=owner_hash(token), source=label[:255], payload=json.dumps({'table': table}), expires=datetime.utcnow() + timedelta(hours=1))
    db.add(batch)
    db.commit()
    return RedirectResponse('/imports/' + batch.id, status_code=303)


@router.get('/{batch_id}')
def show(request: Request, batch_id: str, db: Session = Depends(get_db)):
    batch = get_batch(db, batch_id, browser(request))
    payload = json.loads(batch.payload)
    if batch.state == 'done':
        return page(request, step='done', batch=batch, summary=payload['summary'])
    table = payload['table']
    return page(request, step='mapping', batch=batch, table=table, mapping=payload.get('mapping', suggested_mapping(table['headers'])), mode=payload.get('mode', 'skip'))


@router.post('/{batch_id}/preview')
async def preview(request: Request, batch_id: str, db: Session = Depends(get_db)):
    form = await request.form(max_fields=110)
    token = require_form(request, form)
    batch = get_batch(db, batch_id, token)
    if batch.state == 'done':
        return RedirectResponse('/imports/' + batch.id, status_code=303)
    payload = json.loads(batch.payload)
    table = payload['table']
    mapping = [str(form.get(f'column_{i}', '')) for i in range(len(table['headers']))]
    mode = str(form.get('mode', 'skip'))
    try:
        result = preview_import(db, table, mapping, mode)
    except ImportProblem as exc:
        return page(request, step='mapping', batch=batch, table=table, mapping=mapping, mode=mode, error=str(exc))
    payload.pop('esri_suggestions', None)  # Mapping changes invalidate earlier geocodes.\n    payload.update(mapping=mapping, mode=mode, preview=result)
    saved = db.execute(update(ContactImportBatch).where(ContactImportBatch.id == batch_id, ContactImportBatch.state.in_(['mapping', 'preview'])).values(payload=json.dumps(payload), state='preview'))
    if saved.rowcount != 1:
        db.rollback()
        return RedirectResponse('/imports/' + batch.id, status_code=303)
    db.commit()
    return page(request, step='preview', batch=batch, result=result)


@router.post('/{batch_id}/esri-preview')
async def esri_preview(request: Request, batch_id: str, db: Session = Depends(get_db)):
    """Resume bounded Esri geocoding in explicit batches; no contact writes."""
    token = require_form(request, await request.form())
    batch = get_batch(db, batch_id, token)
    if batch.state != 'preview':
        raise HTTPException(409, 'Preview the import first.')
    payload = json.loads(batch.payload)
    if not payload.get('preview'):
        raise HTTPException(409, 'Import preview missing.')
    if not os.getenv('ARCGIS_API_KEY'):
        return page(request, step='preview', batch=batch, result=payload['preview'],
                    error='Esri API key is not configured.')
    from starlette.concurrency import run_in_threadpool
    suggestions = await run_in_threadpool(enrich_next_batch, payload['preview'], payload.get('esri_suggestions'), 10)
    # Preserve raw preview signature. Verified suggestions are applied only after
    # recomputing the source preview at commit time.
    payload['esri_suggestions'] = suggestions
    batch.payload = json.dumps(payload)
    db.commit()
    return page(request, step='preview', batch=batch, result=payload['preview'],
                esri_suggestions=suggestions)


@router.post('/{batch_id}/commit')
async def commit(request: Request, batch_id: str, db: Session = Depends(get_db)):
    form = await request.form()
    token = require_form(request, form)
    if form.get('confirm') != 'yes':
        raise HTTPException(400, 'Confirm the preview before importing.')
    batch = get_batch(db, batch_id, token)
    if batch.state == 'done':
        return RedirectResponse('/imports/' + batch.id, status_code=303)
    # Claim before re-reading source or contacts. The database write lock serializes
    # competing imports; claiming and all contact writes share one transaction.
    claim = db.execute(update(ContactImportBatch).where(ContactImportBatch.id == batch_id, ContactImportBatch.state == 'preview').values(state='committing'))
    if claim.rowcount != 1:
        db.rollback()
        raise HTTPException(409, 'Open the import preview before saving.')
    db.refresh(batch)
    payload = json.loads(batch.payload)
    result = preview_import(db, payload['table'], payload['mapping'], payload['mode'])
    if signature(result) != signature(payload['preview']):
        batch.state = 'preview'
        payload['preview'] = result
        batch.payload = json.dumps(payload)
        db.commit()
        return page(request, step='preview', batch=batch, result=result, error='Contacts changed since your preview. Review the refreshed results and confirm again.')
    suggestions = payload.get('esri_suggestions', {})
    try:
        for row in result['rows']:
            suggestion = suggestions.get(str(row['row']), {})
            # Only fill a missing county, never overwrite the imported value.
            if (row['action'] in ('create', 'update')
                    and not row['data'].get('county')
                    and suggestion.get('status') == 'verified'
                    and suggestion.get('county')):
                row['data']['county'] = suggestion['county']
            if row['action'] == 'create':
                db.add(Lead(**hydrate(row['data'])))
            elif row['action'] == 'update':
                lead = db.get(Lead, row['lead_id'])
                for key, value in hydrate(row['data']).items():
                    setattr(lead, key, value)
                lead.updated = datetime.utcnow()
        # Retain rejected source rows until expiry so they can be corrected and retried.
        summary = {'counts': result['counts'], 'rows': [{k: row[k] for k in ('row', 'action', 'message')} for row in result['rows']], 'completed': datetime.utcnow().isoformat() + 'Z'}
        rejected = [row for row in result['rows'] if row['action'] == 'error']
        batch.payload = json.dumps({'summary': summary, 'rejected': {'headers': payload['table']['headers'], 'rows': rejected}})
        batch.state = 'done'
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(500, 'The import could not be saved. No rows were committed. Try again from the preview.')
    return RedirectResponse('/imports/' + batch.id, status_code=303)


@router.post('/{batch_id}/cancel')
async def cancel(request: Request, batch_id: str, db: Session = Depends(get_db)):
    token = require_form(request, await request.form())
    batch = get_batch(db, batch_id, token)
    db.delete(batch)
    db.commit()
    return RedirectResponse('/imports', status_code=303)


def safe_csv(value):
    value = str(value)
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')) else value


@router.get('/{batch_id}/results.csv')
def results_csv(request: Request, batch_id: str, db: Session = Depends(get_db)):
    batch = get_batch(db, batch_id, browser(request))
    payload = json.loads(batch.payload)
    result = payload.get('summary') or payload.get('preview')
    if not result:
        raise HTTPException(409, 'Preview this import first.')
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['Source row', 'Result', 'Details'])
    for row in result['rows']:
        writer.writerow([row['row'], row['action'], safe_csv(row['message'])])
    return Response(output.getvalue(), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="WSBCO_Import_Results.csv"', 'Cache-Control': 'no-store'})


@router.post('/{batch_id}/correct')
async def correct(request: Request, batch_id: str, db: Session = Depends(get_db)):
    form = await request.form(max_fields=10)
    token = require_form(request, form)
    batch = get_batch(db, batch_id, token)
    payload = json.loads(batch.payload)
    if batch.state != 'preview':
        raise HTTPException(409, 'Preview this import before applying a correction.')
    # A stale tab must not overwrite newer corrections or a committed batch.
    if form.get('revision') != signature(payload['preview']):
        raise HTTPException(409, 'The preview changed. Refresh it before correcting rows.')
    try:
        table = bulk_correct(payload['table'], payload['mapping'], str(form.get('field', '')), str(form.get('old', '')), str(form.get('replacement', '')))
        result = preview_import(db, table, payload['mapping'], payload['mode'])
    except ImportProblem as exc:
        return page(request, step='preview', batch=batch, result=payload['preview'], error=str(exc))
    previous = batch.payload
    payload.pop('esri_suggestions', None)  # Corrected addresses invalidate geocodes.\n    payload.update(table=table, preview=result)
    changed = db.execute(update(ContactImportBatch).where(ContactImportBatch.id == batch_id, ContactImportBatch.state == 'preview', ContactImportBatch.payload == previous).values(payload=json.dumps(payload)))
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, 'The import changed. Refresh before trying again.')
    db.commit()
    return page(request, step='preview', batch=batch, result=result)


def source_csv_response(headers, rows, filename):
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow([safe_csv(v) for v in headers])
    writer.writerows([[safe_csv(v) for v in row] for row in rows])
    return Response(output.getvalue(), media_type='text/csv', headers={'Content-Disposition': f'attachment; filename="{filename}"', 'Cache-Control': 'no-store'})


@router.get('/{batch_id}/errors.csv')
def errors_csv(request: Request, batch_id: str, db: Session = Depends(get_db)):
    batch = get_batch(db, batch_id, browser(request))
    payload = json.loads(batch.payload)
    if batch.state == 'done':
        rejected = payload.get('rejected', {'headers': [], 'rows': []})
        headers, rows = rejected['headers'], rejected['rows']
    elif payload.get('preview'):
        headers = payload['table']['headers']
        rows = [r for r in payload['preview']['rows'] if r['action'] == 'error']
    else:
        raise HTTPException(409, 'Preview this import first.')
    # Original columns retain the original source values; first columns are ready for retry.
    meta = ['Import source row', 'Import error details', 'Original source values (JSON)']
    return source_csv_response(headers + meta, [r['cleaned_values'] + [r['row'], r['message'], json.dumps(dict(zip(headers, r['original_values'])), ensure_ascii=False)] for r in rows], 'WSBCO_Rejected_Rows.csv')


@router.get('/{batch_id}/cleaned.csv')
def cleaned_csv(request: Request, batch_id: str, db: Session = Depends(get_db)):
    batch = get_batch(db, batch_id, browser(request))
    payload = json.loads(batch.payload)
    if not payload.get('preview'):
        raise HTTPException(409, 'Download the cleaned file from the preview before committing.')
    return source_csv_response(payload['table']['headers'], [r['cleaned_values'] for r in payload['preview']['rows']], 'WSBCO_Cleaned_Contacts.csv')


@router.get('/{batch_id}/original.csv')
def original_csv(request: Request, batch_id: str, db: Session = Depends(get_db)):
    batch = get_batch(db, batch_id, browser(request))
    payload = json.loads(batch.payload)
    if 'table' not in payload:
        raise HTTPException(409, 'The full source is cleared after commit. Rejected rows retain their original values.')
    table = payload['table']
    return source_csv_response(table['headers'], [r.get('original_values', r['values']) for r in table['rows']], 'WSBCO_Original_Source_Values.csv')
