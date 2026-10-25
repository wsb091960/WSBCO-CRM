"""Single-user CRM sign-in. No credentials or sessions are stored in the CRM database."""
import hashlib
import hmac
import os
import secrets
import time
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

router = APIRouter()
COOKIE = "wsbco_session"
TTL = 12 * 3600

def _settings():
    password = os.environ.get("CRM_ADMIN_PASSWORD", "")
    secret = os.environ.get("CRM_SESSION_SECRET", "")
    return password, secret

def _valid_session(request):
    _, secret = _settings()
    raw = request.cookies.get(COOKIE, "")
    if len(secret) < 32 or not raw or "." not in raw:
        return False
    timestamp, signature = raw.split(".", 1)
    if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > TTL:
        return False
    expected = hmac.new(secret.encode(), timestamp.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)

def _cookie(request, response):
    _, secret = _settings()
    timestamp = str(int(time.time()))
    signature = hmac.new(secret.encode(), timestamp.encode(), hashlib.sha256).hexdigest()
    response.set_cookie(COOKIE, timestamp + "." + signature, max_age=TTL,
                        httponly=True, secure=request.url.scheme == "https" or
                        request.headers.get("x-forwarded-proto", "").lower() == "https",
                        samesite="strict", path="/")

LOGIN_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in | WSBCO CRM</title>
<style>body{font:16px system-ui;background:#f2f5f1;display:grid;place-items:center;min-height:90vh}
main{background:white;padding:2rem;max-width:360px;width:85%;border-radius:14px;box-shadow:0 5px 30px #1232}
h1{color:#14543b;font-size:1.6rem}input,button{box-sizing:border-box;width:100%;padding:12px;margin:8px 0;border-radius:7px}
button{background:#14543b;color:white;border:0;cursor:pointer}.error{color:#9b2020}</style></head>
<body><main><h1>WSBCO CRM</h1><p>Sign in to access your contacts and GIS map.</p>
{{error}}<form method="post" action="/login"><label for="password">Password</label>
<input id="password" name="password" type="password" autocomplete="current-password" required autofocus>
<button type="submit">Sign in</button></form></main></body></html>"""

@router.get("/login")
def login_page(request: Request):
    if _valid_session(request):
        return RedirectResponse("/", status_code=303)
    return HTMLResponse(LOGIN_PAGE.replace("{{error}}", ""))

@router.post("/login")
async def login(request: Request):
    password, secret = _settings()
    if not password or len(secret) < 32:
        return PlainTextResponse("CRM sign-in is not configured. Set CRM_ADMIN_PASSWORD and CRM_SESSION_SECRET on the server.", status_code=503)
    form = await request.form()
    supplied = str(form.get("password", ""))
    if not hmac.compare_digest(supplied.encode(), password.encode()):
        time.sleep(0.35)
        return HTMLResponse(LOGIN_PAGE.replace("{{error}}", '<p class="error">Incorrect password.</p>'), status_code=401)
    response = RedirectResponse("/", status_code=303)
    _cookie(request, response)
    return response

@router.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE, path="/")
    return response

class CRMSignInMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        if path == "/health" or path.startswith("/static/"):
            return await call_next(request)
        # Website contact form must remain publicly available.
        if path == "/api/website/leads" and request.method == "POST":
            return await call_next(request)
        if path == "/login":
            if request.method == "POST" and not _same_origin(request):
                return PlainTextResponse("Invalid origin", status_code=403)
            return await call_next(request)
        password, secret = _settings()
        if not password or len(secret) < 32:
            return PlainTextResponse("CRM sign-in is not configured. Set CRM_ADMIN_PASSWORD and CRM_SESSION_SECRET.", status_code=503)
        if not _valid_session(request):
            if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
                return RedirectResponse("/login", status_code=303)
            return JSONResponse({"detail": "Sign-in required"}, status_code=401)
        if request.method not in ("GET", "HEAD", "OPTIONS") and not _same_origin(request):
            return PlainTextResponse("Invalid origin", status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

def _same_origin(request):
    origin = request.headers.get("origin", "")
    if not origin:
        return False
    from urllib.parse import urlsplit
    parsed = urlsplit(origin)
    host = request.headers.get("host", "")
    return parsed.scheme in ("https", "http") and parsed.netloc.lower() == host.lower()
