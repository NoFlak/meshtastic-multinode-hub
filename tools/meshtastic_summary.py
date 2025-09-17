import sys, os, json
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, BASE_DIR)
from main import run_cli_command, parse_meshtastic_info, summarize_meshtastic_nodes

if __name__ == '__main__':
    raw = run_cli_command(['--info'])
    parsed = parse_meshtastic_info(raw)
    summ = summarize_meshtastic_nodes(parsed)
    print(json.dumps(summ, indent=2))
