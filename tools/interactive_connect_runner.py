import sys, os
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, BASE_DIR)
from main import interactive_connect

if __name__ == '__main__':
    interactive_connect()
