from fastapi import APIRouter, Form, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db, DATA_DIR
from app.models import CallLog
from fastapi.responses import JSONResponse
from pathlib import Path
import sqlite3
from datetime import datetime

router = APIRouter(prefix="/api", tags=["activity"])
DB = DATA_DIR / "wsbco_activity.db"

def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con=sqlite3.connect(DB)
    con.row_factory=sqlite3.Row
    con.execute("""CREATE TABLE IF NOT EXISTS activities(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      lead_id INTEGER NOT NULL,
      activity_type TEXT NOT NULL,
      title TEXT NOT NULL,
      detail TEXT,
      outcome TEXT,
      agent TEXT,
      created_at TEXT NOT NULL
    )""")
    con.execute("CREATE INDEX IF NOT EXISTS ix_activity_lead ON activities(lead_id, created_at DESC)")
    con.commit()
    return con

@router.get("/leads/{lead_id}/activities")
def list_activities(lead_id:int, db: Session = Depends(get_db)):
    with connect() as con:
        rows=con.execute("SELECT * FROM activities WHERE lead_id=? ORDER BY id DESC LIMIT 200",(lead_id,)).fetchall()
    activities = [dict(r) for r in rows]
    calls = db.scalars(select(CallLog).where(CallLog.lead_id == lead_id,
        CallLog.direction == 'manual').order_by(CallLog.started_at.desc()).limit(200)).all()
    activities += [dict(id=f'manual-call-{c.id}', lead_id=lead_id, activity_type='call',
        title='Manual call logged', detail=c.notes, outcome=c.disposition, agent='',
        created_at=c.started_at.isoformat() + 'Z') for c in calls]
    def timestamp(row):
        from datetime import timezone
        value = datetime.fromisoformat(row['created_at'].replace('Z', '+00:00'))
        return value.replace(tzinfo=timezone.utc).timestamp() if value.tzinfo is None else value.timestamp()
    activities.sort(key=timestamp, reverse=True)
    return {"activities": activities[:200]}

@router.post("/leads/{lead_id}/activities")
def add_activity(lead_id:int, activity_type:str=Form("note"), title:str=Form(...),
                 detail:str=Form(""), outcome:str=Form(""), agent:str=Form("")):
    now=datetime.now().astimezone().isoformat(timespec="seconds")
    with connect() as con:
        cur=con.execute("""INSERT INTO activities
          (lead_id,activity_type,title,detail,outcome,agent,created_at)
          VALUES(?,?,?,?,?,?,?)""",
          (lead_id,activity_type,title,detail,outcome,agent,now))
        con.commit()
        rid=cur.lastrowid
    return JSONResponse({"ok":True,"id":rid,"created_at":now})

# Create table during import.
with connect():
    pass
