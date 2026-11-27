"""`workcenter doctor` and the paths it reads, on Linux, macOS and Windows.

The root, the venv's Python, kicad-cli, ngspice and KiCad's library folders come from tools/hostos.py.
kicad-cli and ngspice are found on PATH first, then where hostos says an install puts them; doctor says
where it looked when it finds neither. Off Linux the xvfb row is not applicable. The `kicad-python` row
names the Python that imports KiCad's pcbnew, and the `pcbnew` row asks it, as a child process.

Nothing here runs on a Mac or on Windows. The doctor runs whole in a child process that sets
`sys.platform` to darwin or win32 before it loads the CLI, on a made-up root, made-up KiCad folders and
made-up engines (shell scripts that print a version). `os.name` stays "posix": pathlib cannot build a
WindowsPath on Linux. On win32, shutil.which asks `_winapi`, which Linux lacks; a stand-in answers that
the working folder is never searched.
"""

from __future__ import annotations

import importlib.machinery
import json
import os
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
MAC_CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
BUNDLED = Path("Contents/Frameworks/Python.framework/Versions/Current/bin/python3")
# The rows doctor has at main cea464d, in order, on a root with no chip engines.
ROWS_TODAY = [
    "kicad-cli",
    "ngspice",
    "python",
    "java",
    "freerouting",
    "freerouting2",
    "venv",
    "requirements",
    "xvfb",
    "rsvg-convert",
    "ffmpeg",
    "openems",
    "symbols",
    "manifest",
    "no-cd hook",
    "test hook",
    "kistack",
    "node",
]

pytestmark = pytest.mark.skipif(os.name != "posix", reason="the made-up engines are shell scripts")


def load_cli_module():
    loader = importlib.machinery.SourceFileLoader("workcenter_cli_platforms", str(CLI))
    module = types.ModuleType("workcenter_cli_platforms")
    module.__file__ = str(CLI)
    sys.modules[module.__name__] = module
    loader.exec_module(module)
    return module


wc = load_cli_module()


