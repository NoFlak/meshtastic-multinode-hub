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
from datetime import datetime
import subprocess
import sys
import json
import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import time as _time
try:
    # prefer redis.asyncio when available
    import redis.asyncio as _redis_async
    REDIS_ASYNC_AVAILABLE = True
except Exception:
    _redis_async = None
    REDIS_ASYNC_AVAILABLE = False

try:
    import redis as _redis_sync
    REDIS_SYNC_AVAILABLE = True
except Exception:
    _redis_sync = None
    REDIS_SYNC_AVAILABLE = False

# Global redis clients (optional)
REDIS_CLIENT = None         # existing sync client compatibility
REDIS_ASYNC_CLIENT = None   # async client when available
REDIS_URL = os.environ.get('REDIS_URL')
if REDIS_URL:
    try:
        if REDIS_ASYNC_AVAILABLE:
            try:
                REDIS_ASYNC_CLIENT = _redis_async.from_url(REDIS_URL, decode_responses=True)
            except Exception:
                REDIS_ASYNC_CLIENT = None
        if REDIS_SYNC_AVAILABLE:
            try:
                REDIS_CLIENT = _redis_sync.from_url(REDIS_URL, decode_responses=True)
            except Exception:
                REDIS_CLIENT = None
    except Exception:
        REDIS_CLIENT = None
        REDIS_ASYNC_CLIENT = None

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
    # commit history: store snapshots for undo
    cur.execute('''
        CREATE TABLE IF NOT EXISTS commit_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            when_ts TEXT,
            summary TEXT,
            snapshot TEXT
        )
    ''')
    # Historical telemetry table for nodes
    cur.execute('''CREATE TABLE IF NOT EXISTS node_telemetry (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        node_id TEXT,
        ts DATETIME DEFAULT CURRENT_TIMESTAMP,
        gps_lat REAL,
        gps_lon REAL,
        gps_alt REAL,
        battery REAL,
        env_json TEXT
    )''')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_node_telemetry_node_ts ON node_telemetry (node_id, ts)')
    conn.commit()
    conn.close()
    # Ensure telemetry columns exist (safe to call repeatedly)
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        # Add gps_lat, gps_lon, gps_alt, env_json if they don't exist
        cols = [c[1] for c in cur.execute("PRAGMA table_info(nodes)")]
        existing = [c for c in cols]
        if 'gps_lat' not in existing:
            cur.execute('ALTER TABLE nodes ADD COLUMN gps_lat REAL')
        if 'gps_lon' not in existing:
            cur.execute('ALTER TABLE nodes ADD COLUMN gps_lon REAL')
        if 'gps_alt' not in existing:
            cur.execute('ALTER TABLE nodes ADD COLUMN gps_alt REAL')
        if 'env_json' not in existing:
            cur.execute('ALTER TABLE nodes ADD COLUMN env_json TEXT')
        conn.commit()
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass

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
    def _run_cmd_list(cmd_list):
        try:
            result = subprocess.run(cmd_list, capture_output=True, text=True, check=False)
            return result.stdout.strip()
        except Exception as e:
            return str(e)

    cmd = ['meshtastic'] + args
    if device:
        cmd += ['--device', device]
    out = None
    try:
        out = _run_cmd_list(cmd)
        # If empty output and device looks like BLE address, try variants below
        if (not out) and device and (':' in device) and not device.upper().startswith('COM'):
            # generate variants
            variants = generate_ble_variants(device)
            for v in variants:
                cmdv = ['meshtastic'] + args + ['--device', v]
                out = _run_cmd_list(cmdv)
                if out:
                    break
        if out is not None:
            return out
    except FileNotFoundError:
        out = None
    except FileNotFoundError:
        try:
            cmd2 = [sys.executable, '-m', 'meshtastic'] + args
            if device:
                cmd2 += ['--device', device]
            out2 = _run_cmd_list(cmd2)
            # If empty and BLE-like, try variants
            if (not out2) and device and (':' in device) and not device.upper().startswith('COM'):
                variants = generate_ble_variants(device)
                for v in variants:
                    cmdv2 = [sys.executable, '-m', 'meshtastic'] + args + ['--device', v]
                    out2 = _run_cmd_list(cmdv2)
                    if out2:
                        break
            if out2 is not None:
                return out2
        except FileNotFoundError:
            return "meshtastic CLI not found"
        except Exception as e:
            return str(e)
    except Exception as e:
        return str(e)


