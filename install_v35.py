"""Run the packaged copy from the existing CRM project root, with the app stopped."""
from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
import sqlite3


def install():
    root = Path.cwd()
    payload = Path(__file__).resolve().parent / 'v35_imports'
    if not (root / 'app/main.py').is_file() or not (root / 'app/models.py').is_file():
        raise SystemExit('Run this installer from the existing WSBCO-CRM project root.')
    if not payload.is_dir():
        raise SystemExit('Use the installer packaged in WSBCO_CRM_V3_5_Data_Import.zip.')
    main = (root / 'app/main.py').read_text()
    if 'from app.models import Lead' not in (root / 'app/routers/leads.py').read_text():
        raise SystemExit('The expected CRM contact backend was not found; no files changed.')
    import_line = 'from app.imports_v35 import router as imports_v35_router'
    include_line = 'app.include_router(imports_v35_router)'
    if import_line not in main:
        anchor = 'from app.followup_v34 import router as followup_v34_router'
        if anchor not in main:
            raise SystemExit('Install on the completed v3.4 CRM. No files changed.')
        main = main.replace(anchor, anchor + '\n' + import_line, 1)
    if include_line not in main:
        anchor = 'app.include_router(followup_v34_router)'
        if anchor not in main:
            raise SystemExit('The v3.4 router was not found; no files changed.')
        main = main.replace(anchor, anchor + '\n' + include_line, 1)
    main = re.sub(r'version="[^"]+"', 'version="3.5.0"', main, count=1)
    main = re.sub(r'"phase":\s*"[^"]+"', '"phase": "3.5"', main, count=1)
    changes = {'app/main.py': main}
    for name, anchor, addition in [
        ('app/templates/layouts/sidebar.html', '<a href="/dialer">', '<a href="/imports">\n<i class="bi bi-upload"></i>\nImport Data\n</a>\n\n'),
        ('app/templates/leads.html', '<div class="hero-actions">', '\n<a href="/imports" class="btn btn-outline-primary"><i class="bi bi-upload"></i> Import Data</a>'),
    ]:
        text = (root / name).read_text()
        if 'href="/imports"' not in text:
            if anchor not in text:
                raise SystemExit(f'Expected navigation anchor missing in {name}; no files changed.')
            text = text.replace(anchor, addition + anchor if 'sidebar' in name else anchor + addition, 1)
        changes[name] = text
    requirements = (root / 'requirements.txt').read_text().rstrip() + '\n'
    for package in ['openpyxl>=3.1,<4.0', 'xlrd>=2.0,<3.0', 'google-auth[requests]>=2.38,<3.0']:
        base = package.split('>=')[0].split('[')[0]
        if not re.search(r'(?m)^' + re.escape(base) + r'(?:\[|[<>=!~]|\s|$)', requirements):
            requirements += package + '\n'
    changes['requirements.txt'] = requirements
    ignore = (root / '.gitignore').read_text() if (root / '.gitignore').exists() else ''
    if 'backups/' not in ignore.splitlines():
        ignore = ignore.rstrip() + '\nbackups/\n'
    changes['.gitignore'] = ignore
    new_files = {str(p.relative_to(payload)): p for p in payload.rglob('*') if p.is_file()}
    if 'app/imports_v35.py' not in new_files:
        raise SystemExit('The import payload is incomplete; no files changed.')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = root / 'backups' / ('v35_' + stamp)
    backup.mkdir(parents=True)
    for name in list(changes) + list(new_files):
        original = root / name
        if original.is_file():
            saved = backup / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, saved)
    db_file = root / 'data/insurance_crm.db'
    if db_file.exists():
        saved_db = backup / 'data/insurance_crm.db'
        saved_db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_file) as source, sqlite3.connect(saved_db) as destination:
            source.backup(destination)
    for name, content in changes.items():
        (root / name).write_text(content)
    for name, source in new_files.items():
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    print(f'v3.5 import update installed. Backup: {backup.relative_to(root)}')
    print('Install requirements, restart the CRM, then open /imports.')


if __name__ == '__main__':
    install()
