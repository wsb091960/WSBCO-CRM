from pathlib import Path
from datetime import datetime
import shutil
root=Path(__file__).resolve().parent
source=root/'v36_plan_comparison'
main=root/'app/main.py'
detail=root/'app/templates/lead_detail.html'
if not main.exists() or not detail.exists():
    raise SystemExit('Run from WSBCO-CRM repository root')
main_text=main.read_text()
detail_text=detail.read_text()
if 'plan_compare_v36' not in main_text:
    anchor='from app.imports_v35 import router as imports_v35_router'
    if anchor not in main_text: raise SystemExit('Expected V3.5 app/main.py not found; no changes made')
    main_text=main_text.replace(anchor,anchor+'\nfrom app.plan_compare_v36 import router as plan_compare_v36_router')
    main_text=main_text.replace('app.include_router(imports_v35_router)','app.include_router(imports_v35_router)\napp.include_router(plan_compare_v36_router)')
    main_text=main_text.replace('version="3.5.0"','version="3.6.0"').replace('"phase": "3.5"','"phase": "3.6"')
if 'Compare Plans' not in detail_text:
    anchor='<div class="actions"><a href="/leads">Contacts</a>'
    if anchor not in detail_text: raise SystemExit('Expected contact console template not found; no changes made')
    detail_text=detail_text.replace(anchor, '<div class="actions"><a href="/leads/{{lead.id}}/compare" onclick="window.open(this.href, \'wsbco_plan_compare_{{lead.id}}\', \'width=1180,height=850,resizable=yes,scrollbars=yes\'); return false;">Compare Plans</a><a href="/leads">Contacts</a>')
backup=root/'.v36_backup'/datetime.now().strftime('%Y%m%d_%H%M%S')
backup.mkdir(parents=True,exist_ok=True)
for p in (main,detail): shutil.copy2(p,backup/p.name)
for rel in ('app/plan_compare_v36.py','app/templates/plan_compare_v36.html','app/static/css/plan_compare_v36.css'):
    dest=root/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/rel,dest)
main.write_text(main_text)
detail.write_text(detail_text)
print('V3.6 installed. Backups:',backup)
