import sys, os, asyncio
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, BASE_DIR)
from main import scan_ble_devices

if __name__ == '__main__':
    print('BLE devices:')
    devices = asyncio.run(scan_ble_devices())
    print(devices)
