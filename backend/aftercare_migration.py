"""One-time removal of the superseded prognosis flow before family-aftercare starts."""
import logging
import sqlite3
import time
from datetime import datetime

from sqlalchemy import text

from .db import DATA, DB, Record

VERSION = 6


def cleanup_legacy_prognosis():
    with DB() as db:
        applied = db.execute(text('SELECT version FROM schema_migrations WHERE version=:v'), {'v': VERSION}).first()
        if applied:
            return False

        source = DATA / 'family.db'
        backup = None
        if source.exists():
            folder = DATA / 'backups'
            folder.mkdir(parents=True, exist_ok=True)
            backup = folder / f'family.pre-aftercare-{datetime.now():%Y%m%d-%H%M%S-%f}.db'
            try:
                with sqlite3.connect(source) as src, sqlite3.connect(backup) as dst:
                    src.backup(dst)
            except Exception:
                logging.getLogger(__name__).exception('旧预后迁移备份失败，跳过清理以保护数据')
                return False

        cards = []
        for row in db.query(Record).filter_by(kind='card'):
            value = row.data
            if (value.get('care') or {}).get('data', {}).get('prognosis'):
                cards.append(row)
        card_ids = {row.key for row in cards}
        for row in cards:
            db.delete(row)
        for row in db.query(Record).filter_by(kind='reminder'):
            if row.data.get('plan') in card_ids:
                db.delete(row)
        for row in db.query(Record).filter_by(kind='prognosis_pending'):
            db.delete(row)
        db.execute(text('INSERT OR IGNORE INTO schema_migrations VALUES (:v, :at)'), {'v': VERSION, 'at': time.time()})
        db.commit()
    if backup:
        logging.getLogger(__name__).info('旧预后状态已清理，备份：%s', backup)
    return True
