"""Owner-only Google sign-in with one-use challenges and revocable CRM sessions.

The private Google Apps Script web app signs a short-lived assertion only after
Google identifies its owner. The webhook key used for golf intake cannot log in.
"""
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
import re
import secrets
from collections import defaultdict, deque
from threading import Lock
import time
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import Column, DateTime, String, delete, update
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from app.database import Base, SessionLocal, get_db

router = APIRouter()
templates = Jinja2Templates(directory='app/templates')
SESSION_COOKIE = '__Host-wsbco_session'
CHALLENGE_COOKIE = '__Host-wsbco_login'
SESSION_SECONDS = 12 * 60 * 60
CHALLENGE_SECONDS = 5 * 60
login_attempts = defaultdict(deque)
attempts_lock = Lock()


class CrmSession(Base):
    __tablename__ = 'crm_auth_sessions'
    token_hash = Column(String(64), primary_key=True)
    owner_email = Column(String(255), nullable=False)
    expires_at = Column(DateTime, nullable=False, index=True)


class LoginChallenge(Base):
    __tablename__ = 'crm_login_challenges'
    nonce_hash = Column(String(64), primary_key=True)
    next_path = Column(String(1024), nullable=False, default='/leads')
    expires_at = Column(DateTime, nullable=False, index=True)
    used_at = Column(DateTime, nullable=True)


def now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def owner_email():
    return os.getenv('CRM_OWNER_EMAIL', 'williamsburton@gmail.com').strip().lower()


def public_origin():
    return os.getenv('CRM_PUBLIC_URL', 'https://wsbco-crm.onrender.com').rstrip('/')


def safe_next(value):
    value = value or '/leads'
    if any(ord(c) < 32 for c in value):
        return '/leads'
    value = value.strip()
    if (not value.startswith('/') or value.startswith('//') or '\\' in value
            or any(ord(c) < 32 for c in value) or len(value) > 1024):
        return '/leads'
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.path.startswith(('/auth/', '/logout', '/login')):
        return '/leads'
    return value


def configured_login_url():
    value = os.getenv('CRM_GOOGLE_LOGIN_URL', '').strip()
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or parsed.hostname != 'script.google.com'
            or not re.fullmatch(r'/macros/s/[A-Za-z0-9_-]+/exec', parsed.path)
            or parsed.query or parsed.fragment):
        return ''
    return value


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def service_endpoint(path, method):
    if path in {'/', '/login', '/auth/google/start', '/health'} and method in {'GET', 'HEAD'}:
        return True
    if path == '/auth/google/complete' and method == 'POST':
        return True
    if path.startswith('/static/') and method in {'GET', 'HEAD'}:
        return True
    if method == 'POST' and path in {'/golf/inquiries', '/api/website/leads'}:
        return True  # These handlers retain their own intake authentication/validation.
    if method == 'OPTIONS' and path == '/api/website/leads':
        return True  # CORSMiddleware validates the public website's preflight.
    if method == 'POST' and re.fullmatch(r'/twilio/(connect|status)/\d+', path):
        return True  # These handlers require a verified Twilio signature.
    return False


def same_origin_mutation(request):
    origin = request.headers.get('origin', '')
    if origin == public_origin():
        return True
    # A privacy-preserving Referrer-Policy can suppress Origin on a genuine
    # same-origin navigation POST. Sec-Fetch-Site is set by the browser and
    # cannot be supplied by cross-site page scripts. Never accept same-site.
    return origin in {'', 'null'} and request.headers.get('sec-fetch-site') == 'same-origin'


class OwnerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request.state.crm_owner = None
        token = request.cookies.get(SESSION_COOKIE, '')
        if re.fullmatch(r'[a-f0-9]{64}', token):
            with SessionLocal() as db:
                session = db.get(CrmSession, digest(token))
                if session and session.expires_at > now_utc() and session.owner_email == owner_email():
                    request.state.crm_owner = session.owner_email
        public = service_endpoint(request.url.path, request.method)
        if not public and not request.state.crm_owner:
            if request.method in {'GET', 'HEAD'} and 'text/html' in request.headers.get('accept', ''):
                destination = safe_next(request.url.path + ('?' + request.url.query if request.url.query else ''))
                response = RedirectResponse('/login?' + urlencode({'next': destination}), status_code=303)
            else:
                response = JSONResponse({'detail': 'Sign in to your private workspace.'}, status_code=401)
        elif (not public and request.method not in {'GET', 'HEAD', 'OPTIONS'}
              and not same_origin_mutation(request)):
            response = JSONResponse({'detail': 'Please submit changes from your CRM workspace.'}, status_code=403)
        else:
            response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "frame-ancestors 'none'"
        response.headers['Referrer-Policy'] = 'no-referrer'
        if not request.url.path.startswith('/static/'):
            response.headers['Cache-Control'] = 'no-store'
        return response


@router.get('/login')
def login(request: Request, next: str = '/leads', error: str = ''):
    errors = {
        'expired': 'Your sign-in expired. Please try again.',
        'account': 'This Google account does not have access to this workspace.',
        'unavailable': 'Sign-in is being prepared. Please try again shortly.',
    }
    return templates.TemplateResponse(request=request, name='scenic_entry.html', context={
        'signed_in': bool(getattr(request.state, 'crm_owner', None)),
        'next_path': safe_next(next), 'login_error': errors.get(error, ''),
    })


