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

import atexit
import csv
import hashlib
import importlib.util
import os
import shutil
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


_hostos = []
# Where Via looks for each engine a mark asks for: tools/hostos.py's function of its candidates.
ENGINE_CANDIDATES = {"kicad-cli": "kicad_cli_candidates", "ngspice": "ngspice_candidates"}


def hostos():
    """tools/hostos.py, loaded from its file under a name of its own when first asked for: nothing goes
    on sys.path, and a copy of this conftest in a folder of its own, with no tools/, still loads."""
    if not _hostos:
        spec = importlib.util.spec_from_file_location("conftest_hostos", REPO / "tools" / "hostos.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _hostos.append(module)
    return _hostos[0]


def engine_absent(name: str) -> bool:
    """Whether Via finds no `name` (kicad-cli or ngspice) where its CLI looks: on PATH, then where the
    installer put it (KiCad's bundle on macOS, its per-user install and Via's own ngspice on Windows), or
    the file KICAD_CLI or NGSPICE names. Marks on shutil.which(name) alone skipped 57 tests for ngspice and
    42 for kicad-cli on Windows, and 44 for kicad-cli on macOS, whose engines the same run's gates used
    (run 46093588252, M328)."""
    module = hostos()
    return module.found_program(getattr(module, ENGINE_CANDIDATES[name])()) is None


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


def first_line_fits(path: str) -> bool:
    """Whether the kernel starts `path` from a first line (`#!path`): no space or tab (macOS's kernel
    splits the line there) and at most 125 bytes, so the line is at most 127 (Linux before 5.1 cuts it
    there; macOS's bound is larger). The bound is in bytes: a non-ASCII letter takes 2 or more."""
    return bool(path) and not any(c.isspace() for c in path) and len(os.fsencode(path)) <= 125


_TWINS: list[str] = []


def _twin(folder: Path) -> Path:
    """`folder`/bin/python, a link to this Python, with this venv's pyvenv.cfg and lib beside it (where
    this Python is a venv's), so the link imports what this Python imports. Made once."""
    py = folder / "bin" / "python"
    py.parent.mkdir(parents=True, exist_ok=True)
    prefix = Path(sys.prefix)
    links = [(py, Path(sys.executable))]
    if (prefix / "pyvenv.cfg").is_file():
        links += [(folder / "pyvenv.cfg", prefix / "pyvenv.cfg"), (folder / "lib", prefix / "lib")]
    for link, target in links:
        try:
            link.symlink_to(target)
        except FileExistsError:
            pass
    return py


def first_line_python(folder: Path) -> str:
    """The Python a stand-in's first line names: this one, or where its path cannot be a first line (a
    venv under macOS's "Application Support"), a link to it in `folder`, else in a temporary folder of
    this process, removed at its exit. The link's folder is named by this Python's path. RuntimeError
    where neither can be a first line."""
    if first_line_fits(sys.executable):
        return sys.executable
    name = ".p" + hashlib.sha256(os.fsencode(sys.executable)).hexdigest()[:8]  # short: the bound is tight
    for base in (folder, None):
        if base is None:
            if not _TWINS:
                _TWINS.append(tempfile.mkdtemp(prefix="si-"))
                atexit.register(shutil.rmtree, _TWINS[0], True)
            base = Path(_TWINS[0])
        if first_line_fits(str(base / name / "bin" / "python")):
            return str(_twin(base / name))
    raise RuntimeError(f"no first line can start this Python ({sys.executable}): set TMPDIR to a short path")


def stand_in(path: Path, source: str) -> Path:
    """A stand-in engine at `path`: a program that runs the Python `source` under this Python, with no
    shell, and the path to run it by.

    Linux and macOS: `path` itself, whose first line names this Python, or a link to it where this
    Python's path cannot be a first line (first_line_python). Windows starts no first line: the program
    is `<name>-stand-in.py`, and `<name>.cmd` (found on PATH by PATHEXT) starts this Python on it with
    every argument. Not run on Windows yet: cmd reads `%` and `^` in an argument."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        script = path.with_name(f"{path.name}-stand-in.py")
        script.write_text(source, encoding="utf-8")
        cmd = path.with_name(f"{path.name}.cmd")
        cmd.write_bytes(f'@"{sys.executable}" "{script}" %*\r\n'.encode())
        return cmd
    path.write_text(f"#!{first_line_python(path.parent)}\n{source}", encoding="utf-8")
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
