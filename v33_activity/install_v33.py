from pathlib import Path
import shutil, re
main=Path("app/main.py")
if not main.exists(): raise SystemExit("Run this from /workspaces/WSBCO-CRM")
shutil.copy2(main, Path("app/main_before_v33.py"))
s=main.read_text()
imp="from app.activity_v33 import router as activity_v33_router"
inc="app.include_router(activity_v33_router)"
if imp not in s:
    # place import before first app= assignment
    m=re.search(r"(?m)^app\s*=",s)
    if not m: raise SystemExit("Could not find FastAPI app assignment in app/main.py")
    s=s[:m.start()]+imp+"\n"+s[m.start():]
if inc not in s:
    # insert immediately after first app=... line
    lines=s.splitlines()
    for i,line in enumerate(lines):
        if re.match(r"^app\s*=",line):
            lines.insert(i+1,inc);break
    s="\n".join(lines)+"\n"
main.write_text(s)
print("V3.3 activity router installed. Backup: app/main_before_v33.py")
