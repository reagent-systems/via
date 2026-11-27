"""tools/hostos.py: every difference between Linux, macOS and Windows that the CLI needs, in 1 place.

On Linux each function returns what the code returns today, at the file and line its comment names.
Each test sets `sys.platform` to linux, darwin or win32, and the environment variables and files the
function reads. `os.name` is not set: hostos reads `sys.platform` alone, and pathlib builds a
WindowsPath, which Linux cannot make, whenever `os.name` is "nt".

The module is loaded from its file for each test, under a name of its own: no folder is put on
`sys.path` and no other test's `import hostos` gets this copy (PROCESSES.md P12 step 12).
"""

from __future__ import annotations

import errno
import importlib.util
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path, PureWindowsPath

import pytest
from conftest import posix_only, stand_in

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
    "JAVA_HOME",
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
    """Set the platform. A run on Windows stands in the POSIX names its Python lacks (os.getuid,
    os.killpg, SIGHUP, SIGKILL) for a test of Linux or macOS; a POSIX run keeps its own."""
    monkeypatch.setattr(sys, "platform", platform)
    if platform != "win32":
        for module, name, value in (
            (os, "getuid", lambda: 1000),
            (os, "killpg", lambda pid, sig: None),
            (signal, "SIGHUP", 1),
            (signal, "SIGKILL", 9),
        ):
            if not hasattr(module, name):
                monkeypatch.setattr(module, name, value, raising=False)


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
    monkeypatch.delattr(os, "getuid", raising=False)
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


# ------------------------------------------------------------------ java_home


def program(path: Path, text: str = "") -> Path:
    """A file that can run: a stand-in java, or a stand-in /usr/libexec/java_home."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)
    return path


@posix_only("it makes symbolic links, which Windows refuses without Developer Mode")
@pytest.mark.parametrize("platform", PLATFORMS)
def test_java_home_is_the_folder_above_bin_with_links_resolved(hostos, monkeypatch, tmp_path, platform):
    """routers.py:93 on Linux: /usr/bin/java -> /etc/alternatives/java -> the JVM's bin/java. Homebrew's
    openjdk on macOS links its bin/java the same way into the bundle's Contents/Home."""
    on(monkeypatch, platform)
    home = tmp_path / "jvm" / "java-21-openjdk-amd64"
    java = program(home / "bin" / "java")
    (tmp_path / "alternatives").mkdir()
    (tmp_path / "alternatives" / "java").symlink_to(java)
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "java").symlink_to(tmp_path / "alternatives" / "java")
    assert hostos.java_home(tmp_path / "bin" / "java") == home.resolve()
    assert hostos.java_home(str(java)) == home.resolve()


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_java_home_reads_no_java_home_variable_off_the_launchers(hostos, monkeypatch, tmp_path, platform):
    on(monkeypatch, platform)
    monkeypatch.setenv("JAVA_HOME", str(tmp_path / "elsewhere"))
    java = program(tmp_path / "jdk" / "bin" / "java")
    assert hostos.java_home(java) == (tmp_path / "jdk").resolve()


def test_java_home_on_macos_follows_the_usr_bin_stub_to_java_home(hostos, monkeypatch, tmp_path):
    """Apple's /usr/bin/java is a launcher, not a JVM: the folder above it is /usr. It runs the JDK that
    JAVA_HOME names, else the one /usr/libexec/java_home picks (Apple's java_home(1))."""
    on(monkeypatch, "darwin")
    stub = program(tmp_path / "usr" / "bin" / "java").resolve()
    monkeypatch.setattr(hostos, "MAC_JAVA_STUB", stub)
    jdk = tmp_path / "Library/Java/JavaVirtualMachines/temurin-21.jdk/Contents/Home"
    tool = stand_in(tmp_path / "usr" / "libexec" / "java_home", f"print({str(jdk)!r})\n")
    monkeypatch.setattr(hostos, "MAC_JAVA_HOME", tool)
    assert hostos.java_home(stub) == jdk
    monkeypatch.setenv("JAVA_HOME", str(tmp_path / "named"))
    assert hostos.java_home(stub) == tmp_path / "named"


