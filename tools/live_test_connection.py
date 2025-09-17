"""Live connection test helper.

Runs non-destructive discovery:
 - lists COM ports (if pyserial installed)
 - scans BLE (if bleak installed)
 - attempts to run `meshtastic --info` (if available)

This script is intended to be run locally where hardware access is available.
"""
import subprocess
import sys
import json


def run_cmd(cmd):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, check=False)
        return p.returncode, p.stdout.strip() or p.stderr.strip()
    except Exception as e:
        return 1, str(e)


def list_com_ports():
    try:
        import serial.tools.list_ports as list_ports
    except Exception as e:
        return {'error': f'pyserial not available: {e}'}
    ports = []
    for p in list_ports.comports():
        ports.append({'device': p.device, 'description': p.description, 'hwid': p.hwid})
    return ports


async def scan_ble(timeout=4.0):
    try:
        from bleak import BleakScanner
    except Exception as e:
        return {'error': f'bleak not available: {e}'}
    try:
        scanner = BleakScanner()
        found = await scanner.discover(timeout=timeout)
        out = []
        for d in found:
            out.append({'address': getattr(d, 'address', None), 'name': getattr(d, 'name', None), 'rssi': getattr(d, 'rssi', None)})
        return out
    except Exception as e:
        return {'error': str(e)}


def try_meshtastic_info(device: str = None):
    cmd = ['meshtastic', '--info']
    if device:
        cmd += ['--device', device]
    rc, out = run_cmd(cmd)
    if rc == 0 and out:
        try:
            return json.loads(out)
        except Exception:
            return out
    # fallback to python -m meshtastic
    cmd2 = [sys.executable, '-m', 'meshtastic', '--info']
    if device:
        cmd2 += ['--device', device]
    rc2, out2 = run_cmd(cmd2)
    if rc2 == 0 and out2:
        try:
            return json.loads(out2)
        except Exception:
            return out2
    return {'error': 'meshtastic CLI not available', 'rc': rc, 'out': out}


def main():
    print('Listing COM ports...')
    ports = list_com_ports()
    print(json.dumps(ports, indent=2))

    print('\nAttempting BLE scan (best-effort, requires BLE hardware)...')
    try:
        import asyncio
        res = asyncio.run(scan_ble())
        print(json.dumps(res, indent=2))
    except Exception as e:
        print('BLE scan failed:', e)

    print('\nTrying meshtastic --info (best-effort)...')
    res = try_meshtastic_info()
    print(json.dumps(res, indent=2))


if __name__ == '__main__':
    main()
