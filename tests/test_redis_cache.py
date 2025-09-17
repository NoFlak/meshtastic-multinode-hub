import importlib
import sqlite3
import tempfile
import os
import json
from fastapi.testclient import TestClient


class FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, k):
        return self.store.get(k)

    def setex(self, k, ttl, v):
        self.store[k] = v


def setup_module(module):
    fd, tmp = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    m = importlib.import_module('main')
    m.DB_PATH = tmp
    m.init_db()


def teardown_module(module):
    import importlib
    m = importlib.import_module('main')
    try:
        os.remove(m.DB_PATH)
    except Exception:
        pass


def test_positions_in_memory_cache(monkeypatch):
    m = importlib.import_module('main')
    # ensure no redis client
    monkeypatch.setattr(m, 'REDIS_CLIENT', None)
    # insert a node
    conn = sqlite3.connect(m.DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT INTO nodes (node_id, long_name, gps_lat, gps_lon, gps_alt, battery) VALUES (?,?,?,?,?,?)",
                ('N1', 'Node1', 1.0, 2.0, 3.0, 90.0))
    conn.commit()
    conn.close()

    client = TestClient(m.app)
    r = client.get('/api/nodes/positions')
    assert r.status_code == 200
    data = r.json()
    assert data['ok'] is True
    assert len(data['positions']) == 1


def test_positions_with_fake_redis(monkeypatch):
    m = importlib.import_module('main')
    fake = FakeRedis()
    monkeypatch.setattr(m, 'REDIS_CLIENT', fake)
    # clear in-process cache so the endpoint will attempt to write to Redis
    try:
        m._POSITIONS_CACHE = {'ts': 0, 'ttl': 5.0, 'positions': []}
    except Exception:
        pass
    # populate cache via first request
    client = TestClient(m.app)
    r = client.get('/api/nodes/positions')
    assert r.status_code == 200
    # ensure fake redis has cache key
    assert 'positions_cache' in fake.store
    val = json.loads(fake.store['positions_cache'])
    assert 'positions' in val
