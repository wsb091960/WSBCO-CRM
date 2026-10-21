from pathlib import Path
import shutil
from datetime import datetime
root=Path.cwd()
backend=root/'app/plan_compare_v36.py'
template=root/'app/templates/plan_compare_v36.html'
if not backend.exists() or not template.exists():
    raise SystemExit('Run from /workspaces/WSBCO-CRM after installing the V3.6 catalog.')
py=backend.read_text()
html=template.read_text()
if 'ZIP_COUNTIES_V36' in py:
    print('ZIP lookup fix already installed; no changes needed.')
    raise SystemExit(0)
anchor='def catalog():\n'
if anchor not in py: raise SystemExit('Unexpected backend version; no files changed.')
py=py.replace(anchor,'''# Verified local ZIP mapping. Unknown ZIPs require explicit county confirmation;
# never infer service-area eligibility from ZIP alone.
ZIP_COUNTIES_V36 = {'97420': 'Coos'}

def normalize_county_v36(value):
    return re.sub(r'\\s+county\\s*$', '', (value or '').strip(), flags=re.I).strip()

def resolve_county_v36(zip_code, county):
    county = normalize_county_v36(county)
    mapped = ZIP_COUNTIES_V36.get((zip_code or '').strip())
    # For verified ZIPs, correct a missing/stale CRM county. For other ZIPs,
    # preserve user-supplied county and require confirmation.
    if mapped and (not county or county.casefold() != mapped.casefold()):
        return mapped
    return county

'''+anchor)
py=py.replace("p['county'].casefold() == county.strip().removesuffix(' County').casefold()", "p['county'].casefold() == normalize_county_v36(county).casefold()")
py=py.replace("county = county.strip() or (lead.county or '')\n    zip_code = zip_code.strip() or (lead.zip_code or '')", "zip_code = zip_code.strip() or (lead.zip_code or '')\n    county = resolve_county_v36(zip_code, county.strip() or (lead.county or ''))")
py=py.replace("available = {p['plan_segment_id']:p for p in county_plans(county,plan_type)}", "county = resolve_county_v36(zip_code, county)\n    available = {p['plan_segment_id']:p for p in county_plans(county,plan_type)}")
old='Confirm county before comparing; this catalog is county-based, not a ZIP-to-county lookup.'
if old not in html: raise SystemExit('Unexpected comparison template; no files changed.')
html=html.replace(old, 'ZIP 97420 automatically resolves to Coos County. For other ZIPs, confirm or enter the county manually. County-level listing is not ZIP-level eligibility verification.')
html=html.replace('<input name="zip_code" value="{{zip_code}}"', '<input id="v36-zip" name="zip_code" value="{{zip_code}}"')
html=html.replace('<input name="county" list="oregon-counties"', '<input id="v36-county" name="county" list="oregon-counties"')
html=html.replace('const boxes=[...document.querySelectorAll', '''const v36zip=document.getElementById('v36-zip'),v36county=document.getElementById('v36-county');
function v36ApplyZip(){if(v36zip.value.trim()==='97420')v36county.value='Coos';}
v36zip.addEventListener('input',v36ApplyZip);
v36zip.addEventListener('change',v36ApplyZip);
v36ApplyZip();
const boxes=[...document.querySelectorAll''')
backup=root/'.v36_zip_fix_backup'/datetime.now().strftime('%Y%m%d_%H%M%S')
backup.mkdir(parents=True,exist_ok=True)
shutil.copy2(backend,backup/backend.name)
shutil.copy2(template,backup/template.name)
backend.write_text(py)
template.write_text(html)
print('ZIP 97420 -> Coos lookup installed. Backup:',backup)
print('Restart the CRM, then enter ZIP 97420 and click Find plans.')
