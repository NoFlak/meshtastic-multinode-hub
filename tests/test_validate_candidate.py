import json
import importlib
import importlib.util
import types
from pathlib import Path
import pytest


@pytest.fixture(autouse=True)
def reload_main(tmp_path):
    # load the main.py module by path to avoid package import issues
    repo_dir = Path(__file__).resolve().parent
    main_path = repo_dir / '..' / 'main.py'
    main_path = main_path.resolve()
    spec = importlib.util.spec_from_file_location('main_module', str(main_path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_validate_com_port_not_installed(reload_main, monkeypatch):
    m = reload_main
    # simulate pyserial import error inside function by ensuring it's not in sys.modules
    monkeypatch.setitem(importlib.sys.modules, 'serial', None)
    res = m.validate_candidate('COM99')
    assert res['ok'] is False
    assert 'pyserial' in res['reason'] or 'not available' in res['reason']


def test_validate_com_port_open_fail(reload_main, monkeypatch):
    m = reload_main
    class FakeSerial:
        def __init__(self, *a, **kw):
            raise Exception('port busy')
    # inject fake serial module into sys.modules so "import serial" inside the function gets it
    fake_mod = types.ModuleType('serial')
    fake_mod.Serial = FakeSerial
    monkeypatch.setitem(importlib.sys.modules, 'serial', fake_mod)
    res = m.validate_candidate('COM4')
    assert res['ok'] is False
    assert ('Could not open serial port' in res['reason']) or ('pyserial' in res['reason'])


def test_validate_ble_variants_and_json_success(reload_main, monkeypatch):
    m = reload_main
    # mock run_cli_command to return empty for first variant, then valid JSON for second
    calls = {'count': 0}

    def fake_run(args, device=None):
        calls['count'] += 1
        if calls['count'] == 1:
            return ''
        # return JSON containing nodes
        return json.dumps({'nodes': [{'id': '9C:13:9E:E8:37:71', 'name': 'Test'}]})

    monkeypatch.setattr(m, 'run_cli_command', fake_run)
    res = m.validate_candidate('9C:13:9E:E8:37:71', expected='9C:13:9E:E8:37:71')
    assert res['ok'] is True
    assert 'Found' in res['reason']
