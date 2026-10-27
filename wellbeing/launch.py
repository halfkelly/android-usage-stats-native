"""Running the app without Docker: open, stop, and the scheduled sync.

On a friend's Windows laptop there is no container: windows\\setup.ps1 puts a
Python in the project folder, the Desktop shortcut runs `pythonw -m wellbeing
open`, and the scheduled task `pythonw -m wellbeing autosync`. pythonw has no
console, so anything the user must see goes to a message box. The same
commands work in the Docker setup (autosync.sh calls autosync).
"""
from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path

from . import archive, inbox

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
LOCK_STALE_S = 30 * 60


def port() -> int:
    return int(os.environ.get("DASHBOARD_PORT") or 5000)


def url() -> str:
    return f"http://127.0.0.1:{port()}/"


def tell(text: str, title: str = "Phone Usage") -> None:
    """Print, or -- under pythonw, which has nowhere to print -- a message box."""
    # pythonw (the shortcut, the scheduled task) has no stdout at all; anything
    # else -- a console, a pipe, a log -- gets the text.
    if sys.stdout is not None or os.name != "nt":
        print(text)
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x40)
    except Exception:   # noqa: BLE001 -- a message we can't show must not crash the launcher
        print(text)


def answering(timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url(), timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def prepare() -> str | None:
    """Bootstrap and pin the archive's zone; the problem in a sentence, or None."""
    try:
        inbox.bootstrap_archive()
        archive.pin_timezone()
    except archive.ZoneMismatchError as exc:
        return str(exc)
    except archive.TimezoneError:
        return None        # no archive yet: the dashboard starts empty and sets itself up
    return None


def _pythonw() -> str:
    """pythonw.exe beside python.exe on Windows, so the server opens no window."""
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return str(w) if os.name == "nt" and w.exists() else str(exe)


def start_server(db_path: str) -> None:
    DATA.mkdir(exist_ok=True)
    log = open(DATA / "serve.log", "ab")
    cmd = [_pythonw(), "-m", "wellbeing", "--db", db_path, "serve", "--port", str(port())]
    kwargs: dict = {"cwd": str(ROOT), "stdout": log, "stderr": subprocess.STDOUT,
                    "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW: it
        # outlives the shortcut that started it, with no console of its own.
        kwargs["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)


def open_dashboard(db_path: str, browser: bool = True) -> int:
    problem = prepare()
    if problem:
        tell(f"The dashboard can't start.\n\n{problem}")
        return 1
    if not answering():
        start_server(db_path)
        for _ in range(60):
            time.sleep(0.5)
            if answering():
                break
        else:
            tell(f"The dashboard didn't start. Details are in {DATA / 'serve.log'}.")
            return 1
    if browser:
        webbrowser.open(url())
    return 0


def stop_dashboard() -> int:
    req = urllib.request.Request(url() + "api/stop", method="POST", headers={"X-Dashboard": "1"})
    try:
        urllib.request.urlopen(req, timeout=5)
    except urllib.error.HTTPError as exc:
        tell(f"The dashboard said no ({exc.code}): it runs in Docker; use Stop dashboard.bat there.")
        return 1
    except (urllib.error.URLError, OSError):
        tell("The dashboard wasn't running.")
        return 0
    tell("Dashboard stopped. The phone keeps collecting.")
    return 0


class _Stamped:
    """A log writer that puts the time in front of every line."""

    def __init__(self, fh):
        self.fh, self.fresh = fh, True

    def write(self, text: str) -> int:
        for part in text.splitlines(keepends=True):
            if self.fresh:
                self.fh.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S "))
            self.fh.write(part)
            self.fresh = part.endswith("\n")
        return len(text)

    def flush(self) -> None:
        self.fh.flush()


@contextlib.contextmanager
def _lock():
    """One sync at a time; a lock older than 30 minutes is a crashed run's."""
    path = DATA / ".autosync.lock"
    try:
        if time.time() - path.stat().st_mtime > LOCK_STALE_S:
            path.unlink()
    except OSError:
        pass
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        yield False
        return
    try:
        os.write(fd, str(os.getpid()).encode())
        yield True
    finally:
        os.close(fd)
        with contextlib.suppress(OSError):
            path.unlink()


def _trim(log: Path, keep: int = 500, over: int = 800) -> None:
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    except OSError:
        return
    if len(lines) > over:
        log.write_text("".join(lines[-keep:]), encoding="utf-8")


def autosync(db_path: str, ingest) -> int:
    """The scheduled sync: read the phone's new uploads into the database and
    the archive, logging to data/autosync.log. Quietly does nothing when the
    phone hasn't uploaded yet or another sync is running. `ingest` is the
    ingest-phone command, passed in to avoid an import cycle."""
    DATA.mkdir(exist_ok=True)
    log_path = DATA / "autosync.log"
    _trim(log_path)
    with contextlib.suppress(Exception):     # log times in the archive's zone from the first line
        archive.pin_timezone()
    with open(log_path, "a", encoding="utf-8") as fh:
        out = _Stamped(fh)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            with _lock() as mine:
                if not mine:
                    print("a sync is already running; skipping")
                    return 0
                box = inbox.inbox_dir()
                if box is None or not box.is_dir():
                    print(f"no phone uploads at {box or 'My Drive/PhoneUsage/phone'} yet "
                          f"(is Google Drive running, and the phone app connected?); skipping")
                    return 0
                problem = prepare()
                if problem:
                    print(f"error: {problem}")
                    return 1
                print("reading the phone's uploads")
                code = ingest(db_path)
                print("done")
                return code
