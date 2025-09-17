import importlib.util
import json
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest


def load_main_with_db(db_path):
    repo = Path(__file__).resolve().parents[1]
    main_path = repo / 'main.py'
    spec = importlib.util.spec_from_file_location('main_module', str(main_path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_commit_and_undo_cycle(tmp_path, monkeypatch):
    db_file = tmp_path / 'app.db'
    # create an empty DB by importing and running init_db
    m = load_main_with_db(db_file)
    # set DB path inside the loaded module then init DB
    m.DB_PATH = str(db_file)
    m.init_db()

    # seed nodes table with one node
    conn = sqlite3.connect(db_file)
    cur = conn.cursor()
    cur.execute("INSERT INTO nodes (node_id, long_name, role, connection) VALUES (?,?,?,?)", ('seed1', 'Seed Node', 'CLIENT', 'manual'))
    conn.commit()
    conn.close()

    # mock run_cli_command to return JSON for two devices
    def fake_run(args, device=None):
        # return JSON if device present
        return json.dumps({'nodes': {device: {'user': {'macaddr': device, 'longName': device}}}})

    monkeypatch.setattr(m, 'run_cli_command', fake_run)

    # run auto_connect_loop with two candidates and commit
    candidates = ['A1:B2:C3:D4:E5:F6', 'COM5']
    summary = m.auto_connect_loop(candidates, allocation_mode='auto', auto_commit=True)
    assert summary.get('committed') is True

    # check commit_history row exists
    conn = sqlite3.connect(db_file)
    cur = conn.cursor()
    cur.execute('SELECT id, when_ts, summary, snapshot FROM commit_history ORDER BY id DESC')
    row = cur.fetchone()
    assert row is not None
    commit_id = row[0]

    # ensure nodes updated
    cur.execute('SELECT node_id, role FROM nodes')
    nodes = cur.fetchall()
    assert any(n[1] in ('ROUTER','ROUTER_LATE') for n in nodes)
    conn.close()

    # call undo_last_commit
    res = m.undo_last_commit()
    assert res['ok'] is True

    # check nodes restored (seed1 should exist)
    conn = sqlite3.connect(db_file)
    cur = conn.cursor()
    cur.execute('SELECT node_id FROM nodes')
    rows = [r[0] for r in cur.fetchall()]
    assert 'seed1' in rows
    conn.close()
