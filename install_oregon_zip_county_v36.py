from pathlib import Path
import csv, io, json, re, urllib.request, shutil
from collections import defaultdict
from datetime import datetime
root=Path.cwd(); py=root/'app/plan_compare_v36.py'; html=root/'app/templates/plan_compare_v36.html'; data=root/'app/data/oregon_zip_counties_v36.json'
if not py.exists() or not html.exists(): raise SystemExit('Run in /workspaces/WSBCO-CRM with V3.6 installed')
url='https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_county20_natl.txt'
print('Downloading Census ZIP-area/county data...')
with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'WSBCO CRM county loader'}),timeout=90) as r: raw=r.read().decode('utf-8-sig')
reader=csv.DictReader(io.StringIO(raw),delimiter='|'); fields=reader.fieldnames
z=next(c for c in fields if 'GEOID_ZCTA5_20' in c); f=next(c for c in fields if 'GEOID_COUNTY_20' in c); n=next(c for c in fields if 'NAMELSAD_COUNTY_20' in c)
lookup=defaultdict(set)
for row in reader:
    if row[f].startswith('41'): lookup[row[z]].add(re.sub(r' County$','',row[n]))
lookup={k:sorted(v) for k,v in lookup.items()}
assert len(lookup)>250 and 'Coos' in lookup.get('97420',[]) and 'Marion' in lookup.get('97317',[]), 'Census data validation failed'
source=py.read_text(); template=html.read_text()
if 'OREGON_ZCTA_COUNTIES_V36' in source: raise SystemExit('Already installed')
pat=r'(?m)^def resolve_county_v36\(zip_code, county\):\n(?:[ \t]+[^\n]*\n|\n)+'
m=re.search(pat,source)
if not m: raise SystemExit('Lookup function not found; no files changed')
new='''def resolve_county_v36(zip_code, county):
    options = OREGON_ZCTA_COUNTIES_V36.get((zip_code or '').strip()[:5], [])
    given = normalize_county_v36(county)
    if len(options) == 1: return options[0]
    if options: return given if given in options else ''
    return given

'''
source=source[:m.start()]+new+source[m.end():]
source='''import json as _zipjson
from pathlib import Path as _ZipPath
OREGON_ZCTA_COUNTIES_V36 = _zipjson.loads((_ZipPath(__file__).resolve().parent / 'data' / 'oregon_zip_counties_v36.json').read_text())
'''+source
script='''<script id="oregon-zip-county-v36">(function(){const map=__MAP__;function init(){const z=document.querySelector('[name="zip_code"]'),c=document.querySelector('[name="county"]');if(!z||!c)return;const msg=document.createElement('small');c.after(msg);function update(){const choices=map[z.value.trim().slice(0,5)]||[];if(c.tagName==='SELECT'){const opts=[...c.options];if(choices.length===1){const found=opts.find(o=>o.value.replace(/ County$/i,'').toLowerCase()===choices[0].toLowerCase());c.value=found?found.value:'';}else c.value='';}else c.value=choices.length===1?choices[0]:'';msg.textContent=choices.length>1?'ZIP crosses counties: '+choices.join(', ')+'. Confirm county.':choices.length===0?'ZIP not in Census reference; enter county manually.':'County suggested from Census geography; verify client address.';c.dispatchEvent(new Event('change',{bubbles:true}));}z.addEventListener('input',update);update();}if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();})();</script>'''.replace('__MAP__',json.dumps(lookup,separators=(',',':')))
if '{% endblock %}' in template:
    i=template.rfind('{% endblock %}');template=template[:i]+script+'\n'+template[i:]
else: template+='\n'+script
backup=root/'backups'/('zipcounty_'+datetime.now().strftime('%Y%m%d_%H%M%S'));backup.mkdir(parents=True,exist_ok=True)
shutil.copy2(py,backup/py.name);shutil.copy2(html,backup/html.name)
data.parent.mkdir(parents=True,exist_ok=True);data.write_text(json.dumps(lookup,indent=2))
py.write_text(source);html.write_text(template)
print('Installed',len(lookup),'Oregon Census ZIP areas;',sum(len(v)>1 for v in lookup.values()),'cross multiple counties')
print('Backup:',backup,'\nRestart CRM and hard refresh browser.')
