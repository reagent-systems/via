"""tools/hostos.py: every difference between Linux, macOS and Windows that the CLI needs, in 1 place.

On Linux each function returns what the code returns today, at the file and line its comment names.
Each test sets `sys.platform` to linux, darwin or win32, and the environment variables and files the
function reads. `os.name` is not set: hostos reads `sys.platform` alone, and pathlib builds a
WindowsPath, which Linux cannot make, whenever `os.name` is "nt".

The module is loaded from its file for each test, under a name of its own: no folder is put on
`sys.path` and no other test's `import hostos` gets this copy (PROCESSES.md P12 step 12).
"""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tools" / "hostos.py"
PLATFORMS = ("linux", "darwin", "win32")
# Every variable hostos reads: each test starts with none of them set.
READS = (
    "WORKCENTER_ROOT",
    "KICAD_CLI",
    "NGSPICE",
    "KICAD_SYMBOL_DIR",
    "KICAD_FOOTPRINT_DIR",
    "KICAD10_SYMBOL_DIR",
    "KICAD10_FOOTPRINT_DIR",
    "KICAD10_3DMODEL_DIR",
    "LOCALAPPDATA",
    "ProgramFiles",
)
BUNDLED_PYTHON = Path("Contents/Frameworks/Python.framework/Versions/Current/bin/python3")
MAC_SHARED = Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport")