@router.get('/auth/google/start')
def start_google_login(request: Request, next: str = '/leads', db: Session = Depends(get_db)):
    google_url = configured_login_url()
    secret = os.getenv('CRM_GOOGLE_SIGNING_KEY', '').strip()
    if not google_url or len(secret) < 32:
        return RedirectResponse('/login?error=unavailable', status_code=303)
    ip = request.client.host if request.client else 'unknown'
    with attempts_lock:
        moment = time.monotonic()
        # Bound both per-client traffic and the in-memory client index.
        for old_ip in [key for key, values in login_attempts.items() if not values or values[-1] <= moment - 600]:
            del login_attempts[old_ip]
        if ip not in login_attempts and len(login_attempts) >= 10000:
            return JSONResponse({'detail': 'Please try signing in shortly.'}, status_code=429)
        attempts = login_attempts[ip]
        while attempts and attempts[0] <= moment - 600:
            attempts.popleft()
        if len(attempts) >= 30:
            return JSONResponse({'detail': 'Please try signing in shortly.'}, status_code=429)
        attempts.append(moment)
    nonce = secrets.token_hex(32)
    now = now_utc()
    db.execute(delete(LoginChallenge).where(LoginChallenge.expires_at < now))
    db.execute(delete(CrmSession).where(CrmSession.expires_at < now))
    db.add(LoginChallenge(nonce_hash=digest(nonce), next_path=safe_next(next),
                          expires_at=now + timedelta(seconds=CHALLENGE_SECONDS)))
    db.commit()
    response = RedirectResponse(google_url + '?' + urlencode({'nonce': nonce}), status_code=303)
    response.set_cookie(CHALLENGE_COOKIE, nonce, max_age=CHALLENGE_SECONDS,
                        secure=True, httponly=True, samesite='none', path='/')
    return response


def verified_assertion(assertion, cookie_nonce):
    """Check signature, account, audience, lifetime and browser-bound challenge."""
    secret = os.getenv('CRM_GOOGLE_SIGNING_KEY', '').strip()
    if len(secret) < 32 or not re.fullmatch(r'[a-f0-9]{64}', cookie_nonce):
        raise ValueError('Missing sign-in configuration or browser challenge')
    if len(assertion) > 4096 or assertion.count('.') != 1:
        raise ValueError('Invalid assertion')
    encoded, signature = assertion.split('.')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', encoded + signature):
        raise ValueError('Invalid encoding')
    expected = base64.urlsafe_b64encode(hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).digest()).decode().rstrip('=')
    if not hmac.compare_digest(signature, expected):
        raise ValueError('Invalid signature')
    payload = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
    now = int(datetime.now(timezone.utc).timestamp())
    issued, expiry = payload.get('iat'), payload.get('exp')
    if (not isinstance(issued, int) or not isinstance(expiry, int)
            or expiry <= now or issued > now + 30 or now - issued > CHALLENGE_SECONDS
            or expiry - issued > CHALLENGE_SECONDS or expiry <= issued):
        raise ValueError('Expired assertion')
    if payload.get('iss') != 'wsbco-private-google-login' or payload.get('aud') != public_origin():
        raise ValueError('Invalid audience')
    if payload.get('email', '').lower() != owner_email():
        raise ValueError('Account not allowed')
    if not hmac.compare_digest(str(payload.get('nonce', '')), cookie_nonce):
        raise ValueError('Invalid challenge')
    return payload


@router.post('/auth/google/complete')
async def complete_google_login(request: Request, db: Session = Depends(get_db)):
    # The assertion stays in an HTTPS POST body, never a URL, log or browser history.
    try:
        body_length = int(request.headers.get('content-length', '0'))
    except ValueError:
        body_length = 8193
    if body_length > 8192:
        return RedirectResponse('/login?error=expired', status_code=303)
    form = await request.form()
    nonce = request.cookies.get(CHALLENGE_COOKIE, '')
    try:
        verified_assertion(str(form.get('assertion', '')), nonce)
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, json.JSONDecodeError):
        return RedirectResponse('/login?error=expired', status_code=303)
    challenge = db.get(LoginChallenge, digest(nonce))
    now = now_utc()
    if not challenge or challenge.used_at or challenge.expires_at <= now:
        return RedirectResponse('/login?error=expired', status_code=303)
    destination = safe_next(challenge.next_path)
    consumed = db.execute(update(LoginChallenge).where(
        LoginChallenge.nonce_hash == digest(nonce), LoginChallenge.used_at.is_(None),
        LoginChallenge.expires_at > now).values(used_at=now))
    if consumed.rowcount != 1:
        db.rollback()
        return RedirectResponse('/login?error=expired', status_code=303)
    token = secrets.token_hex(32)
    db.add(CrmSession(token_hash=digest(token), owner_email=owner_email(),
                      expires_at=now + timedelta(seconds=SESSION_SECONDS)))
    db.commit()
    response = RedirectResponse(destination, status_code=303)
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_SECONDS,
                        secure=True, httponly=True, samesite='lax', path='/')
    response.delete_cookie(CHALLENGE_COOKIE, secure=True, httponly=True, samesite='none', path='/')
    return response


@router.post('/logout')
def logout(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE, '')
    if token:
        db.execute(delete(CrmSession).where(CrmSession.token_hash == digest(token)))
        db.commit()
    response = RedirectResponse('/', status_code=303)
    response.delete_cookie(SESSION_COOKIE, secure=True, httponly=True, samesite='lax', path='/')
    return response
