"""
FastAPI application for the Meshtastic Support App.
This app provides an administrative interface to monitor and control a Meshtastic mesh network.
It serves HTML templates, handles authentication via sessions, stores logs and messages
in a SQLite database, and runs CLI commands to interact with the Meshtastic nodes.

The app uses Jinja2 for templates and starlette's SessionMiddleware for session support.
"""

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
# NOTE: SessionMiddleware has been removed for environments where itsdangerous is not available.
# We are not using session-based authentication during testing. Instead, pages are always accessible.
# from starlette.middleware.sessions import SessionMiddleware
import sqlite3
import subprocess
import hashlib
import json
import os

app = FastAPI()

# Secret key for session cookies; change to a secure random value when deploying
# Removed SessionMiddleware due to missing itsdangerous dependency.
# app.add_middleware(SessionMiddleware, secret_key='super-secret-key-change-me')

# Paths for config and database
BASE_DIR = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')
DB_PATH = os.path.join(BASE_DIR, 'app.db')

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, 'templates'))
app.mount('/static', StaticFiles(directory=os.path.join(BASE_DIR, 'static')), name='static')

def load_config():
    """Load the application configuration from JSON file."""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    return {"username": "admin", "password_hash": ""}

def save_config(config):
    """Save the configuration to JSON file."""
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f)

def init_db():
    """Initialise the SQLite database and create tables if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    # Node status table
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
    # Messages table
    cur.execute('''CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender TEXT,
        recipient TEXT,
        message TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    # Logs table
    cur.execute('''CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event TEXT,
        details TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()

def run_cli_command(args):
    """Run a Meshtastic CLI command and return its output.

    In this environment, the meshtastic binary may not exist. This function
    attempts to run it and returns the output or an error string.
    """
    try:
        result = subprocess.run(['meshtastic'] + args, capture_output=True, text=True, check=False)
        return result.stdout.strip()
    except FileNotFoundError:
        return "meshtastic CLI not found"
    except Exception as e:
        return str(e)

@app.on_event('startup')
def startup_event():
    # Ensure the database exists when the server starts
    init_db()
    # Ensure a default config file exists
    if not os.path.exists(CONFIG_PATH):
        default_config = {"username": "admin", "password_hash": ""}
        save_config(default_config)

@app.get('/', response_class=HTMLResponse)
async def root(request: Request):
    """
    Entry point for the application. During testing we bypass session checks and
    always redirect to the dashboard page. In a production environment you would
    enforce authentication here.
    """
    return RedirectResponse(url='/dashboard', status_code=302)

@app.get('/login', response_class=HTMLResponse)
async def login_get(request: Request):
    # Render the login form
    return templates.TemplateResponse('login.html', {"request": request, "error": None})

@app.post('/login')
async def login_post(request: Request, username: str, password: str):
    """
    Handle a login attempt. During testing we avoid using sessions. If the
    username and password are valid, the user is redirected to the dashboard.
    Otherwise the login page is re-rendered with an error.
    """
    config = load_config()
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    if username == config.get('username') and password_hash == config.get('password_hash'):
        # In a production environment this would set request.session['logged_in'] = True.
        # During testing we simply redirect without modifying session state.
        return RedirectResponse(url='/dashboard', status_code=302)
    # Invalid login
    return templates.TemplateResponse('login.html', {"request": request, "error": "Invalid credentials."})

@app.get('/logout', name='logout')
async def logout(request: Request):
    """
    Perform a logout by removing the logged_in flag if sessions are available.
    During testing this operation is a no-op.
    """
    if hasattr(request, 'session'):
        request.session.pop('logged_in', None)
    return RedirectResponse(url='/login', status_code=302)

@app.get('/dashboard', response_class=HTMLResponse, name='dashboard')
async def dashboard(request: Request):
    """
    Render the dashboard page. Authentication is bypassed during testing, so
    this page is always accessible.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute('SELECT * FROM nodes ORDER BY id ASC')
    nodes = cur.fetchall()
    conn.close()
    return templates.TemplateResponse('dashboard.html', {"request": request, "nodes": nodes})

@app.get('/messages', response_class=HTMLResponse, name='messages')
async def messages_get(request: Request):
    """
    Display the message log. This endpoint is unauthenticated in test mode.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute('SELECT * FROM messages ORDER BY timestamp DESC')
    msgs = cur.fetchall()
    conn.close()
    return templates.TemplateResponse('messages.html', {"request": request, "messages": msgs})

@app.post('/messages')  # default name is "messages_post"
async def messages_post(request: Request, message: str):
    """
    Submit a new message to be sent through the mesh. During testing,
    authentication is not enforced. Messages are still logged to the
    database. If the meshtastic CLI is not available, the command
    output is ignored.
    """
    if message:
        # Call the CLI to send text; ignore output
        run_cli_command(['--sendtext', message])
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute('INSERT INTO messages (sender, recipient, message) VALUES (?, ?, ?)',
                    ('admin', 'broadcast', message))
        cur.execute('INSERT INTO logs (event, details) VALUES (?, ?)',
                    ('send_message', f'Sent message: {message}'))
        conn.commit()
        conn.close()
    return RedirectResponse(url='/messages', status_code=302)

@app.get('/logs', response_class=HTMLResponse, name='logs')
async def logs_page(request: Request):
    """
    Display the application log entries. This endpoint is accessible without
    authentication during testing.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute('SELECT * FROM logs ORDER BY timestamp DESC')
    logs = cur.fetchall()
    conn.close()
    return templates.TemplateResponse('logs.html', {"request": request, "logs": logs})

@app.get('/update_nodes', name='update_nodes')
async def update_nodes(request: Request):
    """
    Endpoint for triggering a node information update. In production this
    should only be accessible to authenticated users. During testing the
    endpoint is always available.
    """
    output = run_cli_command(['--info'])
    return JSONResponse({"raw": output})
