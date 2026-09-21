"""Phase 1's network promise, enforced in code.

Two jobs. `assert_loopback` is called wherever new code is handed a URL, so a
provider endpoint that is not this machine fails at construction rather than at
request time. `apply_offline_env` sets the HuggingFace and transformers offline
switches at start-up, so a source run behaves like the frozen bundle (whose
runtime hook already disables telemetry) and a cached model can never phone
home for a freshness check mid-run.

Everything here is standard library on purpose: it runs before the pipeline
imports and must never be the thing that drags torch in.
"""

import ipaddress
import os
import socket
from pathlib import Path
from urllib.parse import urlsplit


class EgressError(RuntimeError):
    """A URL or address that would leave this machine in Phase 1."""


_LOOPBACK_NAMES = {"localhost", "localhost.localdomain"}


def is_loopback_host(host) -> bool:
    """True when `host` is a loopback name or literal, without resolving it."""
    host = (host or "").strip().strip("[]").lower()
    if not host:
        return False
    if host in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def assert_loopback(url: str) -> str:
    """Raise EgressError unless every address `url` can reach is loopback.

    A bare loopback literal or `localhost` passes without a DNS query. Any
    other name is resolved, and every address it maps to must be loopback: a
    name with one public A record beside 127.0.0.1 is a way out and fails.
    """
    parts = urlsplit(url if "//" in url else "//" + url)
    host = parts.hostname
    if not host:
        raise EgressError("No host in URL: {0!r}".format(url))
    if is_loopback_host(host):
        return url
    try:
        infos = socket.getaddrinfo(host, parts.port or 80, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise EgressError(
            "Could not resolve {0!r} to check it stays on this machine ({1}). "
            "Use 127.0.0.1 or localhost.".format(host, exc)) from exc
    addresses = {info[4][0] for info in infos}
    for address in addresses:
        try:
            if not ipaddress.ip_address(address).is_loopback:
                raise EgressError(
                    "{0!r} resolves to {1}, which is not this machine. Phase 1 "
                    "allows loopback endpoints only.".format(host, address))
        except ValueError as exc:
            raise EgressError(
                "{0!r} resolved to an unreadable address {1!r}".format(
                    host, address)) from exc
    return url


def _hub_cache_dir() -> Path:
    """Where huggingface_hub keeps models, without importing it."""
    for var in ("HF_HUB_CACHE",):
        value = os.environ.get(var)
        if value:
            return Path(value)
    home = os.environ.get("HF_HOME")
    if home:
        return Path(home) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def models_cached() -> bool:
    """A cheap proxy for 'the first-run download has happened'."""
    try:
        return any(_hub_cache_dir().glob("models--*"))
    except OSError:
        return False


def apply_offline_env(cache_ready=None) -> bool:
    """Set the offline switches. Returns True when offline mode was applied.

    Telemetry is always disabled. The offline flags themselves are set only
    once the model cache exists: on a genuinely first run they would turn the
    unavoidable download into an immediate failure, which serves nobody.
    `cache_ready` overrides the detection either way, for tests and for a
    caller that knows better.
    """
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    ready = models_cached() if cache_ready is None else bool(cache_ready)
    if ready:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    return ready