# What the stand-in java_home does, by the shell line each case once was (conftest.stand_in: no shell).
JAVA_HOME_SAYS = {
    "exit 1": "import sys\nsys.exit(1)\n",
    "echo /x; exit 1": "import sys\nprint('/x')\nsys.exit(1)\n",
    "echo a; echo b": "print('a')\nprint('b')\n",
    "": "",
}


@pytest.mark.parametrize("said", ["exit 1", "echo /x; exit 1", "echo a; echo b", "", "missing"])
def test_java_home_on_macos_keeps_usr_when_java_home_names_no_jdk(hostos, monkeypatch, tmp_path, said):
    """No JDK installed: java_home exits 1 ("Unable to locate a Java Runtime"). The folder stays the
    stub's, so the caller names what is missing there. A line it prints before it fails names no JDK."""
    on(monkeypatch, "darwin")
    stub = program(tmp_path / "usr" / "bin" / "java").resolve()
    monkeypatch.setattr(hostos, "MAC_JAVA_STUB", stub)
    tool = tmp_path / "usr" / "libexec" / "java_home"
    if said != "missing":
        tool = stand_in(tool, JAVA_HOME_SAYS[said])
    monkeypatch.setattr(hostos, "MAC_JAVA_HOME", tool)
    assert hostos.java_home(stub) == stub.parent.parent


def test_java_home_on_windows_follows_oracles_javapath_to_java_home(hostos, monkeypatch, tmp_path):
    """Oracle's installer puts launchers in Common Files\\Oracle\\Java\\javapath; the JDK is the one
    JAVA_HOME names. Without it the folder stays the launcher's."""
    on(monkeypatch, "win32")
    java = program(tmp_path / "Common Files" / "Oracle" / "Java" / "javapath" / "java.exe")
    assert hostos.java_home(java) == (tmp_path / "Common Files" / "Oracle" / "Java").resolve()
    monkeypatch.setenv("JAVA_HOME", str(tmp_path / "jdk-21"))
    assert hostos.java_home(java) == tmp_path / "jdk-21"


# ------------------------------------------------------------------ own_group and stop_tree


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_own_group_on_posix_is_a_new_session(hostos, monkeypatch, platform):
    """routers.py:266, routebench.py:249, mcpserver.py:439."""
    on(monkeypatch, platform)
    assert hostos.own_group() == {"start_new_session": True}


def test_own_group_on_windows_is_a_new_process_group(hostos, monkeypatch):
    """start_new_session does nothing on Windows; CREATE_NEW_PROCESS_GROUP (0x200, Microsoft's process
    creation flags) makes the child lead a group that Ctrl+Break can reach alone."""
    on(monkeypatch, "win32")
    monkeypatch.delattr(subprocess, "CREATE_NEW_PROCESS_GROUP", raising=False)
    assert hostos.own_group() == {"creationflags": 0x200}


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_stop_tree_on_posix_sends_sigterm_to_the_group(hostos, monkeypatch, platform):
    """mcpserver.py:498 and :517."""
    on(monkeypatch, platform)
    sent = []
    monkeypatch.setattr(os, "killpg", lambda pid, sig: sent.append((pid, sig)))
    hostos.stop_tree(Proc())
    assert sent == [(4242, signal.SIGTERM)]


def test_stop_tree_on_windows_sends_ctrl_break_to_the_group(hostos, monkeypatch):
    """CTRL_BREAK_EVENT is 1 (Microsoft's GenerateConsoleCtrlEvent); os.kill sends it to the process
    group the pid leads (Python's os.kill)."""
    on(monkeypatch, "win32")
    monkeypatch.delattr(os, "killpg", raising=False)
    monkeypatch.delattr(signal, "CTRL_BREAK_EVENT", raising=False)
    sent = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: sent.append((pid, sig)))
    hostos.stop_tree(Proc())
    assert sent == [(4242, 1)]


