"""Private senior-center outreach, shared by the CRM and the private GIS Site.

The service token grants access only to this isolated center outreach collection;
no beneficiary/contact records are returned through these endpoints.
"""
from datetime import date, datetime, timezone
import csv
import io
import json
import os
import re
import secrets
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import Column, Integer, String, Text, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base, get_db

router = APIRouter()
templates = Jinja2Templates(directory='app/templates')
GIS_URL = 'https://wsbco-san-antonio-senior-outreach.williamsburton.chatgpt.site'
CENTER_ID = re.compile(r'^[a-z0-9][a-z0-9_-]{0,119}$')
STATUSES = {
    'not_contacted': 'Not contacted',
    'contacted': 'Contacted',
    'meeting_scheduled': 'Meeting scheduled',
    'event_scheduled': 'Event scheduled',
    'follow_up': 'Follow-up needed',
    'completed': 'Completed',
}
MAX_BODY = 24_000


class SeniorOutreachRecord(Base):
    __tablename__ = 'senior_center_outreach'
    center_id = Column(String(120), primary_key=True)
    center_name = Column(String(240), nullable=False)
    address = Column(String(500), nullable=False, default='')
    type = Column(String(40), nullable=False, default='')
    contact_name = Column(String(160), nullable=False, default='')
    contact_phone = Column(String(80), nullable=False, default='')
    status = Column(String(40), nullable=False, default='not_contacted', index=True)
    last_contact_date = Column(String(10), nullable=False, default='')
    next_follow_up = Column(String(10), nullable=False, default='', index=True)
    notes = Column(Text, nullable=False, default='')
    updated_at = Column(String(40), nullable=False)
    version = Column(Integer, nullable=False, default=1)


class OutreachInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    center_name: str = Field(min_length=1, max_length=240)
    address: str = Field(default='', max_length=500)
    type: Literal['', 'comprehensive', 'part_time', 'partner', 'closed', 'unknown'] = ''
    contact_name: str = Field(default='', max_length=160)
    contact_phone: str = Field(default='', max_length=80)
    status: Literal['not_contacted', 'contacted', 'meeting_scheduled', 'event_scheduled', 'follow_up', 'completed'] = 'not_contacted'
    last_contact_date: str = Field(default='', max_length=10)
    next_follow_up: str = Field(default='', max_length=10)
    notes: str = Field(default='', max_length=6000)
    version: int = Field(default=0, ge=0, le=2_147_483_646, strict=True)

    @field_validator('last_contact_date', 'next_follow_up')
    @classmethod
    def valid_date(cls, value):
        if value and (not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) or date.fromisoformat(value).isoformat() != value):
            raise ValueError('Use a valid YYYY-MM-DD date, or leave empty.')
        return value

    @field_validator('center_name', 'address', 'contact_name', 'contact_phone', 'notes')
    @classmethod
    def no_controls(cls, value):
        if any(ord(c) < 32 and c not in '\n\r\t' for c in value):
            raise ValueError('Unsupported control character.')
        return value


def valid_id(center_id):
    if not CENTER_ID.fullmatch(center_id):
        raise HTTPException(422, 'Invalid center ID.')
    return center_id


def require_service_token(request: Request):
    expected = os.getenv('SENIOR_OUTREACH_SERVICE_TOKEN', '').strip()
    if len(expected) < 32:
        raise HTTPException(503, 'Senior outreach connection is not configured.')
    supplied = request.headers.get('authorization', '')
    if len(supplied) > 512 or not supplied.startswith('Bearer '):
        raise HTTPException(401, 'Invalid senior outreach service credential.')
    if not secrets.compare_digest(supplied[7:].encode(), expected.encode()):
        raise HTTPException(401, 'Invalid senior outreach service credential.')


def serialize(row):
    return {column.name: getattr(row, column.name) for column in SeniorOutreachRecord.__table__.columns}


def list_records(db):
    return [serialize(r) for r in db.scalars(select(SeniorOutreachRecord).order_by(SeniorOutreachRecord.updated_at.desc(), SeniorOutreachRecord.center_id)).all()]


async def parse_record(request):
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_BODY:
            raise HTTPException(413, 'Outreach record is too large.')
    if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
        raise HTTPException(415, 'Use application/json.')
    try:
        data = json.loads(raw)
        return OutreachInput.model_validate(data)
    except (ValueError, TypeError, ValidationError):
        raise HTTPException(422, 'Invalid outreach record. Check field lengths, status, version and dates.')


def save_record(db, center_id, data):
    valid_id(center_id)
    values = data.model_dump(exclude={'version'})
    values['updated_at'] = datetime.now(timezone.utc).isoformat()
    if data.version == 0:
        row = SeniorOutreachRecord(center_id=center_id, **values, version=1)
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, 'This center already has outreach. Reload before saving.')
    else:
        result = db.execute(update(SeniorOutreachRecord).where(
            SeniorOutreachRecord.center_id == center_id,
            SeniorOutreachRecord.version == data.version,
        ).values(**values, version=data.version + 1))
        if result.rowcount != 1:
            db.rollback()
            raise HTTPException(409, 'Outreach changed in another window. Reload before saving.')
        db.commit()
    return serialize(db.get(SeniorOutreachRecord, center_id))


@router.get('/api/senior-outreach/service/records', dependencies=[Depends(require_service_token)])
@router.get('/api/senior-outreach/records')
def outreach_list(db: Session = Depends(get_db)):
    return JSONResponse({'records': list_records(db)}, headers={'Cache-Control': 'no-store'})


@router.get('/api/senior-outreach/service/records/{center_id}', dependencies=[Depends(require_service_token)])
@router.get('/api/senior-outreach/records/{center_id}')
def outreach_get(center_id: str, db: Session = Depends(get_db)):
    row = db.get(SeniorOutreachRecord, valid_id(center_id))
    if not row:
        raise HTTPException(404, 'No outreach saved for this center.')
    return JSONResponse(serialize(row), headers={'Cache-Control': 'no-store'})


@router.put('/api/senior-outreach/service/records/{center_id}', dependencies=[Depends(require_service_token)])
@router.put('/api/senior-outreach/records/{center_id}')
async def outreach_save(center_id: str, request: Request, db: Session = Depends(get_db)):
    data = await parse_record(request)
    return JSONResponse(save_record(db, center_id, data), headers={'Cache-Control': 'no-store'})


@router.get('/senior-outreach')
def dashboard(request: Request, db: Session = Depends(get_db)):
    rows = list_records(db)
    today = datetime.now(timezone.utc).astimezone(ZoneInfo('America/Los_Angeles')).date().isoformat()
    counts = {key: sum(r['status'] == key for r in rows) for key in STATUSES}
    due = sum(bool(r['next_follow_up']) and r['next_follow_up'] <= today and r['status'] != 'completed' for r in rows)
    return templates.TemplateResponse(request=request, name='senior_outreach.html', context={
        'rows': rows, 'statuses': STATUSES, 'counts': counts, 'due': due, 'today': today, 'gis_url': GIS_URL,
    }, headers={'Cache-Control': 'no-store'})


@router.get('/senior-outreach/export.csv')
def export_records(db: Session = Depends(get_db)):
    columns = [c.name for c in SeniorOutreachRecord.__table__.columns]
    output = io.StringIO(); writer = csv.DictWriter(output, fieldnames=columns); writer.writeheader()
    for row in list_records(db):
        # Spreadsheet formulas must not execute when a saved note is exported.
        writer.writerow({k: "'" + str(v) if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@')) else v for k, v in row.items()})
    return Response(output.getvalue(), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="senior-center-outreach.csv"', 'Cache-Control': 'no-store'})
