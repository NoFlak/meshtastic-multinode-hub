import sqlite3
import os
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, 'app.db')

if not os.path.exists(DB_PATH):
    print('DB not found at', DB_PATH)
else:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    print('Nodes:')
    cur.execute('SELECT * FROM nodes ORDER BY id ASC')
    for r in cur.fetchall():
        print(dict(r))
    print('\nMessages:')
    cur.execute('SELECT * FROM messages ORDER BY timestamp DESC')
    for r in cur.fetchall():
        print(dict(r))
    print('\nLogs:')
    cur.execute('SELECT * FROM logs ORDER BY timestamp DESC')
    for r in cur.fetchall():
        print(dict(r))
    conn.close()
