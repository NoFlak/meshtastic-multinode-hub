import os
import sqlite3
import json
import tempfile
import importlib
from fastapi.testclient import TestClient


def setup_module(module):
    # create a temporary DB file for tests
    fd, tmp = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    # point DB_PATH in main module to temp file
    m = importlib.import_module('main')
    m.DB_PATH = tmp
    # initialize DB schema
    m.init_db()


def teardown_module(module):
    import importlib
    m = importlib.import_module('main')
    try:
        os.remove(m.DB_PATH)
    except Exception:
        pass


def test_positions_and_history():
    m = importlib.import_module('main')
    # insert a node with GPS and telemetry
    conn = sqlite3.connect(m.DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO nodes (node_id, long_name, gps_lat, gps_lon, gps_alt, battery, env_json) VALUES (?,?,?,?,?,?,?)",
        ('NODE123', 'Test Node', 37.0, -122.0, 10.0, 78.0, json.dumps({'sensor': 1})),
    )
    conn.commit()
    # insert historical telemetry
    cur.execute(
        "INSERT INTO node_telemetry (node_id, gps_lat, gps_lon, gps_alt, battery, env_json) VALUES (?,?,?,?,?,?)",
        ('NODE123', 37.0, -122.0, 10.0, 78.0, json.dumps({'sensor': 1})),
    )
    cur.execute(
        "INSERT INTO node_telemetry (node_id, gps_lat, gps_lon, gps_alt, battery, env_json) VALUES (?,?,?,?,?,?)",
        ('NODE123', 37.1, -122.1, 12.0, 75.0, json.dumps({'sensor': 2})),
    )
    conn.commit()
    conn.close()

    client = TestClient(m.app)
    r = client.get('/api/nodes/positions')
    assert r.status_code == 200
    payload = r.json()
    assert payload['ok'] is True
    assert len(payload['positions']) == 1

    r2 = client.get('/api/node/NODE123/telemetry/history?limit=10')
    assert r2.status_code == 200
    payload2 = r2.json()
    assert payload2['ok'] is True
    assert len(payload2['history']) >= 2