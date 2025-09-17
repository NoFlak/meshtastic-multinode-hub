Return Point - iteration 2025-09-16

Branch: main
Timestamp: 2025-09-16T00:00:00Z (local timezone)

Summary:
This return point captures the repository state after the 2025-09-16 iteration which added Redis async detection, cache tests, and a device helper tool.

Files changed in this iteration (high level):
- main.py (Redis detection, async-aware caching for `/api/nodes/positions`)
- tools/check_device.py (new helper; supports --port/--ble, --json, --timeout, --retries, --try-ble)
- changelog.txt (appended entry for this iteration)
- static/map.js, templates/map.html (minor UI polish)
- tests/test_redis_cache.py, tests/test_redis_failure.py (added tests for Redis behavior)

Validation performed:
- Local test suite: 8 passed (unit + integration tests)
- Live device validation: COM enumeration, BLE scan, and `meshtastic --info --port COM4` returned JSON. Verified with `tools/check_device.py` (human and JSON outputs).

How to roll back to previous state:
1. If using git, to roll back to the commit prior to this iteration, find the previous commit hash (e.g., `git log`) and run:

   git checkout <previous-commit-hash>

2. If you want to revert only specific files, use:

   git checkout main -- <path/to/file>

Notes & next steps:
- Consider adding explicit async Redis connect/close in FastAPI lifespan for production.
- Continue UI improvements: add Chart.js graphs and richer node details.