# Small in-memory cache for meshtastic --info outputs to avoid repeated CLI calls
# Keyed by device string (or '_global' when device is None). TTL is short to keep
# behavior responsive while avoiding repeated expensive calls during loops.
MESHTASTIC_INFO_CACHE: Dict[str, Any] = {}
MESHTASTIC_INFO_CACHE_TTL = 8.0  # seconds


@dataclass
class Node:
    id: str
    long_name: Optional[str] = None
    short_name: Optional[str] = None
    macaddr: Optional[str] = None
    hwModel: Optional[str] = None
    snr: Optional[float] = None
    hopsAway: Optional[int] = None
    lastHeard: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


def get_meshtastic_info(device: str = None, ttl: float = MESHTASTIC_INFO_CACHE_TTL):
    """Return parsed meshtastic --info output, using a short-lived cache keyed by device.

    This wraps `run_cli_command(['--info'], device=...)` and `parse_meshtastic_info` and
    avoids repeated CLI calls within a short time window.
    """
    key = device or '_global'
    now = _time.time()
    entry = MESHTASTIC_INFO_CACHE.get(key)
    if entry and (now - entry[0]) < ttl:
        return entry[1]
    raw = run_cli_command(['--info'], device=device)
    parsed = parse_meshtastic_info(raw)
    MESHTASTIC_INFO_CACHE[key] = (now, parsed)
    return parsed


def build_node_object(nid: str, info: dict) -> Node:
    """Construct a lightweight Node object from parsed meshtastic info."""
    try:
        user = info.get('user', {}) if isinstance(info, dict) else {}
        return Node(
            id=nid,
            long_name=user.get('longName') or user.get('long_name'),
            short_name=user.get('shortName') or user.get('short_name'),
            macaddr=(user.get('macaddr') or user.get('mac')),
            hwModel=user.get('hwModel') or info.get('deviceMetrics', {}).get('hwModel'),
            snr=info.get('snr'),
            hopsAway=info.get('hopsAway'),
            lastHeard=info.get('lastHeard'),
            raw=info,
        )
    except Exception:
        return Node(id=nid, raw=info)


def store_telemetry(n: Node):
    """Store a single telemetry datapoint into `node_telemetry` and update the `nodes` row."""
    try:
        raw = n.raw if isinstance(n.raw, dict) else {}
        # Extract battery
        battery = raw.get('battery') or raw.get('batteryLevel') or (raw.get('deviceMetrics') or {}).get('battery')
        # Extract environment JSON (sensors)
        env = raw.get('env') or raw.get('sensors') or raw.get('environment') or {}
        # Extract GPS from common locations
        lat = None
        lon = None
        alt = None
        for key in ('position', 'pos', 'location', 'gps'):
            v = raw.get(key)
            if isinstance(v, dict):
                lat = lat or v.get('lat') or v.get('latitude')
                lon = lon or v.get('lon') or v.get('longitude')
                alt = alt or v.get('alt') or v.get('altitude')
        # fallback top-level
        lat = lat or raw.get('lat') or raw.get('latitude')
        lon = lon or raw.get('lon') or raw.get('longitude')
        alt = alt or raw.get('alt') or raw.get('altitude')

        env_json = json.dumps(env) if env else None
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute('INSERT INTO node_telemetry (node_id, gps_lat, gps_lon, gps_alt, battery, env_json) VALUES (?,?,?,?,?,?)', (
            n.id, lat, lon, alt, battery, env_json
        ))
        # Update nodes table latest telemetry columns
        try:
            cur.execute('UPDATE nodes SET gps_lat = ?, gps_lon = ?, gps_alt = ?, battery = ?, env_json = ?, last_updated = ? WHERE node_id = ?', (
                lat, lon, alt, battery, env_json, datetime.utcnow().isoformat(), n.id
            ))
            if cur.rowcount == 0:
                # Insert placeholder node entry if it doesn't exist
                cur.execute('INSERT INTO nodes (node_id, long_name, role, connection, last_heard, gps_lat, gps_lon, gps_alt, battery, env_json, last_updated) VALUES (?,?,?,?,?,?,?,?,?,?,?)', (
                    n.id, n.long_name or '', None, None, None, lat, lon, alt, battery, env_json, datetime.utcnow().isoformat()
                ))
        except Exception:
            # best-effort; do not fail telemetry storage
            pass
        conn.commit()
        conn.close()
    except Exception:
        # swallow errors to avoid failing commits
        pass


