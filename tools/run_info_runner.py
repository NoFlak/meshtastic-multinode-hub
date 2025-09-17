import sys, os
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, BASE_DIR)
from main import run_cli_command

if __name__ == '__main__':
    print('Calling run_cli_command(["--info"])')
    print(run_cli_command(['--info']))
