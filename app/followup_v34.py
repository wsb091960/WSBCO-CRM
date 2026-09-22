from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
import sqlite3
from datetime import date, datetime, timedelta

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
DB_CANDIDATES = [
    Path("data/golf_coach.db"), Path("data/crm.db"), Path("data/wsbco_crm.db"),
    Path("data/insurance_crm.db"), Path("data/app.db")
]

def find_db():
    for p in DB_CANDIDATES:
        if p.exists(): return p
    dbs=list(Path("data").glob("*.db"))
    if not dbs: raise RuntimeError("No CRM SQLite database found in data/")
    # Avoid selecting the separate V3.3 activity DB as the CRM database.
    for p in dbs:
        if p.name != "wsbco_activity.db": return p
    raise RuntimeError("CRM database not found")

def rows():
    db=find_db()
    con=sqlite3.connect(db); con.row_factory=sqlite3.Row
    tables=[r[0] for r in con.execute("select name from sqlite_master where type='table'")]
    table="leads" if "leads" in tables else ("contacts" if "contacts" in tables else None)
    if not table:
        con.close(); raise RuntimeError("Could not find leads/contacts table")
    cols={r[1] for r in con.execute(f"pragma table_info({table})")}
    wanted=["id","first_name","last_name","phone","mobile","status","priority",
            "next_follow_up","follow_up_type","medicare_effective_date","last_contact"]
    sel=[c for c in wanted if c in cols]
    data=[dict(r) for r in con.execute(f"select {','.join(sel)} from {table}").fetchall()]
    con.close()
    return data

def parse_day(v):
    if not v: return None
    s=str(v)[:10]
    try: return date.fromisoformat(s)
    except: return None

@router.get("/calendar", response_class=HTMLResponse)
def followup_center(request: Request, view: str="today"):
    today=date.today()
    items=[]
    for x in rows():
        d=parse_day(x.get("next_follow_up"))
        if not d: continue
        x["follow_date"]=d
        x["days_delta"]=(d-today).days
        if d < today: x["bucket"]="overdue"
        elif d == today: x["bucket"]="today"
        else: x["bucket"]="upcoming"
        items.append(x)
    counts={
      "today":sum(x["bucket"]=="today" for x in items),
      "overdue":sum(x["bucket"]=="overdue" for x in items),
      "upcoming":sum(x["bucket"]=="upcoming" for x in items),
      "all":len(items)
    }
    if view in ("today","overdue","upcoming"):
        shown=[x for x in items if x["bucket"]==view]
    else: shown=items
    shown.sort(key=lambda x:(x["follow_date"], x.get("priority")!="Urgent", x.get("last_name") or ""))
    return templates.TemplateResponse(
        request=request,
        name="calendar_v34.html",
        context={
            "items": shown,
            "counts": counts,
            "view": view,
            "today": today,
        },
    )
