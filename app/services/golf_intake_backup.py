"""Preserve an existing SQLite CRM before the additive golf intake schema is created."""
from datetime import datetime, timezone
from pathlib import Path
import sqlite3


def backup_before_golf_intake(engine):
    if engine.dialect.name != "sqlite" or not engine.url.database:
        return
    source = Path(engine.url.database)
    if not source.is_file() or source.stat().st_size == 0:
        return
    with sqlite3.connect(source) as connection:
        has_schema = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='golf_inquiry_receipts'"
        ).fetchone()
        if has_schema:
            return
        destination = source.parent / "backups"
        destination.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        with sqlite3.connect(destination / f"before_golf_intake_{stamp}.db") as backup:
            connection.backup(backup)
