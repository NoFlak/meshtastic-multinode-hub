import importlib
import sqlite3
import tempfile
import os
from fastapi.testclient import TestClient


class BadRedis:
    def get(self, k):
        raise RuntimeError('redis get failed')

    def setex(self, k, ttl, v):
        raise RuntimeError('redis setex failed')


def setup_module(module):
    fd, tmp = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    m = importlib.import_module('main')
    m.DB_PATH = tmp
    m.init_db()
    # insert a node
    conn = sqlite3.connect(m.DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT INTO nodes (node_id, long_name, gps_lat, gps_lon, gps_alt, battery) VALUES (?,?,?,?,?,?)",
                ('NF1', 'NodeFail', 3.0, 4.0, 5.0, 50.0))
    conn.commit()
    conn.close()


def teardown_module(module):
    import importlib
    m = importlib.import_module('main')
    try:
        os.remove(m.DB_PATH)
    except Exception:
        pass


def test_redis_failure_fallback(monkeypatch):
    m = importlib.import_module('main')
    bad = BadRedis()
    # monkeypatch sync client
    monkeypatch.setattr(m, 'REDIS_CLIENT', bad)
    # ensure in-process cache is empty/fresh
    m._POSITIONS_CACHE = {'ts': 0, 'ttl': 5.0, 'positions': []}
    client = TestClient(m.app)
    r = client.get('/api/nodes/positions')
    assert r.status_code == 200
    payload = r.json()
    assert payload['ok'] is True
    assert len(payload['positions']) == 1
