from pathlib import Path
from datetime import datetime
import shutil
root=Path.cwd()
backend=root/'app/plan_compare_v36.py'
template=root/'app/templates/plan_compare_v36.html'
if not backend.exists() or not template.exists():
    raise SystemExit('ERROR: Run from CRM project root; V3.6 catalog files missing.')
py=backend.read_text(); html=template.read_text()
backup=root/'.v36_zip_fix_backup'/datetime.now().strftime('%Y%m%d_%H%M%S_v2')
backup.mkdir(parents=True,exist_ok=True)
for f in [backend,template]: shutil.copy2(f,backup/f.name)
# Always update even if earlier hotfix inserted ZIP_COUNTIES_V36.
if 'def resolve_county_v36(' not in py:
    anchor='def catalog():\n'
    if anchor not in py: raise SystemExit('ERROR: Unexpected backend version. Original files left unchanged.')
    py=py.replace(anchor,'''ZIP_COUNTIES_V36 = {'97420': 'Coos'}

def normalize_county_v36(value):
    return re.sub(r'\\s+county\\s*$', '', (value or '').strip(), flags=re.I).strip()

def resolve_county_v36(zip_code, county):
    mapped = ZIP_COUNTIES_V36.get((zip_code or '').strip())
    return mapped or normalize_county_v36(county)

'''+anchor)
else:
    # Fix any earlier implementation that does not override a stale county.
    a=py.index('def resolve_county_v36(')
    b=py.index('\ndef ',a+4)
    py=py[:a]+'''def resolve_county_v36(zip_code, county):
    mapped = ZIP_COUNTIES_V36.get((zip_code or '').strip())
    return mapped or normalize_county_v36(county)
''' + py[b:]
# Enforce mapping at render time, even if the user hasn't clicked Find Plans.
start=py.index('    county = county.strip() or (lead.county or \'\')') if "    county = county.strip() or (lead.county or '')" in py else -1
if start!=-1:
    py=py.replace("    county = county.strip() or (lead.county or '')\n    zip_code = zip_code.strip() or (lead.zip_code or '')", "    zip_code = zip_code.strip() or (lead.zip_code or '')\n    county = resolve_county_v36(zip_code, county.strip() or (lead.county or ''))")
else:
    py=py.replace("    county = resolve_county_v36(zip_code, county.strip() or (lead.county or ''))", "    county = resolve_county_v36(zip_code, county.strip() or (lead.county or ''))")
# Force on POST too.
if "    available = {p['plan_segment_id']:p for p in county_plans(county,plan_type)}" in py:
    py=py.replace("    available = {p['plan_segment_id']:p for p in county_plans(county,plan_type)}", "    county = resolve_county_v36(zip_code, county)\n    available = {p['plan_segment_id']:p for p in county_plans(county,plan_type)}")
# Make county matching tolerate 'County' suffix.
py=py.replace("county.strip().removesuffix(' County').casefold()", "normalize_county_v36(county).casefold()")
# Template: explicit IDs on both inputs, replace older patch or vanilla.
html=html.replace('<input name="zip_code" value="{{zip_code}}"', '<input id="v36-zip" name="zip_code" value="{{zip_code}}"')
html=html.replace('<input name="county" list="oregon-counties"', '<input id="v36-county" name="county" list="oregon-counties"')
# Older patch may have injected JS; remove the block if present.
old="""const v36zip=document.getElementById('v36-zip'),v36county=document.getElementById('v36-county');
function v36ApplyZip(){if(v36zip.value.trim()==='97420')v36county.value='Coos';}
v36zip.addEventListener('input',v36ApplyZip);
v36zip.addEventListener('change',v36ApplyZip);
v36ApplyZip();
"""
html=html.replace(old,'')
js="""// V3.6 ZIP lookup patch v2: update county immediately when ZIP changes.
const v36zip=document.getElementById('v36-zip');
const v36county=document.getElementById('v36-county');
function v36ApplyZip(){
  if (!v36zip || !v36county) return;
  if (v36zip.value.trim()==='97420') {
    v36county.value='Coos';
    v36county.dispatchEvent(new Event('change', {bubbles:true}));
  }
}
if (v36zip && v36county) {
  ['input','change','blur'].forEach(evt=>v36zip.addEventListener(evt,v36ApplyZip));
  v36ApplyZip();
}
"""
html=html.replace('const boxes=[...document.querySelectorAll', js+'const boxes=[...document.querySelectorAll')
backend.write_text(py);template.write_text(html)
assert 'id="v36-zip"' in html and 'id="v36-county"' in html
assert 'county = resolve_county_v36(zip_code,' in py
print('SUCCESS: ZIP 97420 auto-selects Coos in backend and browser.')
print('Files updated:',backend,template)
print('Backup:',backup)
print('IMPORTANT: Restart CRM and hard-refresh comparison page (Ctrl+Shift+R).')