# ------------------------------------------------------------------ stop_signals


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_stop_signals_on_posix_are_term_and_hup(hostos, monkeypatch, platform):
    """enginelock.py:466."""
    on(monkeypatch, platform)
    assert hostos.stop_signals() == (signal.SIGTERM, signal.SIGHUP)


def test_stop_signals_on_windows_are_term_and_break_and_need_no_hup(hostos, monkeypatch):
    on(monkeypatch, "win32")
    monkeypatch.delattr(signal, "SIGHUP", raising=False)
    monkeypatch.setattr(signal, "SIGBREAK", 21, raising=False)
    assert hostos.stop_signals() == (signal.SIGTERM, 21)


def test_stop_signals_leave_out_a_signal_the_python_lacks(hostos, monkeypatch):
    on(monkeypatch, "win32")
    monkeypatch.delattr(signal, "SIGBREAK", raising=False)
    assert hostos.stop_signals() == (signal.SIGTERM,)


# ------------------------------------------------------------------ signal_ends_reads


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_on_posix_a_signal_ends_a_read_so_its_handler_runs(hostos, monkeypatch, platform):
    """tools/mcpserver.py:631 at e702b47 reads stdin on the main thread: a signal there interrupts the
    read (EINTR) and Python runs the handler at once."""
    on(monkeypatch, platform)
    assert hostos.signal_ends_reads() is True


def test_on_windows_a_signal_does_not_end_a_read(hostos, monkeypatch):
    """Windows runs a console control handler on a thread of its own, and a read on a pipe has no
    EINTR: Python's handler waits until the read returns."""
    on(monkeypatch, "win32")
    assert hostos.signal_ends_reads() is False


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
    monkeypatch.delattr(os, "killpg", raising=False)
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


# ------------------------------------------------------------------ program_name

KNOWN = {"kicad-cli", "ngspice", "openEMS", "xvfb-run"}


@pytest.mark.parametrize(
    ("word", "name"),
    [
        ("/usr/bin/kicad-cli", "kicad-cli"),
        ("kicad-cli", "kicad-cli"),
        ("kicad-cli.exe", "kicad-cli.exe"),
        ("/opt/x/OPENEMS", "OPENEMS"),
    ],
)
@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_program_name_on_posix_is_the_last_part_of_the_path(hostos, monkeypatch, platform, word, name):
    """engine_watch.py:93, os.path.basename: no extension is taken off, and case counts."""
    on(monkeypatch, platform)
    assert hostos.program_name(word, KNOWN) == name


@pytest.mark.parametrize(
    ("word", "name"),
    [
        ("C:\\Program Files\\KiCad\\10.0\\bin\\kicad-cli.exe", "kicad-cli"),
        ("C:/Spice64/bin/NGSPICE.EXE", "ngspice"),
        ("openems.exe", "openEMS"),
        ("kicad-cli.cmd", "kicad-cli"),
        ("kicad-cli", "kicad-cli"),
        ("kicad-cli.txt", "kicad-cli.txt"),
        ("notepad.exe", "notepad"),
    ],
)
def test_program_name_on_windows_takes_off_a_pathext_extension_and_reads_any_case(
    hostos, monkeypatch, word, name
):
    on(monkeypatch, "win32")
    monkeypatch.setenv("PATHEXT", ".COM;.EXE;.BAT;.CMD")
    assert hostos.program_name(word, KNOWN) == name


def test_program_name_on_windows_reads_pathext_and_has_a_default(hostos, monkeypatch):
    on(monkeypatch, "win32")
    monkeypatch.setenv("PATHEXT", ".PY")
    assert hostos.program_name("ngspice.py", KNOWN) == "ngspice"
    assert hostos.program_name("ngspice.exe", KNOWN) == "ngspice.exe"
    monkeypatch.delenv("PATHEXT")
    assert hostos.program_name("NGSPICE.EXE", KNOWN) == "ngspice"


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


