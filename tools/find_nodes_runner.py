import sys, os, json, asyncio
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, BASE_DIR)
from main import find_nodes

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--device', help='Optional device to pass to meshtastic (COM port or BLE address)')
    args = parser.parse_args()
    res = asyncio.run(find_nodes(device=args.device))
    print(json.dumps(res, indent=2))
