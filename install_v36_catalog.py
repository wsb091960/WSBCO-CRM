from pathlib import Path
import shutil
from datetime import datetime
root=Path(__file__).resolve().parent
source=root/'v36_plan_comparison'/'app'
main=root/'app/main.py'
detail=root/'app/templates/lead_detail.html'
if not main.exists() or not detail.exists(): raise SystemExit('Run installer from the CRM repository root')
a=main.read_text();b=detail.read_text()
if 'plan_compare_v36_router' not in a:
    anchor='from app.imports_v35 import router as imports_v35_router'
    if anchor not in a: raise SystemExit('V3.5 main.py expected; no changes made')
    a=a.replace(anchor,anchor+'\nfrom app.plan_compare_v36 import router as plan_compare_v36_router')
    a=a.replace('app.include_router(imports_v35_router)','app.include_router(imports_v35_router)\napp.include_router(plan_compare_v36_router)')
if 'Compare Plans' not in b:
    anchor='<div class="actions"><a href="/leads">Contacts</a>'
    if anchor not in b: raise SystemExit('Contact Console template expected; no changes made')
    b=b.replace(anchor,'<div class="actions"><a href="/leads/{{lead.id}}/compare" onclick="window.open(this.href, \'wsbco_plan_compare_{{lead.id}}\', \'width=1180,height=850,resizable=yes,scrollbars=yes\'); return false;">Compare Plans</a><a href="/leads">Contacts</a>')
a=a.replace('version="3.5.0"','version="3.6.0"').replace('"phase": "3.5"','"phase": "3.6"')
backup=root/'.v36_catalog_backup'/datetime.now().strftime('%Y%m%d_%H%M%S')
backup.mkdir(parents=True,exist_ok=True)
for p in (main,detail,root/'app/plan_compare_v36.py',root/'app/templates/plan_compare_v36.html'):
    if p.exists(): shutil.copy2(p,backup/p.name)
for rel in ('plan_compare_v36.py','templates/plan_compare_v36.html','data/oregon_2027_mapd.csv'):
    dst=root/'app'/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/rel,dst)
main.write_text(a);detail.write_text(b)
print('Installed 2027 Oregon MAPD automatic county catalog. Backup:',backup)
