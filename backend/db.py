import hashlib
import json
import os
import secrets
import time
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, String, Text, Float, UniqueConstraint, event, text
from sqlalchemy.orm import declarative_base, sessionmaker
from .persona import DEFAULT_AGENT_NAME, DEFAULT_PROMPT

load_dotenv()
DATA = Path(os.getenv('DATA_DIR', 'data')).resolve()
DATA.mkdir(parents=True, exist_ok=True)
(DATA / 'uploads').mkdir(exist_ok=True)
engine = create_engine('sqlite:///' + str(DATA / 'family.db'), connect_args={'check_same_thread': False})

@event.listens_for(engine, 'connect')
def configure(connection, _):
    connection.execute('PRAGMA journal_mode=WAL')
    connection.execute('PRAGMA busy_timeout=10000')

DB = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    password = Column(String, nullable=False)  # Legacy column retained for existing databases; URL mode does not read it.

class Session(Base):
    __tablename__ = 'sessions'
    token = Column(String, primary_key=True)
    user_id = Column(Integer, nullable=False)
    expires = Column(Float, nullable=False)

class Member(Base):
    __tablename__ = 'members'
    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, nullable=False)
    user_id = Column(Integer, nullable=False)
    __table_args__ = (UniqueConstraint('group_id', 'user_id'),)

class Message(Base):
    __tablename__ = 'messages'
    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, index=True, nullable=False)
    user_id = Column(Integer, nullable=False)
    client_id = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    attachments = Column(Text, default='[]')
    created = Column(Float, default=time.time)
    __table_args__ = (UniqueConstraint('group_id', 'user_id', 'client_id'),)

class Record(Base):
    """Versioned application entities: group, memory, task, demand, job, tool, log, summary, upload."""
    __tablename__ = 'records'
    id = Column(Integer, primary_key=True)
    kind = Column(String, index=True, nullable=False)
    group_id = Column(Integer, index=True, nullable=False)
    key = Column(String, nullable=False)
    payload = Column(Text, default='{}')
    updated = Column(Float, default=time.time)
    __table_args__ = (UniqueConstraint('kind', 'group_id', 'key'),)

    @property
    def data(self):
        return json.loads(self.payload)

    def set(self, data):
        from sqlalchemy import inspect, update
        from sqlalchemy.orm import object_session
        from sqlalchemy.orm.attributes import set_committed_value
        old_payload = self.payload
        if self.kind == 'memory':
            previous = json.loads(old_payload) if old_payload else {}
            data = {**data, 'version': previous.get('version', 1) + 1 if old_payload else 1}
        payload = json.dumps(data, ensure_ascii=False)
        now = time.time()
        # Compare the persisted representation, including legacy rows without a version.
        if self.kind == 'memory' and inspect(self).persistent:
            session = object_session(self)
            with session.no_autoflush:
                changed = session.execute(update(Record).where(Record.id == self.id, Record.payload == old_payload)
                    .values(payload=payload, updated=now).execution_options(synchronize_session=False)).rowcount
            if changed != 1:
                raise ValueError('记忆已被其他任务更新，请重新读取后重试')
            set_committed_value(self, 'payload', payload)
            set_committed_value(self, 'updated', now)
        else:
            self.payload = payload
            self.updated = now

def put(db, kind, gid, key, data):
    r = db.query(Record).filter_by(kind=kind, group_id=gid, key=str(key)).first()
    if not r:
        r = Record(kind=kind, group_id=gid, key=str(key))
        db.add(r)
    r.set(data)
    db.flush()
    return r

def get(db, kind, gid, key):
    return db.query(Record).filter_by(kind=kind, group_id=gid, key=str(key)).first()

def records(db, kind, gid):
    return db.query(Record).filter_by(kind=kind, group_id=gid).order_by(Record.id).all()

def password_hash(value, salt=None):
    salt = salt or secrets.token_hex(16)
    return salt + ':' + hashlib.scrypt(value.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()

def password_ok(value, stored):
    return secrets.compare_digest(password_hash(value, stored.split(':')[0]), stored)

def migrate():
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied REAL)'))
        conn.execute(text('CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(record_id UNINDEXED, group_id UNINDEXED, tokens)'))
        conn.execute(text('INSERT OR IGNORE INTO schema_migrations VALUES (1, :now)'), {'now': time.time()})
        # Version 2 adds harness record kinds and memory metadata. The payload
        # schema is additive; legacy memories retain group/long defaults.
        conn.execute(text('INSERT OR IGNORE INTO schema_migrations VALUES (2, :now)'), {'now': time.time()})
    with DB() as db:
        if not get(db, 'group', 1, 'settings'):
            put(db, 'group', 1, 'settings', {'name': '我们一家', 'agent_name': DEFAULT_AGENT_NAME, 'prompt': DEFAULT_PROMPT, 'active': True, 'wait_seconds': 30, 'version': 1,
                'memory_auto': True, 'memory_short_days': 7, 'memory_review_seconds': 21600})
        for login, name in [('dad', '爸爸'), ('mom', '妈妈'), ('child', '小宇')]:
            user = db.query(User).filter_by(username=login).first()
            if not user:
                user = User(username=login, name=name, password='unused-in-url-mode')
                db.add(user)
                db.flush()
            if not db.query(Member).filter_by(group_id=1, user_id=user.id).first():
                db.add(Member(group_id=1, user_id=user.id))
        db.commit()
    with DB() as db:
        if not db.execute(text('SELECT version FROM schema_migrations WHERE version=3')).first():
            from .repairs import repair_legacy_harness
            repair_legacy_harness(db)
            db.execute(text('INSERT INTO schema_migrations VALUES (3, :now)'), {'now': time.time()})
            db.commit()
    with DB() as db:
        if not db.execute(text('SELECT version FROM schema_migrations WHERE version=4')).first():
            from .persona import upgrade_settings
            upgrade_settings(db)
            db.execute(text('INSERT INTO schema_migrations VALUES (4, :now)'), {'now': time.time()})
            db.commit()