def generate_ble_variants(address: str):
    """Generate plausible BLE device string variants for the meshtastic CLI.

    Examples: 'aa:bb:cc:dd:ee:ff', 'AABBCCDDEEFF', 'aabbccddeeff', 'ble:aa:bb:...'
    """
    a = address.strip()
    no_colon = a.replace(':', '').replace('-', '')
    variants = []
    # original
    variants.append(a)
    # uppercase/lowercase/no separators
    variants.append(no_colon.upper())
    variants.append(no_colon.lower())
    # colon separated uppercase
    variants.append(':'.join([no_colon[i:i+2] for i in range(0, len(no_colon), 2)]).upper())
    # prefixed formats
    variants.append(f'ble:{a}')
    variants.append(f'ble:{no_colon}')
    # dedupe while preserving order
    seen = set()
    out = []
    for v in variants:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


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
    # retry/backoff strategy
    tries = 3
    for attempt in range(tries):
        try:
            scanner = BleakScanner()
            found = await scanner.discover(timeout=timeout + attempt * 2)
            for d in found:
                # some bleak versions give AdvertisementData separately; fall back safely
                rssi = getattr(d, 'rssi', None)
                name = getattr(d, 'name', None)
                address = getattr(d, 'address', None)
                devices.append({'address': address, 'name': name, 'rssi': rssi})
            if devices:
                return devices
        except Exception as e:
            last_err = e
        # exponential backoff sleep
        import asyncio as _asyncio
        await _asyncio.sleep(1 + attempt)
    # no devices found, return any error info if present
    if 'last_err' in locals():
        return {'error': str(last_err)}
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


def interactive_connect():
    """Interactive flow to select a candidate, test with meshtastic --info, and optionally commit as main router."""
    candidates = []
    ports = scan_com_ports()
    candidates += [p['device'] for p in ports]
    try:
        import asyncio
        ble = asyncio.run(scan_ble_devices())
        if isinstance(ble, list):
            candidates += [d['address'] for d in ble if d.get('address')]
    except Exception:
        ble = []
    if not candidates:
        print('No candidates found')
        return
    print('Discovered candidates:')
    for i, c in enumerate(candidates):
        print(f'  [{i}] {c}')
    sel = input('Enter index of device to test (or q to cancel): ').strip()
    if sel.lower().startswith('q'):
        print('Cancelled')
        return
    try:
        idx = int(sel)
        dev = candidates[idx]
    except Exception as e:
        print('Invalid selection:', e)
        return
    print('Testing device', dev)
    out = run_cli_command(['--info'], device=dev)
    print('Raw output (truncated):')
    print((out or '')[:2000])
    parsed = parse_meshtastic_info(out)
    print('Parsed summary:')
    print(summarize_meshtastic_nodes(parsed))
    commit = input('Commit this device as main router? (y/N): ').strip().lower()
    if commit == 'y':
        valid = validate_candidate(dev)
        print('Validation result:', valid)
        if not valid.get('ok'):
            yn = input('Validation failed. Proceed and commit anyway? (y/N): ').strip().lower()
            if yn != 'y':
                print('Aborted commit')
                return
        summary = auto_connect_loop([dev], allocation_mode='manual', main_id=dev, auto_commit=True)
        print('Commit result:')
        print(summary)
    else:
        print('Not committed')


