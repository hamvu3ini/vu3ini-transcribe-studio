"""Start the local server: python -m server.run --port 0 --port-file <file>"""
import argparse
import os
import socket
import sys
from pathlib import Path


def free_port(preferred: int = 0) -> int:
    for p in ([preferred] if preferred else []) + [0]:
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", p))
            port = s.getsockname()[1]
            s.close()
            return port
        except OSError:
            s.close()
    raise RuntimeError("No free port")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--port-file")
    a = ap.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from server import netguard
    netguard.install()
    import uvicorn
    from server import main as m
    port = free_port(a.port)
    cfg = uvicorn.Config(m.app, host="127.0.0.1", port=port, log_level="warning", ws_max_size=16 * 1024 * 1024,
                         access_log=False)
    srv = uvicorn.Server(cfg)
    m.SERVER["uvicorn"] = srv
    if a.port_file:
        Path(a.port_file).write_text(str(port))
    srv.run()
    os._exit(0)


if __name__ == "__main__":
    main()
