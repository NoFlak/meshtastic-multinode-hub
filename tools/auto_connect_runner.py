import sys, os, json, asyncio
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, BASE_DIR)
from main import auto_connect_loop, scan_com_ports, scan_ble_devices

if __name__ == '__main__':
    candidates = [p['device'] for p in scan_com_ports()]
    ble = asyncio.run(scan_ble_devices())
    if isinstance(ble, list):
        candidates += [d['address'] for d in ble if d.get('address')]
    print('Candidates:', candidates)
    summary = auto_connect_loop(candidates, allocation_mode='auto', auto_commit=False)
    print(json.dumps(summary, indent=2))