def test_shell_word_on_windows_leaves_a_drive_path_as_written(hostos, monkeypatch):
    """Run 46067841222, Windows: next, new and the gates' ratings line printed
    `'D:\\a\\_temp\\...\\board'` (sh's quotes, which cmd.exe keeps as part of the name) where the
    path needs none."""
    on(monkeypatch, "win32")
    assert hostos.shell_word("D:\\a\\_temp\\board") == "D:\\a\\_temp\\board"


@pytest.mark.parametrize(
    ("platform", "line"),
    [
        ("linux", "workcenter sim '/home/a b/board' --out /tmp/o"),
        ("darwin", "workcenter sim '/home/a b/board' --out /tmp/o"),
        ("win32", 'workcenter sim "/home/a b/board" --out /tmp/o'),
    ],
)
def test_shell_line_quotes_each_word_as_shell_word_does(hostos, monkeypatch, platform, line):
    """A whole command line, as the engine lock names its holder: shlex.join on Linux and macOS."""
    on(monkeypatch, platform)
    words = ["workcenter", "sim", "/home/a b/board", "--out", "/tmp/o"]
    assert hostos.shell_line(words) == line
    if platform != "win32":
        assert hostos.shell_line(words) == shlex.join(words)


# ------------------------------------------------------------------ installer_command


def test_installer_command_on_linux_is_todays_line_of_next(hostos, monkeypatch):
    """tools/guide.py:834 at cea464d: `sudo <src>/install.sh`."""
    on(monkeypatch, "linux")
    src = Path("/opt/workcenters/ee/src")
    assert hostos.installer_command(src) == "sudo /opt/workcenters/ee/src/install.sh"


def test_installer_command_on_macos_needs_no_sudo_and_quotes_a_space(hostos, monkeypatch):
    on(monkeypatch, "darwin")
    src = Path("/Users/ada/Library/Application Support/via/src")
    assert hostos.installer_command(src) == f"'{src}/install-macos.sh'"
    assert hostos.installer_command(Path("/opt/via")) == "/opt/via/install-macos.sh"


@pytest.mark.parametrize(
    ("platform", "said"), [("linux", "sudo /opt/via/install.sh"), ("darwin", "/opt/via/install-macos.sh")]
)
def test_installer_command_for_linux_and_macos_writes_the_path_with_slashes(
    hostos, monkeypatch, platform, said
):
    """A Path made on Windows prints `\\opt\\via`: a line for sh is written with `/` whatever the host
    (run 46067841222, Windows: `'\\opt\\via/install-macos.sh'`, `sudo \\opt\\...\\install.sh`)."""
    on(monkeypatch, platform)
    assert hostos.installer_command(PureWindowsPath("\\opt\\via")) == said
    assert hostos.installer_command(PureWindowsPath("\\opt\\via\\")) == said


def test_installer_command_on_windows_runs_the_powershell_script_in_double_quotes(hostos, monkeypatch):
    """Double quotes hold a path in cmd.exe and in PowerShell alike; a Windows file name holds none."""
    on(monkeypatch, "win32")
    src = "C:\\Users\\Ada Lovelace\\AppData\\Local\\Via\\src"
    said = hostos.installer_command(src)
    assert said == f'powershell -NoProfile -ExecutionPolicy Bypass -File "{src}\\install.ps1"'
    assert "sudo" not in said and "'" not in said


@pytest.mark.parametrize("src", ["C:\\via\\src\\", "C:\\via\\src/", "C:\\via\\src"])
def test_installer_command_on_windows_puts_1_backslash_before_the_script(hostos, monkeypatch, src):
    """A source folder given with a separator at its end still names `C:\\via\\src\\install.ps1`."""
    on(monkeypatch, "win32")
    said = hostos.installer_command(src)
    assert said == 'powershell -NoProfile -ExecutionPolicy Bypass -File "C:\\via\\src\\install.ps1"'


# ------------------------------------------------------------------ the module