def validate_candidate(device: str, expected: str = None):
    """Validate a device by attempting to query it and optionally matching expected MAC/name.

    Returns {'ok': bool, 'reason': str, 'raw': raw_output, 'parsed': parsed}
    """
    # Check COM port availability
    if device.upper().startswith('COM'):
        # attempt to open using pyserial (non-blocking check)
        try:
            import serial
            s = serial.Serial()
            s.port = device
            s.timeout = 0.5
            try:
                s.open()
                s.close()
            except Exception as e:
                return {'ok': False, 'reason': f'Could not open COM port: {e}'}
        except Exception:
            # pyserial not available or other issue
            return {'ok': False, 'reason': 'pyserial not available'}
    parsed = {'raw': ''}
    import time
    # helper to try meshtastic info with retries and variants
    def try_info_with_retries(device_to_try, attempts=3, delay=1.0):
        last_raw = ''
        for i in range(attempts):
            out = run_cli_command(['--info'], device=device_to_try)
            last_raw = out
            if out and str(out).strip():
                return True, out
            time.sleep(delay * (1 + i))
        return False, last_raw

    # If COM, perform open/close check with retries
    if device.upper().startswith('COM'):
        try:
            import serial
        except Exception:
            return {'ok': False, 'reason': 'pyserial not installed', 'raw': '', 'parsed': parsed}
        opened = False
        last_err = None
        for attempt in range(3):
            try:
                s = serial.Serial(device)
                s.close()
                opened = True
                break
            except Exception as e:
                last_err = e
                time.sleep(0.5 + attempt * 0.5)
        if not opened:
            return {'ok': False, 'reason': f'Could not open serial port after retries: {last_err}', 'raw': '', 'parsed': parsed}

    # For BLE-like addresses, try generated variants
    devices_to_try = [device]
    if (':' in device) and not device.upper().startswith('COM'):
        devices_to_try = generate_ble_variants(device)

    # Try each candidate/variant with retries
    last_raw = ''
    for d in devices_to_try:
        ok, out = try_info_with_retries(d, attempts=3, delay=1.0)
        parsed['raw'] = out
        last_raw = out
        if ok:
            # try parse JSON
            try:
                parsed_json = json.loads(out)
                parsed['json'] = parsed_json
                # heuristic: look for node(s)
                if isinstance(parsed_json, dict) and ('node' in parsed_json or 'nodes' in parsed_json):
                    # if expected provided, check it
                    if expected:
                        # check expected in id, mac or names
                        text = json.dumps(parsed_json).lower()
                        if str(expected).lower() in text:
                            return {'ok': True, 'reason': 'Found expected node in JSON', 'raw': out, 'parsed': parsed}
                        else:
                            return {'ok': False, 'reason': 'JSON returned but expected identifier not found', 'raw': out, 'parsed': parsed}
                    return {'ok': True, 'reason': 'Found node info', 'raw': out, 'parsed': parsed}
            except Exception:
                # non-json but got something non-empty
                if expected and str(expected).lower() not in str(out).lower():
                    return {'ok': False, 'reason': 'Non-JSON output present but expected identifier not found', 'raw': out, 'parsed': parsed}
                return {'ok': True, 'reason': 'Non-JSON output present', 'raw': out, 'parsed': parsed}

    # nothing returned for any variant
    return {'ok': False, 'reason': 'No meshtastic node info returned after retries', 'raw': last_raw, 'parsed': parsed}
    # Try meshtastic --info on device
    raw = run_cli_command(['--info'], device=device)
    parsed = parse_meshtastic_info(raw)
    ok = False
    reason = ''
    if isinstance(parsed, dict) and parsed.get('nodes'):
        ok = True
    else:
        # accept raw text that contains known markers
        if raw and ('node' in raw.lower() or 'device' in raw.lower()):
            ok = True
        else:
            reason = 'No meshtastic node info returned'
    # Optional matching
    if expected and ok:
        # try to match expected MAC or name in parsed nodes
        found = False
        nodes = parsed.get('nodes', {}) if isinstance(parsed, dict) else {}
        for nid, info in nodes.items():
            user = info.get('user', {})
            mac = (user.get('macaddr') or user.get('mac') or '').upper()
            name = (user.get('longName') or user.get('shortName') or '').upper()
            if expected.upper().replace(':','') in mac.replace(':','') or expected.upper() in name:
                found = True
                break
        if not found:
            ok = False
            reason = 'Expected identifier not found in meshtastic info'
    return {'ok': ok, 'reason': reason, 'raw': raw, 'parsed': parsed}


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
        # Try device variants for BLE addresses
        ok = False
        raw_out = ''
        devices_to_try = [dev]
        if (':' in dev) and not dev.upper().startswith('COM'):
            devices_to_try = generate_ble_variants(dev)
        for d_try in devices_to_try:
            parsed = get_meshtastic_info(device=d_try)
            # If parsed contains nodes or non-empty raw, consider it successful
            if isinstance(parsed, dict) and (parsed.get('nodes') or parsed.get('raw') or parsed.get('info')):
                ok = True
                # save a small snippet
                if parsed.get('nodes'):
                    try:
                        raw_out = json.dumps(parsed.get('nodes'))
                    except Exception:
                        raw_out = str(parsed.get('nodes'))
                else:
                    raw_out = parsed.get('raw') or ''
                break
        summary['attempts'].append({'device': dev, 'ok': ok, 'raw': raw_out[:1000] if isinstance(raw_out, str) else raw_out})
    # build allocation proposal from attempts
    available = [a['device'] for a in summary['attempts'] if a.get('ok')]
    main = None
    routers = []
    if allocation_mode == 'manual' and main_id:
        main = main_id
        routers = [d for d in available if d != main]
    else:
        if available:
            main = available[0]
            routers = available[1:]
    allocation = {
        'main': main,
        'routers': routers,
        'allocated': []
    }
    for d in [main] + routers if main else routers:
        if not d:
            continue
        allocation['allocated'].append({'id': d, 'role': 'ROUTER' if d == main else 'ROUTER_LATE', 'type': ('com' if d.upper().startswith('COM') else 'ble'), 'long_name': d})

    summary['allocations'] = allocation

    if auto_commit:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # snapshot current nodes table
        c.execute('SELECT node_id, long_name, role, connection, last_heard, snr, rssi, battery, uptime, last_updated FROM nodes')
        rows = c.fetchall()
        columns = [d[0] for d in c.description]
        snapshot = [dict(zip(columns, r)) for r in rows]
        when_ts = datetime.utcnow().isoformat()
        summary_text = json.dumps({'allocation': allocation})
        c.execute('INSERT INTO commit_history (when_ts, summary, snapshot) VALUES (?,?,?)', (when_ts, summary_text, json.dumps(snapshot)))

        try:
            # perform upserts for allocated nodes
            for node in allocation['allocated']:
                node_id = node['id']
                role = node['role']
                conn_now = datetime.utcnow().isoformat()
                c.execute('SELECT id FROM nodes WHERE node_id = ?', (node_id,))
                if c.fetchone():
                    c.execute('UPDATE nodes SET role = ?, long_name = ?, connection = ? WHERE node_id = ?', (role, node.get('long_name'), node.get('type'), node_id))
                else:
                    c.execute('INSERT INTO nodes (node_id, long_name, role, connection, last_heard) VALUES (?,?,?,?,?)', (node_id, node.get('long_name'), role, node.get('type'), None))
                c.execute('INSERT INTO logs (event, details) VALUES (?, ?)', ('auto_connect_commit', json.dumps(node)))
                # Attempt to capture telemetry for this node and store historical record
                try:
                    parsed = get_meshtastic_info(device=node_id)
                    # parsed may contain 'nodes' mapping or 'raw'; try to find node info
                    if isinstance(parsed, dict) and parsed.get('nodes'):
                        nodes_map = parsed.get('nodes')
                        # try to find a matching entry by node id
                        if node_id in nodes_map:
                            info = nodes_map[node_id]
                            nobj = build_node_object(node_id, info)
                            store_telemetry(nobj)
                        else:
                            # sometimes node id is nested differently; try first node
                            for nid, info in nodes_map.items():
                                nobj = build_node_object(nid, info)
                                store_telemetry(nobj)
                                break
                except Exception:
                    # best-effort: ignore telemetry storage errors during commit
                    pass
            conn.commit()
            summary['committed'] = True
        except Exception as e:
            conn.rollback()
            summary['commit_error'] = str(e)
        finally:
            conn.close()
        # completed commit above; nothing further to do here
    else:
        summary['committed'] = False

    return summary


