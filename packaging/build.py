"""Build the offline Windows package of VU3INI Transcribe Studio (runs on Linux or Windows).

  python packaging/build.py            # bump patch version (1.0.0 -> 1.0.1) and build
  python packaging/build.py --no-bump  # rebuild the current version

Steps: fetch Windows Python 3.12 + FFmpeg (conda-forge win-64), download Windows wheels
from PyPI, assemble the app folder, build the launcher exe and the per-user installer with
NSIS, then zip everything (split into <500 MB parts with a join .bat when needed).
"""
import argparse
import fnmatch
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "packaging"
CACHE = Path(os.environ.get("VTS_BUILD_CACHE", ROOT.parent / "build-cache"))
BUILD = ROOT.parent / "build"
APP_NAME = "VU3INI Transcribe Studio"
ZIP_BASE = "VU3INI-Transcribe-Studio"
PY = "3.12"
CF = "https://conda.anaconda.org/conda-forge"

WHEELS = [
    "fastapi", "uvicorn", "websockets", "h11", "python-multipart", "faster-whisper", "ctranslate2", "sherpa-onnx",
    "numpy", "soundfile", "python-docx", "fpdf2", "uharfbuzz", "psutil", "indic-nlp-library", "sentencepiece",
    "transformers", "pystray", "pillow", "colorama", "huggingface_hub", "tokenizers", "onnxruntime", "av",
]
# Windows-only dependencies that pip does not pick up when resolving from Linux
EXTRA_WIN = ["colorama", "tzdata"]
# PyTorch is fetched without dependency resolution (pip would evaluate its Linux-only
# CUDA markers on this build machine); its real Windows dependencies are listed here.
TORCH = "torch"
TORCH_DEPS = ["sympy", "networkx", "jinja2", "fsspec", "filelock", "typing-extensions", "setuptools", "mpmath", "markupsafe"]


def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


def fetch(url: str, dst: Path) -> Path:
    if dst.exists() and dst.stat().st_size > 0:
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    log("download", url)
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, 4 << 20)
    tmp.replace(dst)
    return dst