# Run in a child process, so this session's import path and modules stay as they are: each pair is
# (what the code held at main cea464d, written out as it was there, what hostos or its caller returns on
# Linux now). The callers take these values from hostos, so comparing with them would compare hostos with
# itself: the first of each pair is cea464d's own expression (tools/workcenter:40-44 and 70,
# tools/routers.py:31 and 49, tools/kicadgen.py:46-47, tools/enginelock.py:132 and 466).
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
env = os.environ.get
root = env("WORKCENTER_ROOT", "/opt/workcenters/ee")
venv_py = root + "/venv/bin/python"
kicad_py = venv_py if os.path.exists(venv_py) else sys.executable
symbols = env("KICAD_SYMBOL_DIR", "/usr/share/kicad/symbols")
footprints = env("KICAD_FOOTPRINT_DIR", "/usr/share/kicad/footprints")
models = env("KICAD10_3DMODEL_DIR", "/usr/share/kicad/3dmodels")
lock = f"/tmp/workcenter-lock-{os.getuid()}"
pairs = {
    "default_root": [root, env("WORKCENTER_ROOT", str(hostos.default_root()))],
    "wc_root": [root, str(wc.WC_ROOT)],
    "routers_root": [root, str(routers.WC_ROOT)],
    "lock_dir": [lock, str(hostos.lock_dir())],
    "enginelock_dir": [lock, str(enginelock.lock_dir())],
    "venv_python": [venv_py, str(hostos.venv_python(root))],
    "kicad_python": [kicad_py, hostos.kicad_python()],
    "wc_venv_python": [kicad_py, wc.venv_python()],
    "kicad_cli": [[env("KICAD_CLI", "kicad-cli")], hostos.kicad_cli_candidates()],
    "wc_kicad_cli": [env("KICAD_CLI", "kicad-cli"), wc.KICAD_CLI],
    "ngspice": [[env("NGSPICE", "ngspice")], hostos.ngspice_candidates()],
    "wc_ngspice": [env("NGSPICE", "ngspice"), wc.NGSPICE],
    "symbols": [symbols, str(hostos.kicad_dirs()["symbols"])],
    "kicadgen_symbols": [symbols, str(kicadgen.SYMBOL_DIR)],
    "footprints": [footprints, str(hostos.kicad_dirs()["footprints"])],
    "kicadgen_footprints": [footprints, str(kicadgen.FOOTPRINT_DIR)],
    "3dmodels": [models, str(hostos.kicad_dirs()["3dmodels"])],
    "wc_3dmodels": ["/usr/share/kicad/3dmodels", wc.DEFAULT_3DMODEL_DIR],
    "awt_lib": ["/java/home/lib/libawt_xawt.so", str(hostos.awt_lib(Path("/java/home")))],
    "stop_signals": [[int(signal.SIGTERM), int(signal.SIGHUP)], [int(s) for s in hostos.stop_signals()]],
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
    assert len(pairs) == 21
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
    assert isinstance(hostos.java_home(sys.executable), Path)
    assert set(hostos.own_group()) <= {"start_new_session", "creationflags"}
    assert isinstance(hostos.installer_command(tmp_path), str)


# ------------------------------------------------------------------ the engine lock's file lock


class FakeMsvcrt:
    """A stand-in for Windows' msvcrt: each call to `locking` is recorded with the file position it ran
    at, and answers in turn from `answers` (None takes the lock; an errno raises OSError with it)."""

    LK_UNLCK, LK_LOCK, LK_NBLCK, LK_RLCK, LK_NBRLCK = 0, 1, 2, 3, 4

    def __init__(self, answers=()):
        self.calls: list[tuple[int, int, int]] = []
        self.answers = list(answers)

    def locking(self, fd, mode, nbytes):
        self.calls.append((mode, nbytes, os.lseek(fd, 0, os.SEEK_CUR)))
        answer = self.answers.pop(0) if self.answers else None
        if answer is not None:
            raise OSError(answer, os.strerror(answer))


@pytest.fixture
def fake_msvcrt(monkeypatch):
    fake = FakeMsvcrt()
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    monkeypatch.setitem(sys.modules, "fcntl", None)
    return fake


def opened(path: Path) -> int:
    path.touch()
    return os.open(path, os.O_RDWR)


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_lock_file_on_posix_is_flock_and_a_second_descriptor_waits(hostos, monkeypatch, tmp_path, platform):
    """enginelock.py:197 and :421: flock(LOCK_EX | LOCK_NB). The lock belongs to the open file, so a
    second open of the same file in the same process does not get it until the first is closed."""
    on(monkeypatch, platform)
    first, second = opened(tmp_path / "t"), os.open(tmp_path / "t", os.O_RDONLY)
    try:
        assert hostos.lock_file(first) is True
        assert hostos.lock_file(second) is False
        hostos.unlock_file(first)  # nothing on POSIX: close(2) drops a flock at once
        assert hostos.lock_file(second) is False
    finally:
        os.close(first)
    try:
        assert hostos.lock_file(second) is True
    finally:
        os.close(second)


def test_lock_file_on_windows_locks_1_byte_past_any_text(hostos, monkeypatch, tmp_path, fake_msvcrt):
    """msvcrt.locking locks from the file's position, and Windows stops reads of a locked byte too: the
    lock is taken on byte 2**30, which no ticket reaches, with LK_NBLCK (no wait)."""
    on(monkeypatch, "win32")
    fd = opened(tmp_path / "t")
    try:
        assert hostos.lock_file(fd) is True
        hostos.unlock_file(fd)
    finally:
        os.close(fd)
    assert fake_msvcrt.calls == [(2, 1, 1 << 30), (0, 1, 1 << 30)]


def test_lock_file_on_windows_says_false_when_another_handle_holds_it(hostos, monkeypatch, tmp_path):
    """msvcrt.locking raises OSError with EACCES when the bytes are locked (the CRT's _locking)."""
    on(monkeypatch, "win32")
    fake = FakeMsvcrt([errno.EACCES])
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    fd = opened(tmp_path / "t")
    try:
        assert hostos.lock_file(fd) is False
    finally:
        os.close(fd)
    assert len(fake.calls) == 1


def test_lock_file_on_windows_waits_by_trying_again(hostos, monkeypatch, tmp_path):
    """LK_LOCK gives up after 10 tries 1 s apart; a wait for `.seq` has no limit, as flock's has none:
    LK_NBLCK again until it takes the lock (here the 3rd try)."""
    on(monkeypatch, "win32")
    fake = FakeMsvcrt([errno.EACCES, errno.EACCES])
    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    fd = opened(tmp_path / "t")
    try:
        assert hostos.lock_file(fd, wait=True) is True
    finally:
        os.close(fd)
    assert [c[0] for c in fake.calls] == [2, 2, 2]


def test_lock_file_on_windows_raises_any_other_error(hostos, monkeypatch, tmp_path):
    on(monkeypatch, "win32")
    monkeypatch.setitem(sys.modules, "msvcrt", FakeMsvcrt([errno.EBADF]))
    fd = opened(tmp_path / "t")
    try:
        with pytest.raises(OSError):
            hostos.lock_file(fd)
    finally:
        os.close(fd)


@pytest.mark.parametrize("platform", PLATFORMS)
def test_flock_files_is_false_only_on_windows(hostos, monkeypatch, platform):
    on(monkeypatch, platform)
    assert hostos.flock_files() is (platform != "win32")


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_user_id_on_posix_is_getuid(hostos, monkeypatch, platform):
    """enginelock.py:153: the lock folder must be the user's own."""
    on(monkeypatch, platform)
    assert hostos.user_id() == os.getuid()


def test_user_id_on_windows_is_none_and_needs_no_getuid(hostos, monkeypatch):
    on(monkeypatch, "win32")
    monkeypatch.delattr(os, "getuid", raising=False)
    assert hostos.user_id() is None