def undo_last_commit():
    """Revert the last auto-commit by restoring the snapshot stored in commit_history.

    Returns dict {ok: bool, reason: str}
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute('SELECT id, when_ts, summary, snapshot FROM commit_history ORDER BY id DESC LIMIT 1')
        row = cur.fetchone()
        if not row:
            return {'ok': False, 'reason': 'No commit history available'}
        hist_id, when_ts, summary_text, snapshot_json = row
        # snapshot_json should be a JSON array of node rows
        try:
            snapshot = json.loads(snapshot_json) if snapshot_json else []
        except Exception:
            snapshot = []
        # clear nodes table and restore snapshot
        cur.execute('DELETE FROM nodes')
        for r in snapshot:
            cur.execute('INSERT INTO nodes (node_id, long_name, role, connection, last_heard, snr, rssi, battery, uptime, last_updated) VALUES (?,?,?,?,?,?,?,?,?,?)', (
                r.get('node_id'), r.get('long_name'), r.get('role'), r.get('connection'), r.get('last_heard'), r.get('snr'), r.get('rssi'), r.get('battery'), r.get('uptime'), r.get('last_updated')
            ))
        conn.commit()
        cur.execute('INSERT INTO logs (event, details) VALUES (?, ?)', ('undo_last_commit', f'Restored commit_history id={hist_id}'))
        conn.commit()
        conn.close()
        return {'ok': True, 'reason': f'Restored commit id {hist_id} from {when_ts}'}
    except Exception as e:
        return {'ok': False, 'reason': str(e)}


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
    # meshtastic (use short-lived cache)
    parsed = get_meshtastic_info(device=device)
    result['meshtastic_raw'] = parsed
    # Try to extract node MACs from meshtastic parsed data and build Node objects
    nodes = {}
    node_objs = {}
    if isinstance(parsed, dict) and 'nodes' in parsed:
        nodes = parsed['nodes']
        for nid, info in nodes.items():
            node_objs[nid] = build_node_object(nid, info)
    result['meshtastic_nodes'] = nodes
    result['meshtastic_node_objs'] = node_objs
    # Correlate BLE addresses to meshtastic nodes by matching MAC / macaddr fields
    matches = []
    try:
        node_mac_map = {}
        for nid, nobj in node_objs.items():
            mac = (nobj.macaddr or '')
            if mac:
                node_mac_map[mac.upper().replace(':','')] = {'id': nid, 'info': nobj}
        if isinstance(ble, list):
            for d in ble:
                addr = d.get('address','') or ''
                addr_norm = addr.upper().replace(':','')
                if addr_norm in node_mac_map:
                    matches.append({'ble': d, 'node': node_mac_map[addr_norm]})
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

@app.get('/ui', response_class=HTMLResponse)
async def ui_dashboard(request: Request):
    return templates.TemplateResponse('dashboard_ui.html', {"request": request})


@app.get('/node/{node_id}', response_class=HTMLResponse)
async def node_info_page(request: Request, node_id: str):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute('SELECT * FROM nodes WHERE node_id = ?', (node_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return templates.TemplateResponse('node_info.html', {"request": request, "node": None, "telemetry": []})
    node = dict(row)
    # parse env_json if present
    env = None
    try:
        env = json.loads(node.get('env_json') or '{}')
    except Exception:
        env = {}
    node['env'] = env
    return templates.TemplateResponse('node_info.html', {"request": request, "node": node, "telemetry": []})


@app.get('/api/node/{node_id}/telemetry')
async def api_node_telemetry(node_id: str):
    # Return the latest stored telemetry for a node from the nodes table (if present)
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute('SELECT node_id, long_name, gps_lat, gps_lon, gps_alt, battery, env_json, last_updated FROM nodes WHERE node_id = ?', (node_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return JSONResponse({"ok": False, "reason": "Node not found"}, status_code=404)
        data = dict(row)
        # parse env_json
        try:
            data['env'] = json.loads(data.get('env_json') or '{}')
        except Exception:
            data['env'] = {}
        return JSONResponse({"ok": True, "node": data})
    except Exception as e:
        return JSONResponse({"ok": False, "reason": str(e)}, status_code=500)


@app.get('/api/node/{node_id}/telemetry/history')
async def api_node_telemetry_history(node_id: str, limit: int = 100):
    """Return recent historical telemetry points for a node (most recent first)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute('SELECT ts, gps_lat, gps_lon, gps_alt, battery, env_json FROM node_telemetry WHERE node_id = ? ORDER BY ts DESC LIMIT ?', (node_id, limit))
        rows = cur.fetchall()
        conn.close()
        history = []
        for r in rows:
            d = dict(r)
            try:
                d['env'] = json.loads(d.get('env_json') or '{}')
            except Exception:
                d['env'] = {}
            d.pop('env_json', None)
            history.append(d)
        return JSONResponse({"ok": True, "history": history})
    except Exception as e:
        return JSONResponse({"ok": False, "reason": str(e)}, status_code=500)