# ---------------------------------------------------------------- conda-forge mini resolver
class Conda:
    def __init__(self, subdir="win-64"):
        self.records = {}
        for sd in (subdir, "noarch"):
            p = fetch(f"{CF}/{sd}/repodata.json", CACHE / f"repodata-{sd}.json")
            d = json.loads(p.read_text())
            for fn, m in {**d.get("packages", {}), **d.get("packages.conda", {})}.items():
                m = dict(m, fn=fn, subdir=sd)
                self.records.setdefault(m["name"], []).append(m)

    @staticmethod
    def _ver(v):
        try:
            return Version(v)
        except InvalidVersion:
            return Version("0")

    @staticmethod
    def _match(version, spec):
        if not spec or spec == "*":
            return True
        for alt in spec.split("|"):
            ok = True
            for part in alt.split(","):
                part = part.strip()
                if not part:
                    continue
                if part.endswith(".*") and not part.startswith(("<", ">", "!", "=")):
                    ok &= version.startswith(part[:-1]) or version == part[:-2]
                elif part[0].isdigit():
                    # conda: a bare version is fuzzy ("1.2" matches 1.2, 1.2.0, 1.2.5)
                    ok &= version == part or version.startswith(part + ".")
                else:
                    try:
                        ok &= Conda._ver(version) in SpecifierSet(part.replace(".*", ""), prereleases=True)
                    except Exception:
                        ok &= True
            if ok:
                return True
        return False

    def best(self, dep: str):
        parts = dep.split()
        name, vspec = parts[0], parts[1] if len(parts) > 1 else ""
        bspec = parts[2] if len(parts) > 2 else ""
        cands = [m for m in self.records.get(name, []) if self._match(m["version"], vspec)
                 and (not bspec or fnmatch.fnmatch(m["build"], bspec))]
        if not cands:
            return None
        return max(cands, key=lambda m: (self._ver(m["version"]), m.get("build_number", 0), m.get("timestamp", 0)))

    def resolve(self, roots, skip=()):
        """Pick the newest version of each package. When two packages need incompatible versions of
        the same library (e.g. icu 78 and icu 79), both versions are kept: Windows DLL names carry the
        major version (icuuc78.dll / icuuc79.dll), so they install side by side."""
        out, todo, seen, wants = {}, list(roots), set(), {}
        while todo:
            dep = todo.pop(0)
            name = dep.split()[0]
            if name in skip or name.startswith("__"):
                continue
            wants.setdefault(name, []).append(dep)
            if name in seen:
                continue
            m = self.best(dep)
            if m is None:
                log("  (conda) no match for", dep)
                continue
            seen.add(name)
            out[name] = m
            todo += m.get("depends", [])
        extra = {}
        for name, deps in wants.items():
            chosen = out.get(name)
            if not chosen:
                continue
            for dep in deps:
                parts = dep.split()
                if len(parts) > 1 and not self._match(chosen["version"], parts[1]):
                    alt = self.best(dep)
                    if alt and alt["fn"] != chosen["fn"]:
                        extra[f"{name}@{alt['version']}"] = alt
        for k, m in extra.items():
            log("  (conda) also bundling", k, "for a package that needs it")
        return {**extra, **out}  # newest last, so its files win where names clash

    def extract(self, rec, dest: Path):
        f = fetch(f"{CF}/{rec['subdir']}/{rec['fn']}", CACHE / "conda" / rec["fn"])
        if rec["fn"].endswith(".conda"):
            import zstandard
            with zipfile.ZipFile(f) as z:
                for inner in z.namelist():
                    if inner.startswith("pkg-") and inner.endswith(".tar.zst"):
                        data = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(z.read(inner)))
                        with tarfile.open(fileobj=data, mode="r|") as t:
                            t.extractall(dest, filter="data")
        else:
            with tarfile.open(f) as t:
                t.extractall(dest, filter="data")


# ---------------------------------------------------------------- steps
def bump(no_bump: bool) -> str:
    vf = ROOT / "VERSION"
    v = vf.read_text().strip() if vf.exists() else "1.0.0"
    if not no_bump:
        a, b, c = (int(x) for x in v.split("."))
        v = f"{a}.{b}.{c + 1}"
        vf.write_text(v + "\n")
    log("version", v)
    return v


def build_python(conda: Conda, dest: Path):
    log("Windows Python", PY)
    recs = conda.resolve([f"python {PY}.* *_cpython"], skip={"pip", "setuptools", "wheel"})
    stage = BUILD / "conda-python"
    shutil.rmtree(stage, ignore_errors=True)
    for r in recs.values():
        log("  +", r["name"], r["version"])
        conda.extract(r, stage)
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    for item in ("python.exe", "pythonw.exe", "Lib", "DLLs", "LICENSE.txt"):
        src = stage / item
        if src.is_dir():
            shutil.copytree(src, dest / item, ignore=shutil.ignore_patterns("test", "tests", "idlelib", "__pycache__", "ensurepip", "tkinter", "turtledemo"))
        elif src.exists():
            shutil.copy2(src, dest / item)
    # every runtime DLL next to python.exe so extension modules always find them
    for d in (stage, stage / "Library" / "bin"):
        for dll in d.glob("*.dll"):
            shutil.copy2(dll, dest / dll.name)
    (dest / "Lib" / "site-packages").mkdir(parents=True, exist_ok=True)
    lic = BUILD / "licences-src" / "python"
    lic.mkdir(parents=True, exist_ok=True)
    for f in stage.glob("info/licenses/**/*"):
        if f.is_file():
            shutil.copy2(f, lic / f.name)
    if (stage / "LICENSE.txt").exists():
        shutil.copy2(stage / "LICENSE.txt", lic / "Python-LICENSE.txt")
    return {r["name"]: r["version"] for r in recs.values()}