@pytest.fixture
def hostos():
    spec = importlib.util.spec_from_file_location("hostos_under_test", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def bare_env(monkeypatch, tmp_path):
    for name in READS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def on(monkeypatch, platform: str) -> None:
    monkeypatch.setattr(sys, "platform", platform)


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


# ------------------------------------------------------------------ default_root


def test_default_root_on_linux_is_the_folder_install_sh_uses(hostos, monkeypatch):
    on(monkeypatch, "linux")
    assert hostos.default_root() == Path("/opt/workcenters/ee")


def test_default_root_on_macos_is_the_users_application_support_folder(hostos, monkeypatch, tmp_path):
    on(monkeypatch, "darwin")
    assert hostos.default_root() == tmp_path / "home" / "Library" / "Application Support" / "via"


def test_default_root_on_windows_is_under_localappdata(hostos, monkeypatch, tmp_path):
    on(monkeypatch, "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert hostos.default_root() == tmp_path / "local" / "Via"


def test_default_root_on_windows_without_localappdata_is_under_the_home_folder(hostos, monkeypatch, tmp_path):
    on(monkeypatch, "win32")
    assert hostos.default_root() == tmp_path / "home" / "AppData" / "Local" / "Via"


@pytest.mark.parametrize("platform", PLATFORMS)
def test_default_root_is_the_default_and_leaves_workcenter_root_to_the_caller(hostos, monkeypatch, platform):
    """Every caller reads `os.environ.get("WORKCENTER_ROOT", <default>)` today; the default is all that
    moves here."""
    on(monkeypatch, platform)
    before = hostos.default_root()
    monkeypatch.setenv("WORKCENTER_ROOT", "/somewhere/else")
    assert hostos.default_root() == before


# ------------------------------------------------------------------ lock_dir


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_lock_dir_on_posix_is_one_folder_per_user_in_tmp(hostos, monkeypatch, platform):
    on(monkeypatch, platform)
    assert hostos.lock_dir() == Path("/tmp") / f"workcenter-lock-{os.getuid()}"


def test_lock_dir_on_windows_is_under_localappdata_and_asks_no_user_id(hostos, monkeypatch, tmp_path):
    on(monkeypatch, "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.delattr(os, "getuid")
    assert hostos.lock_dir() == tmp_path / "local" / "Via" / "lock"


def test_lock_dir_leaves_workcenter_lock_dir_to_the_lock(hostos, monkeypatch):
    on(monkeypatch, "linux")
    monkeypatch.setenv("WORKCENTER_LOCK_DIR", "/elsewhere")
    assert hostos.lock_dir() == Path("/tmp") / f"workcenter-lock-{os.getuid()}"


# ------------------------------------------------------------------ venv_python


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_venv_python_on_posix_is_bin_python(hostos, monkeypatch, tmp_path, platform):
    on(monkeypatch, platform)
    assert hostos.venv_python(tmp_path) == tmp_path / "venv" / "bin" / "python"


def test_venv_python_on_windows_is_scripts_python_exe(hostos, monkeypatch, tmp_path):
    on(monkeypatch, "win32")
    assert hostos.venv_python(tmp_path) == tmp_path / "venv" / "Scripts" / "python.exe"


# ------------------------------------------------------------------ kicad_python


def test_kicad_python_on_linux_is_the_venvs_python_when_it_is_there(hostos, monkeypatch, tmp_path):
    """Linux's venv sees pcbnew (--system-site-packages); workcenter's venv_python() picks it."""
    on(monkeypatch, "linux")
    monkeypatch.setenv("WORKCENTER_ROOT", str(tmp_path))
    py = touch(tmp_path / "venv" / "bin" / "python")
    assert hostos.kicad_python() == str(py)


def test_kicad_python_on_linux_without_a_venv_is_this_python(hostos, monkeypatch, tmp_path):
    on(monkeypatch, "linux")
    monkeypatch.setenv("WORKCENTER_ROOT", str(tmp_path))
    assert hostos.kicad_python() == sys.executable


def test_kicad_python_on_macos_is_the_python_in_kicads_bundle(hostos, monkeypatch, tmp_path):
    on(monkeypatch, "darwin")
    app = tmp_path / "Applications" / "KiCad" / "KiCad.app"
    monkeypatch.setattr(hostos, "MAC_APP", app)
    py = touch(app / BUNDLED_PYTHON)
    assert hostos.kicad_python() == str(py)


def test_kicad_python_on_macos_follows_kicad_cli_to_another_bundle(hostos, monkeypatch, tmp_path):
    on(monkeypatch, "darwin")
    monkeypatch.setattr(hostos, "MAC_APP", tmp_path / "absent" / "KiCad.app")
    app = tmp_path / "Other" / "KiCad.app"
    monkeypatch.setenv("KICAD_CLI", str(touch(app / "Contents" / "MacOS" / "kicad-cli")))
    py = touch(app / BUNDLED_PYTHON)
    assert hostos.kicad_python() == str(py)


def test_kicad_python_on_macos_without_kicad_is_none(hostos, monkeypatch, tmp_path):
    on(monkeypatch, "darwin")
    monkeypatch.setattr(hostos, "MAC_APP", tmp_path / "absent" / "KiCad.app")
    assert hostos.kicad_python() is None


def test_kicad_python_on_windows_is_bin_python_exe_of_the_machine_install(hostos, monkeypatch, tmp_path):
    on(monkeypatch, "win32")
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    py = touch(tmp_path / "pf" / "KiCad" / "10.0" / "bin" / "python.exe")
    touch(tmp_path / "local" / "Programs" / "KiCad" / "10.0" / "bin" / "python.exe")
    assert hostos.kicad_python() == str(py)


def test_kicad_python_on_windows_takes_the_user_install_when_alone(hostos, monkeypatch, tmp_path):
    on(monkeypatch, "win32")
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    py = touch(tmp_path / "local" / "Programs" / "KiCad" / "10.0" / "bin" / "python.exe")
    assert hostos.kicad_python() == str(py)


def test_kicad_python_on_windows_follows_kicad_cli_first(hostos, monkeypatch, tmp_path):
    on(monkeypatch, "win32")
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    machine = touch(tmp_path / "pf" / "KiCad" / "10.0" / "bin" / "python.exe")
    cli = touch(tmp_path / "D" / "KiCad" / "bin" / "kicad-cli.exe")
    monkeypatch.setenv("KICAD_CLI", str(cli))
    assert hostos.kicad_python() == str(machine)
    touch(cli.parent / "python.exe")
    assert hostos.kicad_python() == str(cli.parent / "python.exe")


def test_kicad_python_on_windows_without_kicad_is_none(hostos, monkeypatch, tmp_path):
    on(monkeypatch, "win32")
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert hostos.kicad_python() is None


# ------------------------------------------------------------------ kicad_cli_candidates


def test_kicad_cli_on_linux_is_the_name_on_path(hostos, monkeypatch):
    on(monkeypatch, "linux")
    assert hostos.kicad_cli_candidates() == ["kicad-cli"]


@pytest.mark.parametrize("platform", PLATFORMS)
def test_kicad_cli_named_by_kicad_cli_is_the_only_candidate(hostos, monkeypatch, platform):
    on(monkeypatch, platform)
    monkeypatch.setenv("KICAD_CLI", "/my/kicad-cli")
    assert hostos.kicad_cli_candidates() == ["/my/kicad-cli"]


def test_kicad_cli_on_macos_is_on_path_then_in_the_bundle(hostos, monkeypatch):
    on(monkeypatch, "darwin")
    assert hostos.kicad_cli_candidates() == [
        "kicad-cli",
        str(Path("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli")),
    ]


def test_kicad_cli_on_windows_is_on_path_then_in_the_machine_then_the_user_one(hostos, monkeypatch, tmp_path):
    on(monkeypatch, "win32")
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    assert hostos.kicad_cli_candidates() == [
        "kicad-cli",
        str(tmp_path / "pf" / "KiCad" / "10.0" / "bin" / "kicad-cli.exe"),
        str(tmp_path / "local" / "Programs" / "KiCad" / "10.0" / "bin" / "kicad-cli.exe"),
    ]


def test_kicad_cli_on_windows_without_programfiles_names_c_program_files(hostos, monkeypatch, tmp_path):
    on(monkeypatch, "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    machine = Path("C:\\Program Files") / "KiCad" / "10.0" / "bin" / "kicad-cli.exe"
    assert hostos.kicad_cli_candidates()[1] == str(machine)


# ------------------------------------------------------------------ ngspice_candidates


def test_ngspice_on_linux_is_the_name_on_path(hostos, monkeypatch):
    on(monkeypatch, "linux")
    assert hostos.ngspice_candidates() == ["ngspice"]


@pytest.mark.parametrize("platform", PLATFORMS)
def test_ngspice_named_by_ngspice_is_the_only_candidate(hostos, monkeypatch, platform):
    on(monkeypatch, platform)
    monkeypatch.setenv("NGSPICE", "/my/ngspice")
    assert hostos.ngspice_candidates() == ["/my/ngspice"]


def test_ngspice_on_macos_is_on_path_then_in_homebrews_prefixes(hostos, monkeypatch):
    on(monkeypatch, "darwin")
    assert hostos.ngspice_candidates() == ["ngspice", "/opt/homebrew/bin/ngspice", "/usr/local/bin/ngspice"]


def test_ngspice_on_windows_is_the_console_program_first(hostos, monkeypatch):
    on(monkeypatch, "win32")
    assert hostos.ngspice_candidates() == [
        "ngspice_con",
        "ngspice",
        str(Path("C:\\Spice64") / "bin" / "ngspice_con.exe"),
        str(Path("C:\\Spice64") / "bin" / "ngspice.exe"),
    ]


# ------------------------------------------------------------------ kicad_dirs


def test_kicad_dirs_on_linux_are_the_ppas_folders(hostos, monkeypatch):
    on(monkeypatch, "linux")
    assert hostos.kicad_dirs() == {
        "symbols": Path("/usr/share/kicad/symbols"),
        "footprints": Path("/usr/share/kicad/footprints"),
        "3dmodels": Path("/usr/share/kicad/3dmodels"),
    }


@pytest.mark.parametrize("platform", PLATFORMS)
def test_kicad_dirs_take_vias_own_variables_first(hostos, monkeypatch, tmp_path, platform):
    """KICAD_SYMBOL_DIR and KICAD_FOOTPRINT_DIR are what kicadgen.py reads today and what
    `make verify-site` points at empty folders; they win over KiCad's own variables."""
    on(monkeypatch, platform)
    monkeypatch.setenv("KICAD_SYMBOL_DIR", str(tmp_path / "s"))
    monkeypatch.setenv("KICAD_FOOTPRINT_DIR", str(tmp_path / "f"))
    monkeypatch.setenv("KICAD10_SYMBOL_DIR", str(tmp_path / "s10"))
    monkeypatch.setenv("KICAD10_FOOTPRINT_DIR", str(tmp_path / "f10"))
    monkeypatch.setenv("KICAD10_3DMODEL_DIR", str(tmp_path / "m10"))
    dirs = hostos.kicad_dirs()
    assert dirs == {"symbols": tmp_path / "s", "footprints": tmp_path / "f", "3dmodels": tmp_path / "m10"}


def test_kicad_dirs_on_linux_read_no_kicad10_library_variable(hostos, monkeypatch, tmp_path):
    """kicadgen.py:46-47 read only Via's variables today; the 3D folder reads KICAD10_3DMODEL_DIR
    (workcenter:2505)."""
    on(monkeypatch, "linux")
    monkeypatch.setenv("KICAD10_SYMBOL_DIR", str(tmp_path / "s10"))
    monkeypatch.setenv("KICAD10_FOOTPRINT_DIR", str(tmp_path / "f10"))
    monkeypatch.setenv("KICAD10_3DMODEL_DIR", str(tmp_path / "m10"))
    assert hostos.kicad_dirs() == {
        "symbols": Path("/usr/share/kicad/symbols"),
        "footprints": Path("/usr/share/kicad/footprints"),
        "3dmodels": tmp_path / "m10",
    }


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_kicad_dirs_off_linux_take_kicads_own_variables_next(hostos, monkeypatch, tmp_path, platform):
    on(monkeypatch, platform)
    monkeypatch.setenv("KICAD10_SYMBOL_DIR", str(tmp_path / "s10"))
    monkeypatch.setenv("KICAD10_FOOTPRINT_DIR", str(tmp_path / "f10"))
    monkeypatch.setenv("KICAD10_3DMODEL_DIR", str(tmp_path / "m10"))
    dirs = hostos.kicad_dirs()
    assert dirs == {"symbols": tmp_path / "s10", "footprints": tmp_path / "f10", "3dmodels": tmp_path / "m10"}


def test_kicad_dirs_on_macos_are_in_the_bundles_sharedsupport(hostos, monkeypatch):
    on(monkeypatch, "darwin")
    assert hostos.kicad_dirs() == {
        "symbols": MAC_SHARED / "symbols",
        "footprints": MAC_SHARED / "footprints",
        "3dmodels": MAC_SHARED / "3dmodels",
    }


def test_kicad_dirs_on_macos_follow_kicad_cli_to_its_bundle(hostos, monkeypatch, tmp_path):
    on(monkeypatch, "darwin")
    app = tmp_path / "Other" / "KiCad.app"
    monkeypatch.setenv("KICAD_CLI", str(touch(app / "Contents" / "MacOS" / "kicad-cli")))
    assert hostos.kicad_dirs()["symbols"] == app / "Contents" / "SharedSupport" / "symbols"


def test_kicad_dirs_on_macos_ignore_a_kicad_cli_outside_a_bundle(hostos, monkeypatch, tmp_path):
    on(monkeypatch, "darwin")
    monkeypatch.setenv("KICAD_CLI", str(touch(tmp_path / "bin" / "kicad-cli")))
    assert hostos.kicad_dirs()["symbols"] == MAC_SHARED / "symbols"


def test_kicad_dirs_on_windows_are_in_the_machine_installs_share(hostos, monkeypatch, tmp_path):
    on(monkeypatch, "win32")
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    share = tmp_path / "pf" / "KiCad" / "10.0" / "share" / "kicad"
    assert hostos.kicad_dirs() == {
        "symbols": share / "symbols",
        "footprints": share / "footprints",
        "3dmodels": share / "3dmodels",
    }


def test_kicad_dirs_on_windows_take_the_user_install_when_only_it_has_a_share(hostos, monkeypatch, tmp_path):
    on(monkeypatch, "win32")
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    share = tmp_path / "local" / "Programs" / "KiCad" / "10.0" / "share" / "kicad"
    (share / "symbols").mkdir(parents=True)
    assert hostos.kicad_dirs()["symbols"] == share / "symbols"


def test_kicad_dirs_on_windows_follow_kicad_cli_first(hostos, monkeypatch, tmp_path):
    on(monkeypatch, "win32")
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    (tmp_path / "pf" / "KiCad" / "10.0" / "share" / "kicad").mkdir(parents=True)
    cli = touch(tmp_path / "D" / "KiCad" / "bin" / "kicad-cli.exe")
    monkeypatch.setenv("KICAD_CLI", str(cli))
    (tmp_path / "D" / "KiCad" / "share" / "kicad").mkdir(parents=True)
    assert hostos.kicad_dirs()["footprints"] == tmp_path / "D" / "KiCad" / "share" / "kicad" / "footprints"


# ------------------------------------------------------------------ kicad_share


def test_kicad_share_on_linux_is_the_ppas_folder_whatever_the_variables(hostos, monkeypatch, tmp_path):
    """tools/workcenter:70 keeps the install's 3D folder apart from every variable: a board's
    ${KICAD9_3DMODEL_DIR} unset falls back to it, never to KICAD10_3DMODEL_DIR's value."""
    on(monkeypatch, "linux")
    for name in ("KICAD_SYMBOL_DIR", "KICAD10_SYMBOL_DIR", "KICAD10_3DMODEL_DIR"):
        monkeypatch.setenv(name, str(tmp_path / name))
    assert hostos.kicad_share() == Path("/usr/share/kicad")


def test_kicad_share_on_macos_is_the_bundles_sharedsupport(hostos, monkeypatch, tmp_path):
    on(monkeypatch, "darwin")
    monkeypatch.setenv("KICAD10_3DMODEL_DIR", str(tmp_path / "models"))
    assert hostos.kicad_share() == MAC_SHARED


def test_kicad_share_on_windows_is_the_first_install_with_a_share(hostos, monkeypatch, tmp_path):
    on(monkeypatch, "win32")
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    share = tmp_path / "local" / "Programs" / "KiCad" / "10.0" / "share" / "kicad"
    share.mkdir(parents=True)
    monkeypatch.setenv("KICAD10_3DMODEL_DIR", str(tmp_path / "models"))
    assert hostos.kicad_share() == share


@pytest.mark.parametrize("platform", PLATFORMS)
def test_kicad_dirs_without_variables_are_the_folders_of_kicad_share(hostos, monkeypatch, tmp_path, platform):
    on(monkeypatch, platform)
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    share = hostos.kicad_share()
    assert hostos.kicad_dirs() == {name: share / name for name in ("symbols", "footprints", "3dmodels")}


# ------------------------------------------------------------------ awt_lib


def test_awt_lib_on_linux_is_the_x11_library(hostos, monkeypatch, tmp_path):
    """routers.py:49: FreeRouting 1.9.0's window needs AWT's X11 library."""
    on(monkeypatch, "linux")
    assert hostos.awt_lib(tmp_path) == tmp_path / "lib" / "libawt_xawt.so"


def test_awt_lib_on_macos_is_the_cocoa_library(hostos, monkeypatch, tmp_path):
    on(monkeypatch, "darwin")
    assert hostos.awt_lib(tmp_path) == tmp_path / "lib" / "libawt_lwawt.dylib"


def test_awt_lib_on_windows_is_awt_dll_in_bin(hostos, monkeypatch, tmp_path):
    on(monkeypatch, "win32")
    assert hostos.awt_lib(tmp_path) == tmp_path / "bin" / "awt.dll"


# ------------------------------------------------------------------ stop_signals


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_stop_signals_on_posix_are_term_and_hup(hostos, monkeypatch, platform):
    """enginelock.py:466."""
    on(monkeypatch, platform)
    assert hostos.stop_signals() == (signal.SIGTERM, signal.SIGHUP)


def test_stop_signals_on_windows_are_term_and_break_and_need_no_hup(hostos, monkeypatch):
    on(monkeypatch, "win32")
    monkeypatch.delattr(signal, "SIGHUP")
    monkeypatch.setattr(signal, "SIGBREAK", 21, raising=False)
    assert hostos.stop_signals() == (signal.SIGTERM, 21)


def test_stop_signals_leave_out_a_signal_the_python_lacks(hostos, monkeypatch):
    on(monkeypatch, "win32")
    monkeypatch.delattr(signal, "SIGBREAK", raising=False)
    assert hostos.stop_signals() == (signal.SIGTERM,)


# ------------------------------------------------------------------ kill_tree


class Proc:
    """A stand-in for subprocess.Popen: its pid and whether kill() was called."""

    def __init__(self, pid: int = 4242):
        self.pid = pid
        self.killed = False

    def kill(self):
        self.killed = True


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_kill_tree_on_posix_kills_the_process_group(hostos, monkeypatch, platform):
    """routers.py:273: the child leads its own group (start_new_session) and the group gets SIGKILL."""
    on(monkeypatch, platform)
    sent = []
    monkeypatch.setattr(os, "killpg", lambda pid, sig: sent.append((pid, sig)))
    proc = Proc()
    hostos.kill_tree(proc)
    assert sent == [(4242, signal.SIGKILL)]
    assert not proc.killed


def test_kill_tree_on_windows_runs_taskkill_on_the_tree(hostos, monkeypatch):
    on(monkeypatch, "win32")
    monkeypatch.delattr(os, "killpg")
    ran = []

    def run(cmd, **kwargs):
        ran.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(hostos.subprocess, "run", run)
    proc = Proc()
    hostos.kill_tree(proc)
    assert ran == [["taskkill", "/T", "/F", "/PID", "4242"]]
    assert not proc.killed


def test_kill_tree_on_windows_kills_the_child_when_taskkill_fails(hostos, monkeypatch):
    on(monkeypatch, "win32")

    def run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, "", "ERROR: access is denied")

    monkeypatch.setattr(hostos.subprocess, "run", run)
    proc = Proc()
    hostos.kill_tree(proc)
    assert proc.killed


def test_kill_tree_on_windows_kills_the_child_when_taskkill_is_absent(hostos, monkeypatch):
    on(monkeypatch, "win32")

    def run(cmd, **kwargs):
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(hostos.subprocess, "run", run)
    proc = Proc()
    hostos.kill_tree(proc)
    assert proc.killed


def gone(pid: int) -> bool:
    """The process has ended: no entry, or a zombie no one has reaped yet."""
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] == "Z"
    except FileNotFoundError:
        return True


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc to see the grandchild end")
def test_kill_tree_on_linux_ends_a_grandchild_the_test_started(hostos):
    """A real tree, as xvfb-run starts Java: a shell in its own session and a sleep it started."""
    proc = subprocess.Popen(
        ["sh", "-c", "sleep 60 & echo $!; wait"], stdout=subprocess.PIPE, text=True, start_new_session=True
    )
    try:
        grandchild = int(proc.stdout.readline())
        hostos.kill_tree(proc)
        assert proc.wait(timeout=10) == -signal.SIGKILL
        end = time.monotonic() + 10
        while not gone(grandchild) and time.monotonic() < end:
            time.sleep(0.05)
        assert gone(grandchild)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        proc.stdout.close()


# ------------------------------------------------------------------ write_text


@pytest.mark.parametrize("platform", PLATFORMS)
def test_write_text_writes_utf8_with_lf_line_ends(hostos, monkeypatch, tmp_path, platform):
    on(monkeypatch, platform)
    path = tmp_path / "out.txt"
    assert hostos.write_text(path, "Ω 10k\nnext\n") == len("Ω 10k\nnext\n")
    assert path.read_bytes() == "Ω 10k\nnext\n".encode()


def test_write_text_asks_for_lf_and_utf8_whatever_the_locale(hostos, monkeypatch, tmp_path):
    """Linux cannot make Python translate "\\n" as Windows does, so the test reads what is asked of the
    write: newline="\\n" turns translation off on every system (Python's `open`)."""
    on(monkeypatch, "win32")
    asked = []
    real = Path.write_text

    def spy(self, data, encoding=None, errors=None, newline=None):
        asked.append((encoding, newline))
        return real(self, data, encoding=encoding, errors=errors, newline=newline)

    monkeypatch.setattr(Path, "write_text", spy)
    hostos.write_text(str(tmp_path / "out.txt"), "a\n")
    assert asked == [("utf-8", "\n")]


def test_write_text_leaves_a_carriage_return_the_text_holds(hostos, tmp_path):
    path = tmp_path / "out.txt"
    hostos.write_text(path, "a\r\nb\n")
    assert path.read_bytes() == b"a\r\nb\n"


# ------------------------------------------------------------------ shell_word


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_shell_word_on_posix_quotes_a_path_with_a_space_for_sh(hostos, monkeypatch, platform):
    on(monkeypatch, platform)
    pip = "/Users/a/Library/Application Support/via/venv/bin/pip"
    assert hostos.shell_word(pip) == f"'{pip}'"
    assert shlex.split(hostos.shell_word(pip) + " install") == [pip, "install"]


@pytest.mark.parametrize("platform", PLATFORMS)
def test_shell_word_leaves_a_plain_path_as_written(hostos, monkeypatch, platform):
    """Linux's command lines stay as they are today."""
    on(monkeypatch, platform)
    assert hostos.shell_word("/opt/workcenters/ee/venv/bin/pip") == "/opt/workcenters/ee/venv/bin/pip"


def test_shell_word_on_windows_puts_a_path_with_a_space_in_double_quotes(hostos, monkeypatch):
    """cmd.exe and PowerShell take double quotes, not sh's single ones (subprocess.list2cmdline)."""
    on(monkeypatch, "win32")
    pip = "C:\\Users\\John Smith\\AppData\\Local\\Via\\venv\\Scripts\\pip.exe"
    assert hostos.shell_word(pip) == f'"{pip}"'


# ------------------------------------------------------------------ the module

# Run in a child process, so this session's import path and modules stay as they are: each pair is
# (what the code holds today, what hostos returns on Linux).
TODAY = """
import importlib.machinery, importlib.util, json, os, signal, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import enginelock, hostos, kicadgen, routers
loader = importlib.machinery.SourceFileLoader("wc", sys.argv[1] + "/workcenter")
spec = importlib.util.spec_from_loader("wc", loader)
wc = sys.modules["wc"] = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wc)

class P:
    pid = 1
sent = []
os.killpg = lambda pid, sig: sent.append([pid, int(sig)])
hostos.kill_tree(P())
home = Path("/java/home")
root = os.environ.get("WORKCENTER_ROOT", str(hostos.default_root()))
models = os.environ.get("KICAD10_3DMODEL_DIR", wc.DEFAULT_3DMODEL_DIR)
pairs = {
    "default_root": [str(wc.WC_ROOT), root],
    "routers_root": [str(routers.WC_ROOT), root],
    "lock_dir": [str(enginelock.lock_dir()), str(hostos.lock_dir())],
    "venv_python": [str(wc.WC_ROOT / "venv" / "bin" / "python"), str(hostos.venv_python(wc.WC_ROOT))],
    "kicad_python": [wc.venv_python(), hostos.kicad_python()],
    "kicad_cli": [[wc.KICAD_CLI], hostos.kicad_cli_candidates()],
    "ngspice": [[wc.NGSPICE], hostos.ngspice_candidates()],
    "symbols": [str(kicadgen.SYMBOL_DIR), str(hostos.kicad_dirs()["symbols"])],
    "footprints": [str(kicadgen.FOOTPRINT_DIR), str(hostos.kicad_dirs()["footprints"])],
    "3dmodels": [models, str(hostos.kicad_dirs()["3dmodels"])],
    "awt_lib": [str(home / routers.AWT_X11), str(hostos.awt_lib(home))],
    "stop_signals": [[int(s) for s in enginelock._STOPS], [int(s) for s in hostos.stop_signals()]],
    "kill_tree": [[[1, int(signal.SIGKILL)]], sent],
}
print(json.dumps(pairs))
"""


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="today's code is Linux's")
@pytest.mark.parametrize("venv", [False, True])
@pytest.mark.parametrize("named", [False, True])
def test_on_linux_hostos_returns_what_the_code_returns_today(tmp_path, venv, named):
    """With no variable set, with each variable set, and with and without a venv's Python."""
    env = {k: v for k, v in os.environ.items() if k not in READS and k != "WORKCENTER_LOCK_DIR"}
    if venv:
        env["WORKCENTER_ROOT"] = str(tmp_path / "root")
        touch(tmp_path / "root" / "venv" / "bin" / "python")
    if named:
        for name in (n for n in READS if n.startswith(("KICAD", "NGSPICE"))):
            env[name] = str(tmp_path / name)
    proc = subprocess.run(
        [sys.executable, "-I", "-c", TODAY, str(ROOT / "tools")],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    pairs = json.loads(proc.stdout)
    assert len(pairs) == 13
    today = {name: pair[0] for name, pair in pairs.items()}
    assert today == {name: pair[1] for name, pair in pairs.items()}


def test_hostos_imports_only_the_standard_library():
    """The CLI imports it and runs on a bare python3 (AGENTS.md invariant 3): `-S` leaves site-packages
    out, and `-I` keeps the working folder off the path."""
    load = (
        "import importlib.util as u, sys; "
        "s = u.spec_from_file_location('h', sys.argv[1]); s.loader.exec_module(u.module_from_spec(s))"
    )
    proc = subprocess.run(
        [sys.executable, "-I", "-S", "-c", load, str(SOURCE)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("platform", PLATFORMS)
def test_every_function_answers_on_every_platform(hostos, monkeypatch, tmp_path, platform):
    on(monkeypatch, platform)
    monkeypatch.setattr(signal, "SIGBREAK", 21, raising=False)
    assert isinstance(hostos.default_root(), Path)
    assert isinstance(hostos.lock_dir(), Path)
    assert isinstance(hostos.venv_python(tmp_path), Path)
    assert hostos.kicad_python() is None or isinstance(hostos.kicad_python(), str)
    assert all(isinstance(c, str) for c in hostos.kicad_cli_candidates())
    assert all(isinstance(c, str) for c in hostos.ngspice_candidates())
    assert set(hostos.kicad_dirs()) == {"symbols", "footprints", "3dmodels"}
    assert isinstance(hostos.awt_lib(tmp_path), Path)
    assert signal.SIGTERM in hostos.stop_signals()
