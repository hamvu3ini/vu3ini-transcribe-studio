"""Keep the app strictly offline.

Installs a guard on outbound sockets so that any attempt to reach a non-loopback
address is refused and logged. Also sets the offline switches understood by the
Hugging Face libraries, so nothing tries to phone home.
"""
import ipaddress
import logging
import os
import socket
import threading
import time

log = logging.getLogger("vts.netguard")
_attempts = []
_lock = threading.Lock()
_installed = False

OFFLINE_ENV = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "DO_NOT_TRACK": "1",
    "TOKENIZERS_PARALLELISM": "false",
}


def _is_local(host) -> bool:
    if host in (None, "", "localhost"):
        return True
    try:
        ip = ipaddress.ip_address(str(host).split("%")[0])
        return ip.is_loopback or ip.is_unspecified
    except ValueError:
        return str(host).lower() in ("localhost", "localhost.localdomain")


def _record(host, port, kind):
    with _lock:
        _attempts.append({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "host": str(host), "port": port, "via": kind})
        del _attempts[:-200]
    log.warning("Blocked outbound network attempt to %s:%s (%s)", host, port, kind)


def attempts():
    with _lock:
        return list(_attempts)


def install():
    global _installed
    for k, v in OFFLINE_ENV.items():
        os.environ.setdefault(k, v)
    if _installed:
        return
    _installed = True

    orig_connect = socket.socket.connect
    orig_connect_ex = socket.socket.connect_ex
    orig_getaddrinfo = socket.getaddrinfo

    def _target(address):
        if isinstance(address, tuple) and address:
            return address[0], (address[1] if len(address) > 1 else None)
        return None, None  # AF_UNIX etc.

    def connect(self, address):
        host, port = _target(address)
        if self.family in (socket.AF_INET, socket.AF_INET6) and not _is_local(host):
            _record(host, port, "connect")
            raise ConnectionRefusedError(f"Offline mode: outbound connection to {host} blocked")
        return orig_connect(self, address)

    def connect_ex(self, address):
        host, port = _target(address)
        if self.family in (socket.AF_INET, socket.AF_INET6) and not _is_local(host):
            _record(host, port, "connect_ex")
            return 111
        return orig_connect_ex(self, address)

    def getaddrinfo(host, port, *a, **kw):
        if not _is_local(host if not isinstance(host, bytes) else host.decode()):
            _record(host, port, "dns")
            raise socket.gaierror(socket.EAI_NONAME, f"Offline mode: name lookup for {host} blocked")
        return orig_getaddrinfo(host, port, *a, **kw)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.getaddrinfo = getaddrinfo
