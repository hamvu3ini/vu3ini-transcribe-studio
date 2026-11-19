"""Run the test suite with networking disabled (Linux): a fresh network namespace with only loopback.
Usage: unshare -n python tests/run_offline.py [pytest args]"""
import fcntl, socket, struct, subprocess, sys
s = socket.socket()
fcntl.ioctl(s, 0x8914, struct.pack("16sH14s", b"lo", 0x1 | 0x8 | 0x40, b"\0" * 14))  # SIOCSIFFLAGS: lo up
sys.exit(subprocess.call([sys.executable, "-m", "pytest", *sys.argv[1:]]))
