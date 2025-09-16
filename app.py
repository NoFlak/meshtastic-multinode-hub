from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import subprocess
import sqlite3
import json
import os
import hashlib

app = Flask(__name__)
app.secret_key = 'super-secret-key-change-me'

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')
DB_PATH = os.path.join(os.path.dirname(__file__), 'app.db')

def load_config():
    """Load configuration from file."""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    # default config with empty password hash
    return {"username": "admin", "password_hash": ""}

def save_config(config):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f)

def init_db():
    """Initialise the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # Create a table for storing node information
    cur.execute('''CREATE TABLE IF NOT EXISTS nodes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        node_id TEXT,
        long_name TEXT,
        role TEXT,
        connection TEXT,
        last_heard TEXT,
        encryption TEXT,
        snr REAL,
        rssi REAL,
        battery REAL,
        uptime REAL,
        last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    # Create a table for storing messages
    cur.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender TEXT,
        recipient TEXT,
        message TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    # Generic logs table
    cur.execute('''CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event TEXT,
        details TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()

def run_cli_command(args):
    """Run a Meshtastic CLI command and return its output."""
    try:
        result = subprocess.run(['meshtastic'] + args, capture_output=True, text=True, check=False)
        return result.stdout.strip()
    except Exception as e:
        return str(e)

@app.route('/')
def index():
    """Home page; redirect to dashboard or login."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Simple login page."""
    config = load_config()
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        if username == config.get('username') and password_hash == config.get('password_hash'):
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        error = "Invalid credentials."
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    """Logout the user."""
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    """Render the dashboard with node information."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute('SELECT * FROM nodes ORDER BY id ASC')
    nodes = cur.fetchall()
    conn.close()
    return render_template('dashboard.html', nodes=nodes)

@app.route('/messages', methods=['GET', 'POST'])
def messages():
    """Handle sending messages and listing message history."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    if request.method == 'POST':
        text = request.form.get('message', '')
        if text:
            output = run_cli_command(['--sendtext', text])
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute('INSERT INTO messages (sender, recipient, message) VALUES (?, ?, ?)',
                        ('admin', 'broadcast', text))
            cur.execute('INSERT INTO logs (event, details) VALUES (?, ?)',
                        ('send_message', f'Sent message: {text}'))
            conn.commit()
            conn.close()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute('SELECT * FROM messages ORDER BY timestamp DESC')
    msgs = cur.fetchall()
    conn.close()
    return render_template('messages.html', messages=msgs)

@app.route('/logs')
def logs():
    """View logs."""
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute('SELECT * FROM logs ORDER BY timestamp DESC')
    logs = cur.fetchall()
    conn.close()
    return render_template('logs.html', logs=logs)

@app.route('/update_nodes')
def update_nodes():
    """Fetch current node statuses via CLI and update the DB. This route returns JSON for front-end polling."""
    if not session.get('logged_in'):
        return jsonify({"error": "not_logged_in"}), 401
    output = run_cli_command(['--info'])
    return jsonify({"raw": output})

if __name__ == '__main__':
    init_db()
    if not os.path.exists(CONFIG_PATH):
        default_config = {
            "username": "admin",
            "password_hash": ""
        }
        save_config(default_config)
    app.run(host='0.0.0.0', port=5000, debug=True)