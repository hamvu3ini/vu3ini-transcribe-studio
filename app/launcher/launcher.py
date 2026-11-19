"""VU3INI Transcribe Studio launcher.

Starts the local server silently on a free 127.0.0.1 port, shows a tray icon
(Open, Stop / Exit), opens the default browser, allows a single instance only and
makes sure every child process is gone when the app exits.
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent          # .../app
ROOT = APP_DIR.parent                                      # install folder
sys.path.insert(0, str(APP_DIR))
from server import config  # noqa: E402  (paths only; does not start anything)

RUN_DIR = config.DATA_DIR / "run"
RUN_DIR.mkdir(parents=True, exist_ok=True)
PORT_FILE = RUN_DIR / "port"
LOG = config.LOG_DIR / "launcher.log"
WIN = sys.platform == "win32"
NO_WINDOW = 0x08000000


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")


def message_box(text, title=config.APP_NAME):
    if WIN:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)
    else:
        print(title + ": " + text)


# ---------------------------------------------------------------- single instance
class SingleInstance:
    def __init__(self):
        self.ok = True
        if WIN:
            import ctypes
            self.k = ctypes.windll.kernel32
            self.h = self.k.CreateMutexW(None, False, "Local\\VU3INI-Transcribe-Studio")
            if self.k.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
                self.ok = False
        else:
            import fcntl
            self.f = open(RUN_DIR / "instance.lock", "w")
            try:
                fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self.ok = False


# ---------------------------------------------------------------- job object: children die with us
def make_kill_on_close_job():
    if not WIN:
        return None
    import ctypes
    from ctypes import wintypes
    k = ctypes.windll.kernel32

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

    class BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class EXTENDED(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO_COUNTERS), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    job = k.CreateJobObjectW(None, None)
    info = EXTENDED()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    k.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
    return job


def assign_to_job(job, proc):
    if job is None:
        return
    import ctypes
    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1F0FFF, False, proc.pid)
    k.AssignProcessToJobObject(job, h)
    k.CloseHandle(h)


# ---------------------------------------------------------------- server
def python_exe():
    for cand in (ROOT / "python" / "pythonw.exe", ROOT / "python" / "python.exe"):
        if cand.exists():
            return str(cand)
    return sys.executable


def ping(port, timeout=1.5):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=timeout) as r:
            return json.loads(r.read()).get("ok")
    except Exception:
        return False


def kill_tree(pid):
    try:
        import psutil
        p = psutil.Process(pid)
        kids = p.children(recursive=True)
        for c in kids + [p]:
            try:
                c.kill()
            except Exception:
                pass
        psutil.wait_procs(kids + [p], timeout=5)
    except Exception:
        pass


class App:
    def __init__(self):
        self.proc = None
        self.port = None
        self.icon = None
        self.job = make_kill_on_close_job()
        self.stopping = threading.Event()

    def url(self):
        return f"http://127.0.0.1:{self.port}/"

    def start_server(self):
        PORT_FILE.unlink(missing_ok=True)
        env = dict(os.environ)
        env["PYTHONPATH"] = str(APP_DIR)
        env["PYTHONIOENCODING"] = "utf-8"
        # keep bundled FFmpeg first on PATH
        env["PATH"] = str(ROOT / "ffmpeg") + os.pathsep + env.get("PATH", "")
        out = open(config.LOG_DIR / "server-stdout.log", "a", encoding="utf-8")
        self.proc = subprocess.Popen(
            [python_exe(), "-m", "server.run", "--port", "0", "--port-file", str(PORT_FILE)],
            cwd=str(APP_DIR), env=env, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            creationflags=NO_WINDOW if WIN else 0)
        assign_to_job(self.job, self.proc)
        t0 = time.time()
        while time.time() - t0 < 180:
            if self.proc.poll() is not None:
                raise RuntimeError("The engine stopped while starting. See logs in " + str(config.LOG_DIR))
            if PORT_FILE.exists():
                try:
                    self.port = int(PORT_FILE.read_text().strip())
                except ValueError:
                    self.port = None
                if self.port and ping(self.port):
                    log(f"server up on port {self.port} (pid {self.proc.pid})")
                    return
            time.sleep(0.25)
        raise RuntimeError("The engine did not start within 3 minutes.")

    def open(self, *_):
        webbrowser.open(self.url())

    def stop(self, *_):
        if self.stopping.is_set():
            return
        self.stopping.set()
        log("stopping")
        try:
            req = urllib.request.Request(self.url() + "api/shutdown", method="POST", data=b"")
            urllib.request.urlopen(req, timeout=3).read()
        except Exception:
            pass
        if self.proc:
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                pass
            if self.proc.poll() is None:
                kill_tree(self.proc.pid)
        PORT_FILE.unlink(missing_ok=True)
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass

    def watch(self):
        # If the server exits (e.g. "Shut down" in the page), close the launcher too.
        while not self.stopping.is_set():
            if self.proc and self.proc.poll() is not None:
                log("server exited; closing launcher")
                self.stop()
                break
            time.sleep(0.5)

    def run_tray(self):
        if os.environ.get("VTS_NO_TRAY") == "1":
            while not self.stopping.is_set():
                time.sleep(0.5)
            return
        import pystray
        from PIL import Image
        img = Image.open(APP_DIR / "web" / "assets" / "logo-96.png")
        menu = pystray.Menu(pystray.MenuItem("Open", self.open, default=True),
                            pystray.MenuItem("Stop / Exit", self.stop))
        self.icon = pystray.Icon("vu3ini-transcribe", img, f"{config.APP_NAME} {config.VERSION}", menu)
        self.icon.run()


def main():
    inst = SingleInstance()
    if not inst.ok:
        # Already running: bring it forward by opening its page.
        try:
            port = int(PORT_FILE.read_text().strip())
            if ping(port):
                webbrowser.open(f"http://127.0.0.1:{port}/")
                return 0
        except Exception:
            pass
        message_box("VU3INI Transcribe Studio is already starting. Please wait a moment.")
        return 0
    app = App()
    try:
        app.start_server()
    except Exception as e:  # noqa: BLE001
        log("start failed: " + str(e))
        if app.proc and app.proc.poll() is None:
            kill_tree(app.proc.pid)
        message_box("VU3INI Transcribe Studio could not start:\n\n" + str(e))
        return 1
    if os.environ.get("VTS_NO_BROWSER") != "1":
        app.open()
    threading.Thread(target=app.watch, daemon=True).start()
    try:
        app.run_tray()
    finally:
        app.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