def get_redis_client():
    """Return the global REDIS_CLIENT if configured, else None."""
    global REDIS_CLIENT
    return REDIS_CLIENT


def serialize_json(obj: Any) -> str:
    try:
        return json.dumps(obj)
    except Exception:
        return '{}'


def deserialize_json(s: Optional[str]) -> Any:
    if s is None:
        return None
    try:
        return json.loads(s)
    except Exception:
        return None


@app.get('/api/nodes/positions')
async def api_nodes_positions():
    """Return latest position for every node (if GPS present).

    Uses Redis (if `REDIS_CLIENT` configured and `REDIS_URL` set) as the primary
    cache for short TTL, falling back to an in-process cache when Redis isn't
    available.
    """
    global _POSITIONS_CACHE
    try:
        now = _time.time()
        # Try Redis first (async client if available)
        cache_ttl = 5
        try:
            if REDIS_ASYNC_CLIENT is not None:
                try:
                    val = await REDIS_ASYNC_CLIENT.get('positions_cache')
                    if val:
                        parsed = deserialize_json(val)
                        if isinstance(parsed, dict) and parsed.get('ts') and (now - parsed.get('ts', 0) < cache_ttl):
                            return JSONResponse({"ok": True, "positions": parsed.get('positions', [])})
                except Exception:
                    pass
            else:
                rc = get_redis_client()
                if rc:
                    try:
                        val = rc.get('positions_cache')
                        if val:
                            parsed = deserialize_json(val)
                            if isinstance(parsed, dict) and parsed.get('ts') and (now - parsed.get('ts', 0) < cache_ttl):
                                return JSONResponse({"ok": True, "positions": parsed.get('positions', [])})
                    except Exception:
                        pass
        except Exception:
            # Redis issues are non-fatal; fall back to in-process cache
            pass

        # In-process cache
        cache = globals().get('_POSITIONS_CACHE')
        if cache and (now - cache.get('ts', 0) < cache.get('ttl', 5.0)):
            return JSONResponse({"ok": True, "positions": cache.get('positions', [])})

        # Query DB for positions
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute('SELECT node_id, long_name, gps_lat, gps_lon, gps_alt, battery, last_updated FROM nodes WHERE gps_lat IS NOT NULL AND gps_lon IS NOT NULL')
        rows = cur.fetchall()
        conn.close()
        out = [dict(r) for r in rows]

        # store in in-process cache
        globals()['_POSITIONS_CACHE'] = {'ts': now, 'ttl': 5.0, 'positions': out}

        # store in Redis if available (async or sync)
        try:
            if REDIS_ASYNC_CLIENT is not None:
                try:
                    payload = {'ts': now, 'positions': out}
                    await REDIS_ASYNC_CLIENT.setex('positions_cache', cache_ttl, serialize_json(payload))
                except Exception:
                    pass
            else:
                rc = get_redis_client()
                if rc:
                    try:
                        payload = {'ts': now, 'positions': out}
                        rc.setex('positions_cache', cache_ttl, serialize_json(payload))
                    except Exception:
                        pass
        except Exception:
            pass

        return JSONResponse({"ok": True, "positions": out})
    except Exception as e:
        return JSONResponse({"ok": False, "reason": str(e)}, status_code=500)


