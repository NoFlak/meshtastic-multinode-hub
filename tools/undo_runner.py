"""Simple runner to undo last commit in app.db
"""
import sqlite3
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / 'app.db'

if not DB_PATH.exists():
    print('DB not found at', DB_PATH)
else:
    # import main module and call undo
    from main import undo_last_commit
    res = undo_last_commit()
    print(res)