def build_ffmpeg(conda: Conda, dest: Path):
    log("Windows FFmpeg (LGPL build)")
    root = conda.best("ffmpeg * *lgpl*")
    recs = conda.resolve([f"ffmpeg {root['version']} {root['build']}"], skip={"fonts-conda-ecosystem", "fonts-conda-forge", "python"})
    stage = BUILD / "conda-ffmpeg"
    shutil.rmtree(stage, ignore_errors=True)
    for r in recs.values():
        conda.extract(r, stage)
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    for f in (stage / "Library" / "bin").glob("*"):
        if f.suffix.lower() == ".dll" or f.name.lower() in ("ffmpeg.exe", "ffprobe.exe"):
            shutil.copy2(f, dest / f.name)
    lic = BUILD / "licences-src" / "ffmpeg"
    lic.mkdir(parents=True, exist_ok=True)
    for f in stage.rglob("info/licenses/*"):
        if f.is_file():
            shutil.copy2(f, lic / f.name)
    log("  ffmpeg + %d libraries" % len(list(dest.glob("*.dll"))))
    return root["version"]


def build_wheels(site: Path):
    log("Windows wheels from PyPI")
    wd = CACHE / "wheels"
    wd.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "pip", "download", "--only-binary=:all:", "--platform", "win_amd64",
           "--python-version", PY, "--implementation", "cp", "--abi", "cp312", "-d", str(wd)]
    subprocess.run(cmd + [*WHEELS, *EXTRA_WIN, *TORCH_DEPS], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(cmd + ["--no-deps", TORCH], check=True, stdout=subprocess.DEVNULL)
    names = {}
    for whl in sorted(wd.glob("*.whl")):
        dist = whl.name.split("-")[0].lower()
        if not (whl.name.endswith("win_amd64.whl") or "none-any" in whl.name or "abi3-win_amd64" in whl.name):
            continue
        prev = names.get(dist)
        if prev is None or Version(whl.name.split("-")[1]) > Version(prev.name.split("-")[1]):
            names[dist] = whl
    lic = BUILD / "licences-src" / "python-packages"
    lic.mkdir(parents=True, exist_ok=True)
    for dist, whl in sorted(names.items()):
        with zipfile.ZipFile(whl) as z:
            for n in z.namelist():
                parts = n.split("/")
                if ".data" in parts[0] and len(parts) > 2:
                    # {dist}.data/{purelib|platlib|data|scripts}/...
                    if parts[1] in ("purelib", "platlib"):
                        target = site / "/".join(parts[2:])
                    else:
                        continue
                else:
                    target = site / n
                if n.endswith("/"):
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(n) as s, open(target, "wb") as d:
                    shutil.copyfileobj(s, d)
                low = n.lower()
                if ".dist-info/" in low and re.search(r"(licen[cs]e|copying|notice)", low.split(".dist-info/")[1]):
                    out = lic / f"{dist}-{Path(n).name}"
                    if not out.suffix:
                        out = out.with_suffix(".txt")
                    out.write_bytes(z.read(n))
    # remove bulky parts the app never uses
    for junk in ("torch/include", "torch/share", "torch/test", "torch/lib/*.lib", "caffe2", "sympy/*/tests",
                 "**/tests/**/*.py", "torchgen"):
        for p in site.glob(junk):
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
    log(f"  {len(names)} packages installed")
    return sorted(names)


def write_licences(dist: Path, py_ver, ff_ver, pkgs):
    lic = dist / "licences"
    shutil.rmtree(lic, ignore_errors=True)
    shutil.copytree(BUILD / "licences-src", lic)
    fonts = lic / "fonts"
    fonts.mkdir(exist_ok=True)
    for f in (PKG / "third_party").glob("*"):
        shutil.copy2(f, fonts / f.name) if f.is_file() else None
    sys.path.insert(0, str(ROOT / "app"))
    from server import components
    lines = [f"{APP_NAME} — third-party components", "=" * 60, "", "Source credits:"]
    lines += [f"  - {s['name']}: {s['url']} ({s['licence']})" for s in components.SOURCES]
    lines += ["", "Bundled components:"] + [f"  - {n}: {l}" for n, l in components.COMPONENTS]
    lines += ["", f"Python runtime {py_ver.get('python')} from conda-forge; FFmpeg {ff_ver} (LGPL build) from conda-forge.",
              "FFmpeg is used as separate executables (ffmpeg.exe / ffprobe.exe), unmodified.",
              "Corresponding source code: https://github.com/conda-forge/ffmpeg-feedstock and https://ffmpeg.org/download.html",
              "", "Python packages included:", *[f"  - {p}" for p in pkgs],
              "", "Licence texts are in the sub-folders of this folder."]
    (lic / "THIRD-PARTY-NOTICES.txt").write_text("\n".join(lines), encoding="utf-8")


def assemble(version: str, rebuild_runtime: bool):
    dist = BUILD / "dist" / APP_NAME
    rt = BUILD / "runtime"
    if rebuild_runtime or not (rt / "runtime.json").exists():
        conda = Conda()
        py_ver = build_python(conda, rt / "python")
        pkgs = build_wheels(rt / "python" / "Lib" / "site-packages")
        ff_ver = build_ffmpeg(conda, rt / "ffmpeg")
        (rt / "runtime.json").write_text(json.dumps({"python": py_ver, "ffmpeg": ff_ver, "packages": pkgs}))
    meta = json.loads((rt / "runtime.json").read_text())
    log("assembling", dist)
    shutil.rmtree(dist, ignore_errors=True)
    dist.mkdir(parents=True)
    shutil.copytree(rt / "python", dist / "python", ignore=shutil.ignore_patterns("__pycache__"))
    # documentation tools pulled in by indic-nlp-library's metadata; never used at run time
    site = dist / "python" / "Lib" / "site-packages"
    for pat in ("sphinx*", "babel", "babel-*", "docutils*", "alabaster*", "imagesize*", "snowballstemmer*",
                "sphinxcontrib*", "roman_numerals*", "Sphinx*"):
        for p in site.glob(pat):
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
    shutil.copytree(rt / "ffmpeg", dist / "ffmpeg")
    ign = shutil.ignore_patterns("__pycache__", "*.pyc")
    (dist / "app").mkdir()
    for sub in ("server", "web", "launcher", "tools"):
        shutil.copytree(ROOT / "app" / sub, dist / "app" / sub, ignore=ign)
    (dist / "VERSION").write_text(version + "\n")
    shutil.copy2(ROOT / "app" / "web" / "assets" / "app.ico", dist / "app.ico")
    # python path file so the bundled interpreter finds the app and nothing from the PC
    (dist / "python" / "python312._pth").unlink(missing_ok=True)
    write_licences(dist, meta["python"], meta["ffmpeg"], meta["packages"])
    for sub, search in (("ffmpeg", [dist / "ffmpeg"]), ("python", [dist / "python"])):
        miss = check_imports(dist / sub, search)
        # CUDA libraries come from the optional GPU runtime pack; they are loaded only when it is installed
        miss = {k: v for k, v in miss.items() if not k.startswith(("cublas", "cudnn", "cudart", "nvrtc", "cufft", "curand", "cusparse", "cusolver", "nvjitlink", "nccl"))}
        if miss:
            for k, v in sorted(miss.items()):
                log(f"  MISSING {k} needed by {', '.join(v[:3])}{' …' if len(v) > 3 else ''}")
            if not os.environ.get("VTS_IGNORE_MISSING"):
                raise SystemExit(f"{sub}: {len(miss)} required DLL(s) are missing (see above)")
        log(f"  {sub}: every required DLL is present")
    terms = (PKG / "TERMS.txt").read_text(encoding="utf-8")
    (dist / "TERMS.txt").write_text(terms, encoding="utf-8")
    readme = (PKG / "README_FIRST.txt").read_text(encoding="utf-8").replace("{{VERSION}}", version)
    (dist / "README_FIRST.txt").write_text(readme, encoding="utf-8")
    return dist, meta


SYSTEM_DLLS = {
    "kernel32", "user32", "gdi32", "advapi32", "shell32", "ole32", "oleaut32", "comdlg32", "comctl32", "ws2_32",
    "wsock32", "bcrypt", "bcryptprimitives", "crypt32", "secur32", "ncrypt", "iphlpapi", "dbghelp", "psapi", "shlwapi",
    "setupapi", "version", "winmm", "imm32", "msvcrt", "ntdll", "rpcrt4", "userenv", "netapi32", "mpr", "winhttp",
    "wininet", "uxtheme", "dwmapi", "d3d9", "d3d11", "d3d12", "dxgi", "dxva2", "mfplat", "mfuuid", "mf", "mfreadwrite",
    "evr", "strmiids", "opengl32", "glu32", "avrt", "ksuser", "propsys", "powrprof", "cfgmgr32", "dwrite", "d2d1",
    "windowscodecs", "usp10", "msimg32", "oleacc", "hid", "winspool.drv", "mswsock", "dnsapi", "wtsapi32", "wintrust",
    "normaliz", "credui", "cabinet", "ntdll", "ucrtbase", "msvcp_win", "combase", "shcore", "dcomp", "d3dcompiler_47",
    "vcomp140", "vulkan-1", "nvcuda", "dbgeng", "authz", "sspicli", "msi", "wldap32", "winusb", "api-ms-win-core-path-l1-1-0", "avicap32", "imagehlp", "pdh", "msacm32", "msvfw32", "mfcore",
}


def check_imports(folder: Path, search: list[Path]):
    """Fail the build if any .exe/.dll/.pyd needs a DLL that is neither bundled nor part of Windows."""
    import pefile
    have = {p.name.lower() for d in search for p in d.rglob("*") if p.suffix.lower() in (".dll", ".pyd", ".exe")}
    missing = {}
    for f in folder.rglob("*"):
        if f.suffix.lower() not in (".dll", ".exe", ".pyd"):
            continue
        try:
            pe = pefile.PE(str(f), fast_load=True)
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                                                   pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"]])
        except Exception:
            continue
        delayed = {e.dll.decode().lower() for e in getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", [])}
        for e in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
            dll = e.dll.decode().lower()
            stem = dll[:-4] if dll.endswith(".dll") else dll
            if dll in have or dll in delayed or stem in SYSTEM_DLLS or dll.startswith(("api-ms-win-", "ext-ms-")):
                continue
            missing.setdefault(dll, []).append(str(f.relative_to(folder)))
    return missing


def nsis_bin() -> str:
    mk = shutil.which("makensis")
    if mk:
        return mk
    env = CACHE / "nsis"
    exe = env / "bin" / "makensis"
    if not exe.exists():
        log("fetching NSIS (conda-forge linux-64)")
        shutil.rmtree(env, ignore_errors=True)
        c = Conda("linux-64")
        c.records["nsis"] = [m for m in c.records["nsis"] if m["subdir"] == "linux-64"]
        for r in c.resolve(["nsis"]).values():
            c.extract(r, env)
    return str(exe)


def run_nsis(script: Path, defines: dict):
    exe = nsis_bin()
    env = dict(os.environ)
    nsisdir = Path(exe).parent.parent / "share" / "nsis"
    if nsisdir.exists():
        env["NSISDIR"] = str(nsisdir)
    env["LD_LIBRARY_PATH"] = str(Path(exe).parent.parent / "lib") + ":" + env.get("LD_LIBRARY_PATH", "")
    args = [exe, "-V2"] + [f"-D{k}={v}" for k, v in defines.items()] + [str(script)]
    log("makensis", script.name)
    subprocess.run(args, check=True, env=env)


def package(dist: Path, version: str):
    out = BUILD / "out"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    common = {"APPNAME": APP_NAME, "VERSION": version, "DIST": str(dist), "ICON": str(dist / "app.ico"),
              "OUTDIR": str(out), "PKGDIR": str(PKG)}
    # launcher exe goes inside the app folder before the installer is compiled
    run_nsis(PKG / "nsis" / "launcher.nsi", {**common, "OUTFILE": str(dist / f"{APP_NAME}.exe"),
                                              "TARGET": "app\\launcher\\launcher.py", "WINDOWED": "1"})
    installer = out / f"{ZIP_BASE}-Setup-v{version}.exe"
    run_nsis(PKG / "nsis" / "installer.nsi", {**common, "OUTFILE": str(installer)})
    stage = out / f"{ZIP_BASE}-v{version}"
    stage.mkdir()
    shutil.copy2(installer, stage / installer.name)
    for f in ("README_FIRST.txt", "TERMS.txt"):
        shutil.copy2(dist / f, stage / f)
    shutil.copytree(dist / "licences", stage / "licences")
    z = out / f"{ZIP_BASE}-v{version}.zip"
    log("zipping", z.name)
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for f in sorted(stage.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(stage.parent).as_posix(),
                         compress_type=zipfile.ZIP_STORED if f.suffix == ".exe" else zipfile.ZIP_DEFLATED)
    shutil.rmtree(stage)
    sha = hashlib.sha256(z.read_bytes()).hexdigest().upper()
    size = z.stat().st_size
    log(f"zip {size / 1e6:.0f} MB sha256 {sha}")
    parts = [z]
    limit = 499 * 1000 * 1000
    if size > limit:
        parts = []
        with open(z, "rb") as f:
            i = 1
            while chunk := f.read(limit):
                p = out / f"{z.name}.{i:03d}"
                p.write_bytes(chunk)
                parts.append(p)
                i += 1
        z.unlink()
        bat = out / f"JOIN-{ZIP_BASE}-v{version}.bat"
        bat.write_text("\r\n".join([
            "@echo off", "setlocal", "cd /d \"%~dp0\"",
            f"echo Joining {len(parts)} parts into {z.name} ...",
            f"copy /b {'+'.join(p.name for p in parts)} \"{z.name}\" >nul || goto :fail",
            "echo Checking SHA-256 ...",
            f"for /f \"skip=1 tokens=* delims=\" %%h in ('certutil -hashfile \"{z.name}\" SHA256 ^| findstr /v \":\"') do (set H=%%h & goto :got)",
            ":got", "set H=%H: =%",
            f"if /i \"%H%\"==\"{sha}\" (echo OK - the zip is complete and undamaged. & echo You can now extract {z.name}. & pause & exit /b 0)",
            "echo ERROR: checksum does not match. Download the parts again.", "pause", "exit /b 1",
            ":fail", "echo ERROR: a part is missing. Put all parts in this folder and run again.", "pause", "exit /b 1", ""]),
            encoding="utf-8")
        parts.append(bat)
    (out / f"{ZIP_BASE}-v{version}.sha256.txt").write_text(f"{sha}  {z.name}\n")
    installer.unlink()
    return out, parts, sha


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-bump", action="store_true")
    ap.add_argument("--rebuild-runtime", action="store_true", help="download Python, wheels and FFmpeg again")
    a = ap.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(PKG / "help_src.py")], check=True)
    version = bump(a.no_bump)
    dist, _ = assemble(version, a.rebuild_runtime)
    out, parts, sha = package(dist, version)
    log("DONE ->", out)
    for p in sorted(out.iterdir()):
        log(f"   {p.name}  {p.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
