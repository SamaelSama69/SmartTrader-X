import os
import tempfile
from pathlib import Path


_TEST_TMP = Path(__file__).resolve().parent / ".test_tmp"
_TEST_TMP.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("TMP", str(_TEST_TMP))
os.environ.setdefault("TEMP", str(_TEST_TMP))
tempfile.tempdir = str(_TEST_TMP)
_orig_tempdir = tempfile.TemporaryDirectory


class _SafeTemporaryDirectory:
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("ignore_cleanup_errors", True)
        self._inner = _orig_tempdir(*args, **kwargs)

    def __enter__(self):
        return self._inner.__enter__()

    def __exit__(self, exc_type, exc, tb):
        try:
            return self._inner.__exit__(exc_type, exc, tb)
        except PermissionError:
            return True

    def cleanup(self):
        try:
            self._inner.cleanup()
        except PermissionError:
            pass


def _safe_tempdir(*args, **kwargs):
    return _SafeTemporaryDirectory(*args, **kwargs)


tempfile.TemporaryDirectory = _safe_tempdir


def pytest_addoption(parser):
    """Register --include-costs flag for pytest."""
    parser.addoption('--include-costs', action='store_true',
                    help='Enable transaction costs for backtests')
