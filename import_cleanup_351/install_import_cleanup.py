"""Run from the CRM root, with the CRM stopped. Refuses unknown importer versions."""
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def install():
    root=Path.cwd()
    package=Path(__file__).resolve().parent
    hashes=json.loads((package/'baseline_hashes.json').read_text())
    for name,allowed in hashes.items():
        target=root/name
        if not target.is_file():
            raise SystemExit(f'Missing {name}. Run from the CRM root with V3.5 imports installed. No files changed.')
        if hashlib.sha256(target.read_bytes()).hexdigest() not in allowed:
            raise SystemExit(f'{name} differs from the saved V3.5 importer. No files changed. Supply the current file so the update can be merged safely.')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup=root/'backups'/('import_cleanup_'+stamp)
    backup.mkdir(parents=True)
    targets=list(hashes)
    for name in targets:
        dest=backup/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/name,dest)
    db=root/'data/insurance_crm.db'
    if db.exists():
        with sqlite3.connect(db) as src,sqlite3.connect(backup/'insurance_crm.db') as dst: src.backup(dst)
    try:
        for name in targets: shutil.copy2(package/name,root/name)
    except Exception:
        for name in targets: shutil.copy2(backup/name,root/name)
        raise
    print(f'Import cleanup installed. Backup: {backup}')
    print('Restart the CRM and open /imports. Start a fresh import preview.')


if __name__=='__main__': install()
