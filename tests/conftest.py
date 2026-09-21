"""Test harness guard rails.

Two promises every test runs under. No test may open a connection off this
machine: `socket.connect` is wrapped for the whole session and raises on any
non-loopback address, which is what makes the offline claim in PRD PR-1 a
tested property rather than a hope. And Qt runs headless, so widget tests
work on a build agent with no display.
"""

import os
import socket
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Tests import `revolv` from the repo root, wherever pytest was started.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from revolv.netguard import is_loopback_host  # noqa: E402

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "synthetic_call"

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


def _check(address):
    host = address[0] if isinstance(address, tuple) and address else None
    if isinstance(host, (str, bytes)):
        name = host.decode("ascii", "replace") if isinstance(host, bytes) else host
        if not is_loopback_host(name):
            raise AssertionError(
                "Blocked non-loopback connection to {0!r}: Phase 1 tests run "
                "offline".format(name))


def _guarded_connect(self, address):
    _check(address)
    return _real_connect(self, address)


def _guarded_connect_ex(self, address):
    _check(address)
    return _real_connect_ex(self, address)


@pytest.fixture(autouse=True)
def _no_egress(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _guarded_connect_ex)
    yield


@pytest.fixture(scope="session")
def fixture_dir():
    return FIXTURE_DIR


@pytest.fixture(scope="session")
def fixture_segments():
    import json

    with open(FIXTURE_DIR / "call.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def fixture_report():
    import json

    with open(FIXTURE_DIR / "call.analysis.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def fixture_meta():
    import json

    with open(FIXTURE_DIR / "meta.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture()
def qapp():
    """One QApplication for widget tests, created lazily and shared."""
    from PySide6 import QtWidgets

    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app
