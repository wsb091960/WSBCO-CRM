from pathlib import Path
import re, shutil
p=Path("app/main.py")
if not p.exists(): raise SystemExit("Run from /workspaces/WSBCO-CRM")
shutil.copy2(p,"app/main_before_v34.py")
s=p.read_text()
imp="from app.followup_v34 import router as followup_v34_router"
inc="app.include_router(followup_v34_router)"
if imp not in s:
    anchor="from app.activity_v33 import router as activity_v33_router"
    if anchor in s: s=s.replace(anchor,anchor+"\n"+imp)
    else:
        m=re.search(r"(?m)^BASE_DIR\s*=",s)
        if not m: raise SystemExit("Could not find safe import insertion point")
        s=s[:m.start()]+imp+"\n\n"+s[m.start():]
if inc not in s:
    anchor="app.include_router(activity_v33_router)"
    if anchor in s: s=s.replace(anchor,anchor+"\n"+inc)
    else:
        matches=list(re.finditer(r"(?m)^app\.include_router\([^)]+\)\s*$",s))
        if not matches: raise SystemExit("Could not find safe router insertion point")
        pos=matches[-1].end(); s=s[:pos]+"\n"+inc+s[pos:]
p.write_text(s)
print("V3.4 router installed safely. Backup: app/main_before_v34.py")
