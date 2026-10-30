from backend.db import DB, migrate
from backend.memory import save_memory, search, list_profile


def test_domain_search_profile_and_migration():
    with DB() as db:
        save_memory(db, 1, '妈妈喜欢医院附近的公园', manual=True, key='general')
        save_memory(db, 1, '妈妈在医院复诊', manual=True, key='medical', domain='medical',
                    metadata={'subject_ids': [2]}, profile={'record_type': 'followup', 'hospital': '市医院'})
        db.commit()
        assert [m['key'] for m in search(db, 1, '医院', domain='medical')] == ['medical']
        assert [m['key'] for m in search(db, 1, '医院', domain='general')] == ['general']
        assert len(search(db, 1, '医院')) == 2
        assert list_profile(db, 1, 2, 'medical')[0]['profile']['hospital'] == '市医院'
        assert list_profile(db, 1, 3, 'medical') == []
        assert search(db, 2, '医院') == []
    migrate()
    with DB() as db:
        assert len(search(db, 1, '医院', domain='medical')) == 1
