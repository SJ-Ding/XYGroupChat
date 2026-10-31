import os
import tempfile
os.environ['DATA_DIR'] = tempfile.mkdtemp(prefix='xiaoyi-tests-')
os.environ['DEEPSEEK_API_KEY'] = ''
os.environ['DEMO_AUTOSEED'] = 'false'
os.environ['AMAP_MCP_URL'] = ''
os.environ['HOSPITAL_HEADLESS'] = '1'
import pytest
from backend.db import Base, engine, migrate

@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(engine)
    with engine.begin() as c:
        from sqlalchemy import text
        c.execute(text('DROP TABLE IF EXISTS memory_fts'))
        c.execute(text('DROP TABLE IF EXISTS schema_migrations'))
    migrate()
    yield
