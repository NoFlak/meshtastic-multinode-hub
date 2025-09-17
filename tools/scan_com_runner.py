import sys, os
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, BASE_DIR)
from main import scan_com_ports

if __name__ == '__main__':
    print('COM ports:')
    print(scan_com_ports())
