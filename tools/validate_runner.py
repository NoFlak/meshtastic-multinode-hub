import sys, os
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, BASE_DIR)
from main import validate_candidate

if __name__ == '__main__':
    for d in ['COM4', '9C:13:9E:E8:37:71']:
        print('Validating', d)
        res = validate_candidate(d, expected=None)
        print(res)
