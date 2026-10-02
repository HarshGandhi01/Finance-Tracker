"""Load the repository database module, refreshing it after a deployment."""
import hashlib
import importlib.util
from pathlib import Path
import sys
from threading import Lock


_LOCK = Lock()
_MODULE_NAME = '_finance_tracker_dashboard_db'


def load_database():
    path = Path(__file__).resolve().parents[1] / 'db.py'
    source = path.read_bytes()
    fingerprint = hashlib.sha256(source).hexdigest()
    with _LOCK:
        cached = sys.modules.get(_MODULE_NAME)
        if cached is not None and getattr(cached, '_source_fingerprint', None) == fingerprint:
            return cached

        spec = importlib.util.spec_from_file_location(_MODULE_NAME, path)
        module = importlib.util.module_from_spec(spec)
        # Compile the bytes we fingerprinted, avoiding stale bytecode or an unrelated db import.
        exec(compile(source, str(path), 'exec'), module.__dict__)
        module._source_fingerprint = fingerprint
        sys.modules[_MODULE_NAME] = module
        return module
