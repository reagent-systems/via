"""The `engine` marker and its guard, for every test of this folder (tools/ci/engine_marker.py), and
the session's notice file of the engine lock.

A test file takes `engine` from here (`from conftest import engine`): a design file a test writes
imports its test file in a child process, where only this folder is on sys.path.

The engine lock is shared by every run on the machine, test sessions too (tools/enginelock.py): a
session's long commands wait while another session's run holds it. A waiting run prints 2 lines, and
a test that compares the whole of stderr would fail on them. So the session names 1 file for those
lines (`WORKCENTER_LOCK_LOG`), once, before any test, and every process a test starts inherits it. The
summary prints what the file holds; the lock's own tests take the variable out and read stderr.

Where each test file runs is verify/desktop.csv's: `desktop` (Linux, macOS and Windows), `posix` (not
Windows) or `linux`. On a system its row leaves out, the file is skipped as it is collected, before its
import, with the row's reason: the run's `not judged:` lines name it, and Windows never imports a file
that needs fcntl or pwd. 1 test of a desktop file that cannot run somewhere carries `posix_only(...)` or
`linux_only(...)`. A stand-in engine is a Python program (`stand_in`), never a shell script.
"""

import csv
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "ci"))

import engine_marker  # noqa: E402
from engine_marker import (  # noqa: E402, F401
    engine,
    pytest_runtest_call,
    pytest_runtest_setup,
    pytest_runtest_teardown,
)

LOCK_LOG = "WORKCENTER_LOCK_LOG"
_made: list[str] = []

REPO = Path(__file__).resolve().parents[1]
HOSTS = REPO / "verify" / "desktop.csv"
WORDS = {"posix": "POSIX-only", "linux": "Linux-only"}


def host_rows(path: Path) -> dict[str, tuple[str, str]]:
    """verify/desktop.csv: each test file's `runs` and `reason`, by its path under the repository. No
    table (a copy of this conftest in a folder of its own) skips nothing."""
    if not path.is_file():
        return {}
    with open(path, encoding="utf-8", newline="") as fh:
        return {r["file"].strip(): (r["runs"].strip(), r["reason"].strip()) for r in csv.DictReader(fh)}


def host_skip(name: str, table: dict[str, tuple[str, str]], platform: str) -> str | None:
    """Why the file `name` does not run on `platform` (sys.platform's value), None where it does."""
    runs, reason = table.get(name, ("desktop", ""))
    if runs == "posix" and platform == "win32" or runs == "linux" and not platform.startswith("linux"):
        return f"{WORDS[runs]}: {reason} (verify/desktop.csv)"
    return None


def posix_only(reason: str):
    """The mark of 1 test that cannot run on Windows, in a file that runs everywhere."""
    return pytest.mark.skipif(sys.platform == "win32", reason=f"POSIX-only: {reason}")


def linux_only(reason: str):
    """The mark of 1 test that runs on Linux alone, in a file that runs everywhere."""
    return pytest.mark.skipif(not sys.platform.startswith("linux"), reason=f"Linux-only: {reason}")


class HostSkipped(pytest.Module):
    """A test file its row skips on this system: collected as skipped, never imported."""

    reason = ""

    def collect(self):
        pytest.skip(self.reason, allow_module_level=True)


def pytest_pycollect_makemodule(module_path, parent):
    try:
        name = Path(module_path).resolve().relative_to(REPO).as_posix()
    except ValueError:
        return None
    why = host_skip(name, host_rows(HOSTS), sys.platform)
    if why is None:
        return None
    module = HostSkipped.from_parent(parent, path=Path(module_path))
    module.reason = why
    return module


# A first line the kernel can start: no space (macOS splits the line there) and at most 127 bytes
# (Linux before 5.1 cuts it; macOS's bound is larger).
SHEBANG = re.compile(r"[^\s]{1,125}")