@app.get('/map', response_class=HTMLResponse)
async def map_page(request: Request):
    return templates.TemplateResponse('map.html', {"request": request})

@app.get('/api/discover')
async def api_discover():
    try:
        com_ports = scan_com_ports()
        ble = []
        try:
            ble = await scan_ble_devices()
        except Exception:
            # best-effort: leave ble as empty list if scanning fails
            ble = []
        raw = run_cli_command(['--info'])
        parsed = parse_meshtastic_info(raw)
        return JSONResponse({"com_ports": com_ports, "ble_devices": ble, "meshtastic": parsed})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post('/api/validate')
async def api_validate(payload: dict):
    device = payload.get('device') if isinstance(payload, dict) else None
    if not device:
        return JSONResponse({"ok": False, "reason": "Missing device"}, status_code=400)
    res = validate_candidate(device)
    return JSONResponse(res)

@app.post('/api/commit')
async def api_commit(payload: dict):
    auto_commit_flag = False
    allocation_mode = 'auto'
    main_id = None
    if isinstance(payload, dict):
        auto_commit_flag = bool(payload.get('auto_commit', False))
        allocation_mode = payload.get('allocation_mode', 'auto')
        main_id = payload.get('main_id')
    candidates = [p['device'] for p in scan_com_ports()]
    try:
        ble = await scan_ble_devices()
        if isinstance(ble, list):
            candidates += [d['address'] for d in ble if d.get('address')]
    except Exception:
        # ignore BLE scanning problems; proceed with COM-only candidates
        pass
    summary = auto_connect_loop(candidates, allocation_mode=allocation_mode, main_id=main_id, auto_commit=auto_commit_flag)
    return JSONResponse(summary)

@app.post('/api/undo')
async def api_undo():
    res = undo_last_commit()
    return JSONResponse(res)

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
        parser.add_argument('--interactive-connect', action='store_true', help='Run an interactive connect flow for selecting and validating a device')
        parser.add_argument('--undo-last-commit', action='store_true', help='Undo the last auto-commit by restoring previous nodes snapshot')
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

        if args.interactive_connect:
            interactive_connect()

        if args.undo_last_commit:
            res = undo_last_commit()
            print(res)

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