def program(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def a_python(path: Path, mods: Path, pcbnew: str | None = "10.0.8") -> Path:
    """A made-up Python: this test's own, with a folder first on its path that holds a made-up pcbnew.
    Without a version, that pcbnew fails to import as an absent one does, whatever this Python has."""
    mods.mkdir(parents=True, exist_ok=True)
    if pcbnew is not None:
        (mods / "pcbnew.py").write_text(f"def Version():\n    return {pcbnew!r}\n", encoding="utf-8")
    else:
        absent = "raise ModuleNotFoundError(\"No module named 'pcbnew'\", name='pcbnew')\n"
        (mods / "pcbnew.py").write_text(absent, encoding="utf-8")
    return program(path, f'PYTHONPATH="{mods}" exec "{sys.executable}" "$@"')


def kicad_cli(path: Path, version: str = "10.0.8") -> Path:
    return program(path, f"echo {version}")


def ngspice(path: Path, version: str = "47") -> Path:
    return program(path, f"echo '******'; echo '** ngspice-{version} : Circuit level simulation program'")


def library(symbols: Path) -> Path:
    symbols.mkdir(parents=True, exist_ok=True)
    (symbols / "Device.kicad_sym").write_text("(kicad_symbol_lib)\n", encoding="utf-8")
    return symbols


# Sets the platform once every module the standard library picks a platform for at import is loaded:
# urllib.request asks macOS's _scproxy when it sees darwin.
PRELOAD = "import os, runpy, shutil, subprocess, sys, types, urllib.request, xml.sax.saxutils\n"
RUNNER = (
    PRELOAD
    + """
platform, cli, *argv = sys.argv[1:]
if platform == "win32":
    shutil._winapi = types.SimpleNamespace(NeedCurrentDirectoryForExePath=lambda cmd: False)
sys.platform = platform
sys.argv = [cli, *argv]
runpy.run_path(cli, run_name="__main__")
"""
)


def doctor(tmp_path: Path, platform: str, env: dict[str, str], *argv: str) -> subprocess.CompletedProcess:
    base = {
        "PATH": str(tmp_path / "bin"),
        "HOME": str(tmp_path / "home"),
        "LANG": "C.UTF-8",
        "WORKCENTER_LOCK_DIR": str(tmp_path / "lock"),
        "JAVA": str(tmp_path / "absent"),
    }
    (tmp_path / "bin").mkdir(exist_ok=True)
    return subprocess.run(
        [sys.executable, "-I", "-c", RUNNER, platform, str(CLI), *argv],
        capture_output=True,
        text=True,
        env={**base, **env},
        cwd=str(tmp_path),
        timeout=300,
        check=False,
    )


def doctor_json(tmp_path: Path, platform: str, env: dict[str, str]) -> dict:
    proc = doctor(tmp_path, platform, env, "--json", "doctor")
    assert "Traceback" not in proc.stderr, proc.stderr
    return json.loads(proc.stdout)


# ------------------------------------------------------------------ find_program


def test_a_single_candidate_is_kept_as_written_found_or_not(tmp_path, monkeypatch):
    """Linux has 1 candidate, KICAD_CLI's or `kicad-cli`: the constant stays what it is today."""
    monkeypatch.setenv("PATH", str(tmp_path))
    assert wc.find_program(["kicad-cli"]) == "kicad-cli"
    assert wc.find_program([str(tmp_path / "absent")]) == str(tmp_path / "absent")


def test_the_name_on_path_wins_over_an_install(tmp_path, monkeypatch):
    on_path = kicad_cli(tmp_path / "bin" / "kicad-cli")
    installed = kicad_cli(tmp_path / "app" / "kicad-cli")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    assert wc.find_program(["kicad-cli", str(installed)]) == str(on_path)


def test_an_install_is_taken_when_path_lacks_the_name(tmp_path, monkeypatch):
    installed = kicad_cli(tmp_path / "app" / "kicad-cli")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    assert wc.find_program(["kicad-cli", str(tmp_path / "gone"), str(installed)]) == str(installed)


def test_with_nothing_found_the_first_candidate_is_named(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    assert wc.find_program(["ngspice", "/opt/homebrew/bin/ngspice"]) == "ngspice"


def test_where_doctor_looked_names_path_first_then_each_folder():
    line = wc.looked_line(["ngspice", "/opt/homebrew/bin/ngspice", "/usr/local/bin/ngspice"])
    said = "looked on PATH for ngspice, then at /opt/homebrew/bin/ngspice, then at /usr/local/bin/ngspice"
    assert line == said
    assert wc.looked_line(["kicad-cli"]) == "looked on PATH for kicad-cli"


# ------------------------------------------------------------------ the venv's programs


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_a_venv_program_on_posix_is_in_bin(monkeypatch, platform):
    monkeypatch.setattr(sys, "platform", platform)
    assert wc.venv_program(Path("/w/venv"), "python") == Path("/w/venv/bin/python")
    assert wc.venv_program(Path("/w/venv"), "pip") == Path("/w/venv/bin/pip")


def test_a_venv_program_on_windows_is_an_exe_in_scripts(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert wc.venv_program(Path("/w/venv"), "python") == Path("/w/venv/Scripts/python.exe")
    assert wc.requirements_fix(Path("/w/venv"), Path("/s")) == (
        "/w/venv/Scripts/pip.exe install -q -r /s/requirements.txt"
    )


def test_venv_python_is_the_roots_venv_on_each_platform(tmp_path, monkeypatch):
    monkeypatch.setattr(wc, "WC_ROOT", tmp_path)
    for platform, py in (("linux", "venv/bin/python"), ("win32", "venv/Scripts/python.exe")):
        monkeypatch.setattr(sys, "platform", platform)
        assert wc.venv_python() == sys.executable
        program(tmp_path / py, "exit 0")
        assert wc.venv_python() == str(tmp_path / py)


def test_a_row_that_does_not_apply_reads_n_a():
    row = {"required": False, "advisory": True, "ok": False, "applicable": False, "line": "not on darwin"}
    assert wc.doctor_row_text("xvfb", row) == [f"  {'n/a':8} {'xvfb':12} not on darwin"]
    assert wc.doctor_checks_degraded({"xvfb": row}) == []


# ------------------------------------------------------------------ doctor on Linux


def linux_machine(tmp_path: Path) -> dict[str, str]:
    root = tmp_path / "root"
    a_python(root / "venv" / "bin" / "python", tmp_path / "mods")
    kicad_cli(tmp_path / "bin" / "kicad-cli")
    ngspice(tmp_path / "bin" / "ngspice", "42")
    program(tmp_path / "bin" / "Xvfb", "exit 0")
    library(tmp_path / "symbols")
    return {"WORKCENTER_ROOT": str(root), "KICAD_SYMBOL_DIR": str(tmp_path / "symbols")}


def test_doctor_on_linux_keeps_todays_rows_and_adds_kicad_python_and_pcbnew(tmp_path):
    said = doctor_json(tmp_path, "linux", linux_machine(tmp_path))
    rows = said["checks"]
    assert [r for r in rows if r not in ("kicad-python", "pcbnew")] == ROWS_TODAY
    assert list(rows)[3:5] == ["kicad-python", "pcbnew"]
    assert said["root"] == str(tmp_path / "root")
    assert rows["kicad-cli"] == {"required": True, "ok": True, "version": "10.0.8"}
    assert rows["ngspice"] == {"required": True, "ok": True, "version": "42"}
    assert rows["xvfb"] == {"required": False, "ok": True}
    py = str(tmp_path / "root" / "venv" / "bin" / "python")
    assert rows["venv"] == {"required": False, "ok": True, "path": str(tmp_path / "root" / "venv")}
    assert rows["kicad-python"]["path"] == py and rows["kicad-python"]["ok"] is True
    assert rows["kicad-python"]["version"] == ".".join(map(str, sys.version_info[:3]))
    assert rows["pcbnew"] == {"required": False, "ok": True, "version": "10.0.8", "path": py}
    assert rows["symbols"] == {"required": False, "ok": True, "path": str(tmp_path / "symbols")}


def test_doctor_on_linux_without_pcbnew_is_degraded_and_says_why(tmp_path):
    env = linux_machine(tmp_path)
    a_python(tmp_path / "root" / "venv" / "bin" / "python", tmp_path / "mods", pcbnew=None)
    said = doctor_json(tmp_path, "linux", env)
    row = said["checks"]["pcbnew"]
    assert row["ok"] is False and row["required"] is False
    assert "pcbnew" in said["degraded"] and "pcbnew" not in said["missing_required"]
    assert row["lines"] == ["ModuleNotFoundError: No module named 'pcbnew'"]
    assert said["checks"]["kicad-python"]["ok"] is True


def test_doctor_on_linux_without_engines_says_where_it_looked(tmp_path):
    env = linux_machine(tmp_path)
    (tmp_path / "bin" / "kicad-cli").unlink()
    (tmp_path / "bin" / "ngspice").unlink()
    said = doctor_json(tmp_path, "linux", env)
    assert said["checks"]["kicad-cli"]["lines"] == ["looked on PATH for kicad-cli"]
    assert said["checks"]["ngspice"]["lines"] == ["looked on PATH for ngspice"]
    assert said["missing_required"][:2] == ["kicad-cli", "ngspice"]


# ------------------------------------------------------------------ doctor on macOS


def mac_machine(tmp_path: Path) -> dict[str, str]:
    """KiCad's bundle where KICAD_CLI names it, Homebrew's ngspice on PATH, Via's root in the user's
    Application Support."""
    app = tmp_path / "Applications" / "KiCad" / "KiCad.app"
    kicad_cli(app / "Contents" / "MacOS" / "kicad-cli")
    a_python(app / BUNDLED, tmp_path / "mods")
    library(app / "Contents" / "SharedSupport" / "symbols")
    ngspice(tmp_path / "bin" / "ngspice")
    via = tmp_path / "home" / "Library" / "Application Support" / "via"
    a_python(via / "venv" / "bin" / "python", tmp_path / "via-mods", pcbnew=None)
    return {"KICAD_CLI": str(app / "Contents" / "MacOS" / "kicad-cli")}


def test_doctor_on_macos_reads_kicads_bundle_and_the_users_root(tmp_path):
    said = doctor_json(tmp_path, "darwin", mac_machine(tmp_path))
    rows = said["checks"]
    app = tmp_path / "Applications" / "KiCad" / "KiCad.app"
    via = tmp_path / "home" / "Library" / "Application Support" / "via"
    assert said["root"] == str(via)
    assert rows["kicad-cli"] == {
        "required": True,
        "ok": True,
        "version": "10.0.8",
        "path": str(app / "Contents" / "MacOS" / "kicad-cli"),
    }
    brew = str(tmp_path / "bin" / "ngspice")
    assert rows["ngspice"] == {"required": True, "ok": True, "version": "47", "path": brew}
    assert rows["venv"] == {"required": False, "ok": True, "path": str(via / "venv")}
    assert rows["kicad-python"]["path"] == str(app / BUNDLED) and rows["kicad-python"]["ok"] is True
    assert rows["pcbnew"] == {"required": False, "ok": True, "version": "10.0.8", "path": str(app / BUNDLED)}
    assert rows["symbols"] == {
        "required": False,
        "ok": True,
        "path": str(app / "Contents" / "SharedSupport" / "symbols"),
    }
    assert rows["xvfb"]["applicable"] is False and rows["xvfb"]["advisory"] is True
    assert "xvfb" not in said["degraded"] and "xvfb" not in said["missing_required"]


def test_doctor_text_on_macos_marks_xvfb_n_a(tmp_path):
    proc = doctor(tmp_path, "darwin", mac_machine(tmp_path), "doctor")
    assert "Traceback" not in proc.stderr, proc.stderr
    line = [x for x in proc.stdout.splitlines() if " xvfb " in x]
    assert len(line) == 1 and line[0].split()[0] == "n/a", proc.stdout
    assert "Linux" in line[0]


@pytest.mark.skipif(
    any(Path(p).exists() for p in (MAC_CLI, "/opt/homebrew/bin/ngspice", "/usr/local/bin/ngspice")),
    reason="this machine has a program where a Mac's install would put it",
)
def test_doctor_on_macos_without_kicad_says_where_it_looked(tmp_path):
    said = doctor_json(tmp_path, "darwin", {})
    rows = said["checks"]
    assert rows["kicad-cli"]["ok"] is False
    assert rows["kicad-cli"]["lines"] == [f"looked on PATH for kicad-cli, then at {MAC_CLI}"]
    assert rows["ngspice"]["lines"] == [
        "looked on PATH for ngspice, then at /opt/homebrew/bin/ngspice, then at /usr/local/bin/ngspice"
    ]
    assert rows["kicad-python"]["ok"] is False and rows["kicad-python"]["path"] is None
    assert rows["pcbnew"]["ok"] is False
    assert said["status"] == "fail"


# ------------------------------------------------------------------ doctor on Windows


def windows_machine(tmp_path: Path) -> dict[str, str]:
    """KiCad's machine install under a made-up Program Files, ngspice's console program on PATH, Via's
    root under a made-up LOCALAPPDATA. The programs are shell scripts named as Windows names them."""
    kicad = tmp_path / "pf" / "KiCad" / "10.0"
    kicad_cli(kicad / "bin" / "kicad-cli.exe")
    a_python(kicad / "bin" / "python.exe", tmp_path / "mods")
    library(kicad / "share" / "kicad" / "symbols")
    ngspice(tmp_path / "bin" / "ngspice_con.exe")
    via = tmp_path / "local" / "Via"
    a_python(via / "venv" / "Scripts" / "python.exe", tmp_path / "via-mods", pcbnew=None)
    return {"ProgramFiles": str(tmp_path / "pf"), "LOCALAPPDATA": str(tmp_path / "local"), "PATHEXT": ".exe"}


def test_doctor_on_windows_reads_the_machine_install_and_localappdata(tmp_path):
    said = doctor_json(tmp_path, "win32", windows_machine(tmp_path))
    rows = said["checks"]
    kicad = tmp_path / "pf" / "KiCad" / "10.0"
    via = tmp_path / "local" / "Via"
    assert said["root"] == str(via)
    assert rows["kicad-cli"] == {
        "required": True,
        "ok": True,
        "version": "10.0.8",
        "path": str(kicad / "bin" / "kicad-cli.exe"),
    }
    ngspice_con = str(tmp_path / "bin" / "ngspice_con.exe")
    assert rows["ngspice"] == {"required": True, "ok": True, "version": "47", "path": ngspice_con}
    assert rows["venv"] == {"required": False, "ok": True, "path": str(via / "venv")}
    py = str(kicad / "bin" / "python.exe")
    assert rows["kicad-python"]["path"] == py and rows["kicad-python"]["ok"] is True
    assert rows["pcbnew"] == {"required": False, "ok": True, "version": "10.0.8", "path": py}
    assert rows["symbols"]["path"] == str(kicad / "share" / "kicad" / "symbols") and rows["symbols"]["ok"]
    assert rows["xvfb"]["applicable"] is False
    assert said["missing_required"] == []


def test_doctor_on_windows_takes_kicad_cli_on_path_before_the_install(tmp_path):
    env = windows_machine(tmp_path)
    on_path = kicad_cli(tmp_path / "bin" / "kicad-cli.exe", "10.0.9")
    rows = doctor_json(tmp_path, "win32", env)["checks"]
    assert rows["kicad-cli"] == {"required": True, "ok": True, "version": "10.0.9", "path": str(on_path)}


def test_doctor_on_windows_without_kicad_says_where_it_looked(tmp_path):
    env = windows_machine(tmp_path)
    shutil.rmtree(tmp_path / "pf")
    (tmp_path / "bin" / "ngspice_con.exe").unlink()
    rows = doctor_json(tmp_path, "win32", env)["checks"]
    machine = tmp_path / "pf" / "KiCad" / "10.0" / "bin" / "kicad-cli.exe"
    user = tmp_path / "local" / "Programs" / "KiCad" / "10.0" / "bin" / "kicad-cli.exe"
    assert rows["kicad-cli"]["lines"] == [f"looked on PATH for kicad-cli, then at {machine}, then at {user}"]
    assert rows["ngspice"]["lines"][0].startswith("looked on PATH for ngspice_con, then on PATH for ngspice")
    assert rows["kicad-python"]["ok"] is False and rows["pcbnew"]["ok"] is False


# ------------------------------------------------------------------ the other tools' paths


def run_on(platform: str, code: str, env: dict[str, str]) -> str:
    """`code` in a child process that loads tools/ under `platform`, as tools/workcenter does."""
    head = (
        PRELOAD + "shutil._winapi = types.SimpleNamespace(NeedCurrentDirectoryForExePath=lambda cmd: False)\n"
        f"sys.platform = {platform!r}; sys.path.insert(0, {str(ROOT / 'tools')!r})\n"
    )
    proc = subprocess.run(
        [sys.executable, "-I", "-c", head + code],
        capture_output=True,
        text=True,
        env={"PATH": os.environ.get("PATH", ""), **env},
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_kicadgen_reads_its_library_folders_from_hostos(tmp_path, platform):
    env = {"HOME": str(tmp_path), "ProgramFiles": str(tmp_path / "pf"), "LOCALAPPDATA": str(tmp_path / "l")}
    said = run_on(
        platform,
        "import hostos, kicadgen; d = hostos.kicad_dirs()\n"
        "print(kicadgen.SYMBOL_DIR == d['symbols'] and kicadgen.FOOTPRINT_DIR == d['footprints'])\n"
        "print(kicadgen.SYMBOL_DIR)",
        env,
    )
    ok, symbols = said.splitlines()
    assert ok == "True"
    if platform == "linux":
        assert symbols == "/usr/share/kicad/symbols"


SHOW_SYMBOLS = "import kicadgen; print(kicadgen.SYMBOL_DIR)"


def test_kicadgen_on_linux_reads_no_kicad10_library_variable(tmp_path):
    """Linux keeps today's value: KICAD10_SYMBOL_DIR is KiCad's, and Via reads KICAD_SYMBOL_DIR there."""
    said = run_on("linux", SHOW_SYMBOLS, {"KICAD10_SYMBOL_DIR": str(tmp_path)})
    assert said == "/usr/share/kicad/symbols"


def test_kicadgen_on_macos_reads_kicad10_symbol_dir(tmp_path):
    said = run_on("darwin", SHOW_SYMBOLS, {"KICAD10_SYMBOL_DIR": str(tmp_path)})
    assert said == str(tmp_path)


@pytest.mark.parametrize(
    ("platform", "root"),
    [
        ("linux", "/opt/workcenters/ee"),
        ("darwin", "{home}/Library/Application Support/via"),
        ("win32", "{local}/Via"),
    ],
)
def test_the_openems_and_image_paths_follow_the_default_root(tmp_path, platform, root):
    env = {"HOME": str(tmp_path / "h"), "LOCALAPPDATA": str(tmp_path / "l")}
    root = root.format(home=tmp_path / "h", local=tmp_path / "l")
    said = run_on(
        platform,
        "import os, image, fields\n"
        "os.environ['OPENEMS'] = ''\n"
        "import shutil; shutil.which = lambda name: None\n"
        "seen = []\n"
        "import pathlib; real = pathlib.Path.is_file\n"
        "pathlib.Path.is_file = lambda self: seen.append(str(self)) or real(self)\n"
        "fields.OpenEMS.binary()\n"
        "print(image.RECORD); print(seen[0])",
        env,
    )
    record, openems = said.splitlines()
    assert record == f"{root}/image.json"
    assert openems == f"{root}/openems/bin/openEMS"


@pytest.mark.parametrize(
    ("platform", "venv_py"),
    [
        ("linux", "/opt/workcenters/ee/venv/bin/python"),
        ("darwin", "{home}/Library/Application Support/via/venv/bin/python"),
        ("win32", "{local}/Via/venv/Scripts/python.exe"),
    ],
)
def test_the_makefile_takes_its_venv_python_from_hostos(tmp_path, platform, venv_py):
    """The Makefile's VENV_PY is what its shell line prints; the line runs here with the platform set."""
    make = (ROOT / "Makefile").read_text(encoding="utf-8")
    line = next(x for x in make.splitlines() if x.startswith("VENV_PY :="))
    assert "hostos" in line, line
    env = {"HOME": str(tmp_path / "h"), "LOCALAPPDATA": str(tmp_path / "l")}
    said = run_on(platform, "import hostos; print(hostos.venv_python(hostos.default_root()))", env)
    assert said == venv_py.format(home=tmp_path / "h", local=tmp_path / "l")


@pytest.mark.skipif(shutil.which("make") is None, reason="make is not installed")
def test_the_makefile_on_this_machine_names_todays_venv_python(tmp_path):
    show = ["--eval", "show-venv: ; @echo $(VENV_PY)", "show-venv"]
    proc = subprocess.run(
        ["make", "-s", "-C", str(ROOT), "-f", "Makefile", *show],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == str(Path(wc.hostos.venv_python(wc.hostos.default_root())))
    if sys.platform.startswith("linux"):
        assert proc.stdout.strip() == "/opt/workcenters/ee/venv/bin/python"
