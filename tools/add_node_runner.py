import sys, os
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, BASE_DIR)
from main import add_node_manual

if __name__ == '__main__':
    res = add_node_manual('ble', '9C:13:9E:E8:37:71', long_name='Meshtastic_3770', short_name='3770', hw_model='HELTEC_V3', role='CLIENT')
    print('Result:', res)
