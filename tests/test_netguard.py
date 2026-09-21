import os

import pytest

from revolv import netguard


def test_loopback_hosts_pass():
    assert netguard.is_loopback_host("127.0.0.1")
    assert netguard.is_loopback_host("localhost")
    assert netguard.is_loopback_host("LOCALHOST")
    assert netguard.is_loopback_host("::1")
    assert netguard.is_loopback_host("[::1]")
    assert netguard.is_loopback_host("127.5.5.5")


def test_non_loopback_hosts_fail():
    assert not netguard.is_loopback_host("192.168.1.10")
    assert not netguard.is_loopback_host("example.com")
    assert not netguard.is_loopback_host("")
    assert not netguard.is_loopback_host(None)


def test_assert_loopback_accepts_local_urls():
    assert netguard.assert_loopback("http://127.0.0.1:8080/v1")
    assert netguard.assert_loopback("http://localhost:11434/v1")
    assert netguard.assert_loopback("http://[::1]:8080/v1")


def test_assert_loopback_rejects_literal_lan_address():
    with pytest.raises(netguard.EgressError):
        netguard.assert_loopback("http://192.168.1.10:8080/v1")


def test_assert_loopback_rejects_empty_host():
    with pytest.raises(netguard.EgressError):
        netguard.assert_loopback("http:///v1")


def test_apply_offline_env_when_cache_ready(monkeypatch):
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE",
                "HF_HUB_DISABLE_TELEMETRY"):
        monkeypatch.delenv(key, raising=False)
    assert netguard.apply_offline_env(cache_ready=True) is True
    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert os.environ["TRANSFORMERS_OFFLINE"] == "1"
    assert os.environ["HF_HUB_DISABLE_TELEMETRY"] == "1"


def test_apply_offline_env_first_run_keeps_downloads_possible(monkeypatch):
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE",
                "HF_HUB_DISABLE_TELEMETRY"):
        monkeypatch.delenv(key, raising=False)
    assert netguard.apply_offline_env(cache_ready=False) is False
    assert "HF_HUB_OFFLINE" not in os.environ
    assert "TRANSFORMERS_OFFLINE" not in os.environ
    # Telemetry is off regardless.
    assert os.environ["HF_HUB_DISABLE_TELEMETRY"] == "1"


def test_socket_guard_blocks_public_addresses():
    """The conftest guard itself: any non-loopback connect raises."""
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(AssertionError):
            sock.connect(("93.184.216.34", 80))
    finally:
        sock.close()