def stand_in(path: Path, source: str) -> Path:
    """A stand-in engine at `path`: a program that runs the Python `source` under this Python, with no
    shell, and the path to run it by.

    Linux and macOS: `path` itself, whose first line names this Python. Where that path cannot be a
    first line (a venv under macOS's "Application Support"), `path` is `#!/bin/sh` and 1 exec line, and
    the program is `<name>-stand-in.py` beside it. Windows starts no first line: the program is
    `<name>-stand-in.py`, and `<name>.cmd` (found on PATH by PATHEXT) starts this Python on it with every
    argument. Not run on Windows yet: cmd reads `%` and `^` in an argument."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    script = path.with_name(f"{path.name}-stand-in.py")
    if sys.platform == "win32":
        script.write_text(source, encoding="utf-8")
        cmd = path.with_name(f"{path.name}.cmd")
        cmd.write_bytes(f'@"{sys.executable}" "{script}" %*\r\n'.encode())
        return cmd
    if SHEBANG.fullmatch(sys.executable):
        path.write_text(f"#!{sys.executable}\n{source}", encoding="utf-8")
    else:
        script.write_text(source, encoding="utf-8")
        quote = "'\"'\"'"
        py, prog = (str(p).replace("'", quote) for p in (sys.executable, script))
        path.write_text(f"#!/bin/sh\nexec '{py}' '{prog}' \"$@\"\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def router_absent() -> str:
    """Why Via's default router cannot run here, "" when it can: the router's own absent(), which rests
    on the java the product picks (routers.workcenter_java). A routing test skips on this, never on
    the first java on PATH: in CI run 44515796762 a java stood on PATH, so 13 tests ran, and the product
    ran another java, which could not draw FreeRouting's window."""
    tools = str(Path(__file__).resolve().parents[1] / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import routers

    return routers.get(routers.DEFAULT).absent()


# A process that knows no home folder: HOME unset, and a user id with no line in /etc/passwd, as in a
# container run as a user id its image never named (M299). Path.home() raises RuntimeError there. A
# test cannot change its user id, so Python starts with pwd.getpwuid raising KeyError, as it does for
# an unknown id, then runs the script named first with the rest as its arguments.
NO_HOME = (
    "import pwd, runpy, sys\n"
    "def unknown(uid):\n"
    "    raise KeyError(f'getpwuid(): uid not found: {uid}')\n"
    "pwd.getpwuid = unknown\n"
    "sys.argv = sys.argv[1:]\n"
    "runpy.run_path(sys.argv[0], run_name='__main__')\n"
)


# Windows has no pwd: Path.home() reads USERPROFILE, then HOMEDRIVE and HOMEPATH (Python's ntpath), and
# raises RuntimeError with none of them. The start there only runs the script.
NO_HOME_WINDOWS = (
    "import runpy, sys\nsys.argv = sys.argv[1:]\nrunpy.run_path(sys.argv[0], run_name='__main__')\n"
)
HOME_VARIABLES = {"posix": ("HOME",), "win32": ("HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH")}


def no_home_command(script, *args, env: dict | None = None) -> tuple[list[str], dict]:
    """The command and the environment of `script args` with no home folder known, on this system."""
    windows = sys.platform == "win32"
    names = HOME_VARIABLES["win32" if windows else "posix"]
    bare = {k: v for k, v in (os.environ if env is None else env).items() if k not in names}
    start = NO_HOME_WINDOWS if windows else NO_HOME
    return [sys.executable, "-c", start, str(script), *map(str, args)], bare


def no_home(script, *args, env: dict | None = None, **kwargs) -> subprocess.CompletedProcess:
    """Run `script args` under NO_HOME, with `env` (else this process's environment) less HOME."""
    cmd, bare = no_home_command(script, *args, env=env)
    return subprocess.run(cmd, env=bare, capture_output=True, text=True, check=False, **kwargs)


def pytest_configure(config):
    engine_marker.pytest_configure(config)
    if not os.environ.get(LOCK_LOG):
        handle, log = tempfile.mkstemp(prefix="engine-lock-", suffix=".log")
        os.close(handle)
        os.environ[LOCK_LOG] = log
        _made.append(log)


def pytest_terminal_summary(terminalreporter):
    """The lines of the runs that waited for the lock in this session, so a slow session says why."""
    log = Path(os.environ.get(LOCK_LOG, ""))
    lines = log.read_text(encoding="utf-8").splitlines() if _made and log.is_file() else []
    if lines:
        terminalreporter.write_sep("-", f"engine lock: {len(lines)} lines in {log}")
        for line in lines:
            terminalreporter.write_line(line)


def pytest_unconfigure(config):
    engine_marker.pytest_unconfigure(config)
    for log in _made:
        Path(log).unlink(missing_ok=True)
