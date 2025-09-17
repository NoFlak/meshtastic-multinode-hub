#!/usr/bin/env python3
"""Check a Meshtastic device and print a compact summary.

Usage examples:
  python tools/check_device.py --port COM4
  python tools/check_device.py --ble 9c:13:9e:e8:37:70

The script runs `python -m meshtastic --info` with the chosen device and
attempts to extract JSON objects from the CLI output. It prints a short
summary: local device info and a short list of nodes (id, name, battery, lat/lon).
"""
import argparse
import subprocess
import sys
import json
import re
import time
from typing import Optional


def run_cmd(cmd, timeout: Optional[float] = None):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=timeout)
        return p.returncode, p.stdout.strip() or p.stderr.strip()
    except subprocess.TimeoutExpired as e:
        return 124, f'Timeout after {timeout}s'
    except Exception as e:
        return 1, str(e)


def extract_json_objects(s):
    """Return a list of parsed JSON objects found in text by matching balanced braces."""
    objs = []
    i = 0
    n = len(s)
    while i < n:
        if s[i] == '{':
            depth = 0
            start = i
            j = i
            while j < n:
                if s[j] == '{':
                    depth += 1
                elif s[j] == '}':
                    depth -= 1
                    if depth == 0:
                        end = j + 1
                        chunk = s[start:end]
                        try:
                            objs.append(json.loads(chunk))
                        except Exception:
                            # skip invalid JSON chunks
                            pass
                        i = end
                        break
                j += 1
        i += 1
    return objs


def summarize(parsed_objects):
    # parsed_objects is a list of dicts representing JSON blocks found in output
    # We try to find ones that look like 'my info', 'Metadata', and 'Nodes in mesh'
    summary = {}
    nodes = {}
    for obj in parsed_objects:
        # heuristics: if it has 'myNodeNum' or 'rebootCount' treat as myinfo
        if isinstance(obj, dict) and ('myNodeNum' in obj or 'deviceId' in obj):
            summary['myinfo'] = obj
        # metadata often contains firmwareVersion
        elif isinstance(obj, dict) and ('firmwareVersion' in obj or 'deviceStateVersion' in obj):
            summary['metadata'] = obj
        else:
            # nodes mapping: look for keys like '!9ee6fc30'
            if isinstance(obj, dict):
                # decide if this dict is a nodes map by checking nested user entries
                keys = list(obj.keys())
                if keys and all(isinstance(k, str) and k.startswith('!') for k in keys[:3]):
                    nodes.update(obj)
    if nodes:
        summary['nodes'] = nodes
    return summary


def compact_print(summary, max_nodes=10):
    if 'myinfo' in summary:
        mi = summary['myinfo']
        print('Local device:')
        print('  deviceId:', mi.get('deviceId') or mi.get('device_id'))
        print('  myNodeNum:', mi.get('myNodeNum'))
        print('  rebootCount:', mi.get('rebootCount'))
    if 'metadata' in summary:
        md = summary['metadata']
        print('  firmwareVersion:', md.get('firmwareVersion'))
    print('')
    nodes = summary.get('nodes') or {}
    if not nodes:
        print('No nodes parsed from output.')
        return
    print(f'Nodes (showing up to {max_nodes}):')
    cnt = 0
    for nid, info in nodes.items():
        if cnt >= max_nodes:
            break
        name = info.get('user', {}).get('longName') if isinstance(info.get('user'), dict) else None
        mac = info.get('user', {}).get('macaddr') if isinstance(info.get('user'), dict) else None
        battery = None
        dm = info.get('deviceMetrics') or {}
        battery = dm.get('batteryLevel') or info.get('battery') or info.get('deviceMetrics', {}).get('battery')
        pos = info.get('position') or {}
        lat = pos.get('latitude') or pos.get('lat')
        lon = pos.get('longitude') or pos.get('lon')
        print(f'  {nid}: name={name or "(unknown)"} mac={mac or "(unknown)"} battery={battery} lat={lat} lon={lon}')
        cnt += 1


def main():
    p = argparse.ArgumentParser(description='Check a Meshtastic device and print a compact summary')
    g = p.add_mutually_exclusive_group(required=False)
    g.add_argument('--port', help='Serial port (e.g., COM4 or /dev/ttyUSB0)')
    g.add_argument('--ble', help='BLE address (e.g., a1:b2:c3:...)')
    p.add_argument('--try-ble', action='store_true', help='If serial fails, try BLE using --ble value')
    p.add_argument('--timeout', type=float, default=10.0, help='Timeout seconds for meshtastic CLI call')
    p.add_argument('--retries', type=int, default=1, help='Number of retries for meshtastic CLI call')
    p.add_argument('--retry-delay', type=float, default=1.0, help='Seconds to wait between retries')
    p.add_argument('--json', dest='as_json', action='store_true', help='Emit structured JSON output')
    args = p.parse_args()

    if not args.port and not args.ble and not args.try_ble:
        p.error('Either --port or --ble must be provided, or use --try-ble with --ble')

    def attempt(cmd):
        for attempt_idx in range(args.retries):
            rc, out = run_cmd(cmd, timeout=args.timeout)
            if rc == 0:
                return rc, out
            if attempt_idx + 1 < args.retries:
                time.sleep(args.retry_delay)
        return rc, out

    # prefer serial if provided
    final_out = None
    final_rc = 1
    if args.port:
        cmd = [sys.executable, '-m', 'meshtastic', '--info', '--port', args.port]
        final_rc, final_out = attempt(cmd)

    # if serial failed and user asked to try ble, or only ble provided
    if (final_rc != 0 and args.try_ble and args.ble) or (not args.port and args.ble):
        cmd = [sys.executable, '-m', 'meshtastic', '--info', '--ble', args.ble]
        final_rc, final_out = attempt(cmd)

    if final_rc != 0:
        print('meshtastic CLI returned non-zero exit code', final_rc)
        print(final_out)
        sys.exit(final_rc)

    # extract JSON objects from output
    parsed = extract_json_objects(final_out)
    if not parsed:
        # nothing parsed — either error or no JSON; print raw output
        if args.as_json:
            print(json.dumps({'ok': False, 'error': 'no_json', 'output': final_out}))
            return
        print('No JSON objects parsed from meshtastic output; full output below:')
        print(final_out)
        return

    summary = summarize(parsed)
    if args.as_json:
        print(json.dumps({'ok': True, 'summary': summary}, default=str))
    else:
        compact_print(summary)


if __name__ == '__main__':
    main()
