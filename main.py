"""
FastAPI application for the Meshtastic Support App.
This app provides an administrative interface to monitor and control a Meshtastic mesh network.
It serves HTML templates, handles authentication via sessions, stores logs and messages
in a SQLite database, and runs CLI commands to interact with the Meshtastic nodes.

The app uses Jinja2 for templates and starlette's SessionMiddleware for session support.
"""

from fastapi import FastAPI, Request
from contextlib import asynccontextmanager
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
# NOTE: SessionMiddleware has been removed for environments where itsdangerous is not available.
# We are not using session-based authentication during testing. Instead, pages are always accessible.
# from starlette.middleware.sessions import SessionMiddleware
import sqlite3
import subprocess
import sys
import json
import hashlib
import json
import os

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager replacing the deprecated @app.on_event handlers.

    This runs startup logic before the app is ready and can run cleanup logic
    after shutdown. See FastAPI Lifespan Events:
    https://fastapi.tiangolo.com/advanced/events/
    """
    # startup
    init_db()
    if not os.path.exists(CONFIG_PATH):
        default_config = {"username": "admin", "password_hash": ""}
        save_config(default_config)
    yield
    # shutdown: currently nothing to clean up


app = FastAPI(lifespan=lifespan)

# Secret key for session cookies; change to a secure random value when deploying
# Removed SessionMiddleware due to missing itsdangerous dependency.
# app.add_middleware(SessionMiddleware, secret_key='super-secret-key-change-me')

# NOTE: FastAPI's `@app.on_event('startup')` decorator is deprecated. This
# application uses a lifespan context manager (see `lifespan` below) and passes
# it to `FastAPI(lifespan=...)` per FastAPI docs:
# https://fastapi.tiangolo.com/advanced/events/

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

def run_cli_command(args, device: str = None):
    """Run a Meshtastic CLI command and return its output.

    In this environment, the meshtastic binary may not exist. This function
    attempts to run it and returns the output or an error string.
    """
    # First try the 'meshtastic' executable (if on PATH). If that isn't
    # available (FileNotFoundError), attempt to run it as a module via the
    # current Python interpreter: `python -m meshtastic ...`. This makes it
    # work even when the venv isn't activated but the package is installed in
    # the venv used to run this script.
    cmd = ['meshtastic'] + args
    if device:
        cmd += ['--device', device]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return result.stdout.strip()
    except FileNotFoundError:
        try:
            cmd2 = [sys.executable, '-m', 'meshtastic'] + args
            if device:
                cmd2 += ['--device', device]
            result = subprocess.run(cmd2, capture_output=True, text=True, check=False)
            return result.stdout.strip()
        except FileNotFoundError:
            return "meshtastic CLI not found"
        except Exception as e:
            return str(e)
    except Exception as e:
        return str(e)


def scan_com_ports():
    """Return a list of available serial/COM ports."""
    try:
        import serial.tools.list_ports as list_ports
    except Exception:
        return {'error': 'pyserial not available'}
    ports = []
    for p in list_ports.comports():
        ports.append({'device': p.device, 'description': p.description, 'hwid': p.hwid})
    return ports


async def scan_ble_devices(timeout=5.0):
    """Asynchronously scan for BLE devices using bleak. Returns list of (address, name)."""
    try:
        from bleak import BleakScanner
    except Exception:
        return {'error': 'bleak not available'}
    devices = []
    try:
        scanner = BleakScanner()
        found = await scanner.discover(timeout=timeout)
        for d in found:
            devices.append({'address': d.address, 'name': d.name, 'rssi': d.rssi})
    except Exception as e:
        return {'error': str(e)}
    return devices


def parse_meshtastic_info(raw):
    """Attempt to parse JSON-like output from meshtastic --info and return node summaries."""
    try:
        data = json.loads(raw)
    except Exception:
        # Some meshtastic outputs may be plain text or not strictly JSON; return raw
        return {'raw': raw}
    # The device list is usually under 'nodes' or similar top-level key
    nodes = {}
    if isinstance(data, dict):
        # Try common keys
        for key in ('nodes', 'devices', 'peers'):
            if key in data:
                nodes = data[key]
                break
        if not nodes:
            # fallback: return the whole dict
            return {'info': data}
    return {'nodes': nodes}


def summarize_meshtastic_nodes(parsed):
    """Produce a concise list of node summaries from parsed meshtastic info."""
    nodes = parsed.get('nodes') if isinstance(parsed, dict) else None
    summaries = []
    if not nodes:
        return summaries
    for nid, info in nodes.items():
        try:
            user = info.get('user', {})
            summary = {
                'id': nid,
                'longName': user.get('longName'),
                'shortName': user.get('shortName'),
                'macaddr': user.get('macaddr') or user.get('mac'),
                'hwModel': user.get('hwModel') or info.get('deviceMetrics', {}).get('hwModel'),
                'snr': info.get('snr'),
                'hopsAway': info.get('hopsAway'),
                'lastHeard': info.get('lastHeard'),
            }
            summaries.append(summary)
        except Exception:
            continue
    return summaries


def add_node_manual(node_type: str, node_id: str, long_name: str = None, short_name: str = None, hw_model: str = None, role: str = None):
    """Insert a node into the local nodes table for manual tracking.

    node_type: 'ble'|'com'|'wifi' (stored in connection column)
    node_id: MAC address or COM port
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        # avoid duplicate node_id entries
        cur.execute('SELECT id FROM nodes WHERE node_id = ?', (node_id,))
        if cur.fetchone():
            return 'duplicate'
        cur.execute('INSERT INTO nodes (node_id, long_name, role, connection, last_heard, encryption, snr, rssi, battery, uptime) VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (node_id, long_name or '', role or '', node_type, None, '', None, None, None, None))
        cur.execute('INSERT INTO logs (event, details) VALUES (?, ?)', ('add_node_manual', f'Added node {node_id} via {node_type}'))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        return str(e)
    finally:
        conn.close()


def remove_node(node_id: str):
    """Remove a node by node_id from the local DB and log the removal."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute('DELETE FROM nodes WHERE node_id = ?', (node_id,))
        cur.execute('INSERT INTO logs (event, details) VALUES (?, ?)', ('remove_node_manual', f'Removed node {node_id}'))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        return str(e)
    finally:
        conn.close()


def auto_connect_loop(device_candidates: list, allocation_mode: str = 'auto', main_id: str = None, auto_commit: bool = False):
    """Try to auto-connect to possible devices and, if requested, set roles.

    - device_candidates: list of device identifiers (COM ports or BLE addresses)
    - allocation_mode: 'auto' or 'manual' — in 'auto' mode the function will pick the best candidate for main router based on availability; in 'manual', `main_id` must be provided and others will be router_late.
    - auto_commit: bool — if True, commit role changes to DB; otherwise run in dry-run mode.

    This function is conservative: it only calls `meshtastic --info` against candidates to determine availability and node info. It will not change device configurations on the hardware.
    Returns a dict summarizing attempted connections and proposed allocations.
    """
    summary = {'attempts': [], 'allocations': {}}
    # For each candidate, try to run meshtastic --info
    for dev in device_candidates:
        out = run_cli_command(['--info'], device=dev)
        ok = bool(out and len(out.strip())>0)
        summary['attempts'].append({'device': dev, 'ok': ok, 'raw': out[:1000] if isinstance(out, str) else out})
    # Allocation
    available = [a['device'] for a in summary['attempts'] if a['ok']]
    if allocation_mode == 'manual':
        if not main_id:
            summary['error'] = 'manual mode selected but no main_id provided'
            return summary
        main = main_id
        routers = [d for d in available if d != main]
    else:
        # auto: pick the first available as main
        main = available[0] if available else None
        routers = [d for d in available[1:]] if len(available)>1 else []
    summary['allocations']['main'] = main
    summary['allocations']['routers'] = routers

    if auto_commit and main:
        # Write to DB: set main role, others router_late
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        try:
            # Upsert nodes for candidates and set roles
            for dev in available:
                # ensure node exists
                cur.execute('SELECT id FROM nodes WHERE node_id = ?', (dev,))
                if not cur.fetchone():
                    cur.execute('INSERT INTO nodes (node_id, long_name, role, connection) VALUES (?,?,?,?)', (dev, dev, 'ROUTER_LATE', 'auto'))
            # set roles
            if main:
                cur.execute('UPDATE nodes SET role = ? WHERE node_id = ?', ('ROUTER', main))
            for r in routers:
                cur.execute('UPDATE nodes SET role = ? WHERE node_id = ?', ('ROUTER_LATE', r))
            cur.execute('INSERT INTO logs (event, details) VALUES (?, ?)', ('auto_connect', f'Allocated main={main} routers={routers}'))
            conn.commit()
            summary['committed'] = True
        except Exception as e:
            conn.rollback()
            summary['commit_error'] = str(e)
        finally:
            conn.close()
    else:
        summary['committed'] = False

    return summary


async def find_nodes(device: str = None):
    """Run BLE scan, list COM ports, and query meshtastic --info, then try to correlate devices.

    Returns a dict with keys: 'com_ports', 'ble_devices', 'meshtastic_nodes', 'matches'
    where 'matches' attempts to link BLE MAC addresses to meshtastic node entries by MAC.
    """
    result = {}
    # COM
    result['com_ports'] = scan_com_ports()
    # BLE
    ble = await scan_ble_devices()
    result['ble_devices'] = ble
    # meshtastic
    raw = run_cli_command(['--info'], device=device)
    parsed = parse_meshtastic_info(raw)
    result['meshtastic_raw'] = parsed
    # Try to extract node MACs from meshtastic parsed data
    nodes = {}
    if isinstance(parsed, dict) and 'nodes' in parsed:
        nodes = parsed['nodes']
    result['meshtastic_nodes'] = nodes
    # Correlate BLE addresses to meshtastic nodes by matching MAC / macaddr fields
    matches = []
    try:
        # Normalize meshtastic MACs to upper-case no-separators for tolerant matching
        node_mac_map = {}
        for nid, info in nodes.items():
            user = info.get('user', {}) if isinstance(info, dict) else {}
            mac = user.get('macaddr') or user.get('mac')
            if mac:
                node_mac_map[mac.upper().replace(':','')] = {'id': nid, 'info': info}
        # For each BLE device, try to match
        if isinstance(ble, list):
            for d in ble:
                addr = d.get('address','').upper().replace(':','')
                if addr in node_mac_map:
                    matches.append({'ble': d, 'node': node_mac_map[addr]})
    except Exception:
        pass
    result['matches'] = matches
    return result

# NOTE: startup logic moved into the `lifespan` context manager above. The
# previous `@app.on_event('startup')` decorator was deprecated and replaced
# with the `lifespan` pattern.

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

    if __name__ == '__main__':
        # Simple CLI for administrative/testing tasks when running the file directly.
        import argparse

        epilog = (
            "Examples:\n"
            "  python main.py --list-db\n"
            "      Print the contents of the messages and nodes tables.\n\n"
            "  python main.py --info\n"
            "      Run the meshtastic CLI with '--info' (uses the local 'meshtastic' binary).\n\n"
            "  # Connecting to nodes\n"
            "  # For a Wi-Fi connected node you usually don't need extra flags; the CLI will discover it.\n"
            "  # For BLE nodes you may need to run the meshtastic CLI with --device <address> or ensure Bluetooth is enabled.\n"
        )

        parser = argparse.ArgumentParser(
            description='Meshtastic Support App utility CLI',
            epilog=epilog,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        parser.add_argument('--list-db', action='store_true', help='Print nodes, messages, and logs from the local SQLite DB')
        parser.add_argument('--info', action='store_true', help="Run 'meshtastic --info' and print raw output")
        parser.add_argument('--send', type=str, metavar='MESSAGE', help='Send a message via meshtastic CLI (calls --sendtext)')
        parser.add_argument('--scan-ble', action='store_true', help='Scan for BLE devices (requires bleak)')
        parser.add_argument('--scan-com', action='store_true', help='List available serial/COM ports')
        parser.add_argument('--find-nodes', action='store_true', help='Run BLE, COM, and meshtastic scans and print a combined summary')
        parser.add_argument('--meshtastic-device', type=str, help='Device identifier to pass to meshtastic CLI (e.g. COM4 or BLE address)')
        parser.add_argument('--add-node', action='store_true', help='Manually add a node to the local DB')
        parser.add_argument('--add-type', type=str, choices=['ble','com','wifi'], help='Connection type for manual add (ble/com/wifi)')
        parser.add_argument('--add-id', type=str, help='Node identifier (MAC address or COM port)')
        parser.add_argument('--add-longname', type=str, help='Long name for the node')
        parser.add_argument('--add-shortname', type=str, help='Short name for the node')
        parser.add_argument('--add-hwmodel', type=str, help='Hardware model string')
        parser.add_argument('--add-role', type=str, help='Role (ROUTER, CLIENT, etc)')
        parser.add_argument('--auto-connect', action='store_true', help='Attempt auto-connect loop through discovered devices')
        parser.add_argument('--allocation-mode', choices=['auto','manual'], default='auto', help='Allocation mode for auto-connect (auto or manual)')
        parser.add_argument('--main-id', type=str, help='In manual allocation mode, the device id to set as main')
        parser.add_argument('--auto-commit', action='store_true', help='If set, commit allocation role changes to DB during auto-connect')
        parser.add_argument('--remove-node', action='store_true', help='Remove a node from the DB')
        parser.add_argument('--remove-id', type=str, help='Node id to remove (node_id)')
        args = parser.parse_args()

        if args.list_db:
            print('Nodes:')
            try:
                conn = sqlite3.connect(DB_PATH)
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute('SELECT * FROM nodes ORDER BY id ASC')
                rows = cur.fetchall()
                for r in rows:
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
            except Exception as e:
                print('Error reading DB:', e)

        if args.info:
            print('Running meshtastic --info...')
            out = run_cli_command(['--info'])
            print(out)

        if args.scan_com:
            print('Scanning serial/COM ports...')
            ports = scan_com_ports()
            print(ports)

        if args.scan_ble:
            print('Scanning BLE devices (this may take a few seconds)...')
            try:
                import asyncio
                devices = asyncio.run(scan_ble_devices())
                print(devices)
            except Exception as e:
                print('BLE scan failed:', e)

        if args.find_nodes:
            print('Running combined node discovery and correlation:')
            try:
                import asyncio
                summary = None
                try:
                    summary = asyncio.run(find_nodes(device=args.meshtastic_device))
                except RuntimeError:
                    # If there's already a running loop (unlikely here), create a new loop
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    summary = loop.run_until_complete(find_nodes(device=args.meshtastic_device))
                print(json.dumps(summary, indent=2))
            except Exception as e:
                print('find-nodes failed:', e)
            # fall through

        if args.auto_connect:
            # Build candidate list from COM and BLE scans
            candidates = []
            candidates += [p['device'] for p in scan_com_ports()]
            try:
                import asyncio
                ble = asyncio.run(scan_ble_devices())
                if isinstance(ble, list):
                    candidates += [d['address'] for d in ble if d.get('address')]
            except Exception:
                pass
            print('Running auto-connect across candidates:', candidates)
            summary = auto_connect_loop(candidates, allocation_mode=args.allocation_mode, main_id=args.main_id, auto_commit=args.auto_commit)
            print(json.dumps(summary, indent=2))

        if args.remove_node:
            if not args.remove_id:
                print('Missing --remove-id for --remove-node')
            else:
                res = remove_node(args.remove_id)
                if res is True:
                    print('Node removed')
                else:
                    print('Failed to remove node:', res)

        if args.add_node:
            if not args.add_type or not args.add_id:
                print('Missing --add-type or --add-id for --add-node')
            else:
                res = add_node_manual(node_type=args.add_type, node_id=args.add_id, long_name=args.add_longname, short_name=args.add_shortname, hw_model=args.add_hwmodel, role=args.add_role)
                if res is True:
                    print('Node added successfully')
                else:
                    print('Failed to add node:', res)

        if args.send:
            print(f"Sending message: {args.send}")
            out = run_cli_command(['--sendtext', args.send])
            print('CLI output:', out)
