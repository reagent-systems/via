"""The tests on macOS and Windows: verify/desktop.csv, the stand-in engines, and conftest's no-home run.

verify/desktop.csv names every test file and where it runs: `desktop` (Linux, macOS and Windows; the
files that prove the gates and the platform layer), `posix` (not Windows) or `linux`. tests/conftest.py
skips a file at collection where its row says it does not run, with the row's reason, so the run's
`not judged:` lines name it and Windows never imports a file that needs fcntl or pwd.

verify/testshards.py runs the list on each system (`run --only verify/desktop.csv`) and ends its shards
through hostos.kill_tree; its tests for that are here too.

This machine is Linux. Each macOS and Windows case here sets sys.platform, takes a module away from
sys.modules, or runs the code the conftest would run there; none ran on a Mac or on Windows.
"""

from __future__ import annotations

import ast
import csv
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import conftest
import engine_watch
import pytest
import test_new
from test_testshards import FOUR, folder, gate, shard_of

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "verify" / "desktop.csv"
sys.path.insert(0, str(ROOT / "verify"))
import testshards  # noqa: E402

# The files that prove, on each system, the gates (ERC, DRC, SIM, EXPORT), design, next, doctor and the
# platform layer (tools/hostos.py, the engine lock, the runner of the list).
PROOF = {
    "tests/test_hostos.py",
    "tests/test_enginelock.py",
    "tests/test_testshards.py",
    "tests/test_desktop.py",
    "tests/test_gates.py",
    "tests/test_simgate.py",
    "tests/test_corners.py",
    "tests/test_freqplan.py",
    "tests/test_boardrules_drc.py",
    "tests/test_fab.py",
    "tests/test_fabexport.py",
    "tests/test_kicadgen.py",
    "tests/test_designfile.py",
    "tests/test_guide.py",
    "tests/test_done.py",
    "tests/test_new.py",
    "tests/test_doctor_requirements.py",
}


def rows() -> list[dict[str, str]]:
    with open(TABLE, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


# -- the table ------------------------------------------------------------------------------------------


def test_the_table_names_every_test_file_once_with_where_it_runs_and_why():
    found = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "tests").rglob("test_*.py"))
    names = [r["file"] for r in rows()]
    assert sorted(names) == found, "verify/desktop.csv must name every test file once"
    assert len(names) == len(set(names))
    for r in rows():
        assert r["runs"] in ("desktop", "posix", "linux"), r
        assert r["reason"].strip(), r


def test_the_files_that_prove_the_gates_run_on_every_system():
    desktop = {r["file"] for r in rows() if r["runs"] == "desktop"}
    assert PROOF <= desktop, sorted(PROOF - desktop)


@pytest.mark.parametrize(
    ("runs", "platform", "skipped"),
    [
        ("desktop", "linux", False),
        ("desktop", "darwin", False),
        ("desktop", "win32", False),
        ("posix", "linux", False),
        ("posix", "darwin", False),
        ("posix", "win32", True),
        ("linux", "linux", False),
        ("linux", "darwin", True),
        ("linux", "win32", True),
    ],
)
def test_a_row_skips_its_file_only_where_it_does_not_run(runs, platform, skipped):
    table = {"tests/test_x.py": (runs, "it reads /proc")}
    why = conftest.host_skip("tests/test_x.py", table, platform)
    if not skipped:
        assert why is None
    else:
        word = {"posix": "POSIX-only", "linux": "Linux-only"}[runs]
        assert why == f"{word}: it reads /proc (verify/desktop.csv)"


def test_a_file_the_table_does_not_name_is_not_skipped():
    assert conftest.host_skip("tests/test_new_file.py", {}, "win32") is None


@pytest.mark.parametrize(
    ("platform", "posix", "linux"), [("linux", False, False), ("darwin", False, True), ("win32", True, True)]
)
def test_the_marks_of_1_test_skip_it_where_it_cannot_run(monkeypatch, platform, posix, linux):
    """A file that runs on every system can hold a test that cannot: its mark says so, with the reason."""
    monkeypatch.setattr(sys, "platform", platform)
    one, two = conftest.posix_only("it sends SIGHUP"), conftest.linux_only("it reads /proc")
    assert (one.mark.name, one.mark.args, one.mark.kwargs) == (
        "skipif",
        (posix,),
        {"reason": "POSIX-only: it sends SIGHUP"},
    )
    assert (two.mark.args, two.mark.kwargs) == ((linux,), {"reason": "Linux-only: it reads /proc"})


def test_the_real_table_skips_on_windows_what_its_rows_say():
    table = conftest.host_rows(TABLE)
    for r in rows():
        why = conftest.host_skip(r["file"], table, "win32")
        assert (why is None) == (r["runs"] == "desktop"), r


# -- the skip at collection, in a pytest of its own ----------------------------------------------------

IMPORTS_FCNTL = "import fcntl_not_on_this_system  # noqa: F401\n\n\ndef test_x():\n    pass\n"
PASSES = "def test_y():\n    pass\n"


def mini(tmp_path: Path, platform: str) -> subprocess.CompletedProcess:
    """A repository of 3 test files with this conftest and a table: a desktop file, a posix file and a
    linux file whose import fails. A plugin sets sys.platform to `platform` while pytest collects, and
    back after: pytest's own start reads it (on "win32" it imports _winapi, which Linux lacks)."""
    root = tmp_path / "repo"
    (root / "tests").mkdir(parents=True)
    (root / "verify").mkdir()
    text = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    plugin = 'Path(__file__).resolve().parents[1] / "tools" / "ci"'
    text = text.replace(plugin, f"Path({str(ROOT / 'tools' / 'ci')!r})")
    (root / "tests" / "conftest.py").write_text(text, encoding="utf-8")
    (root / "tests" / "test_d.py").write_text(PASSES, encoding="utf-8")
    (root / "tests" / "test_p.py").write_text(IMPORTS_FCNTL, encoding="utf-8")
    (root / "tests" / "test_l.py").write_text(IMPORTS_FCNTL, encoding="utf-8")
    (root / "verify" / "desktop.csv").write_text(
        "file,runs,reason\n"
        "tests/test_d.py,desktop,the gates\n"
        "tests/test_p.py,posix,it locks with fcntl\n"
        "tests/test_l.py,linux,it reads /proc\n",
        encoding="utf-8",
    )
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    (plugins / "as_platform.py").write_text(
        "import sys\n\nimport pytest\n\nREAL = sys.platform\n\n\n"
        "@pytest.hookimpl(tryfirst=True)\ndef pytest_collection(session):\n"
        f"    sys.platform = {platform!r}\n\n\n"
        "@pytest.hookimpl(tryfirst=True)\ndef pytest_collection_modifyitems(session, config, items):\n"
        "    sys.platform = REAL\n",
        encoding="utf-8",
    )
    # A shard's own variables stay with the shard: the child is a pytest that runs alone.
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH" and not k.startswith("TESTSHARDS_")}
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "verify"), str(plugins)])
    args = ["-q", "-p", "as_platform", "-p", "testshards", "-p", "no:cacheprovider", "--rootdir", str(root)]
    args += ["--continue-on-collection-errors", "--basetemp", str(tmp_path / "bt"), "tests"]
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_on_macos_a_linux_file_is_skipped_at_collection_and_named_with_its_reason(tmp_path):
    """sys.platform is "darwin" in the child: the linux file is never imported (its import would fail),
    the posix file is imported and fails, and the not-judged line names the linux file and its row."""
    ran = mini(tmp_path, "darwin")
    out = ran.stdout + ran.stderr
    assert "tests/test_p.py" in out and "fcntl_not_on_this_system" in out, out
    assert (
        "not judged: tests/test_l.py: skipped at collection "
        "('Linux-only: it reads /proc (verify/desktop.csv)')" in out
    ), out
    assert "1 passed, 1 skipped, 1 error" in out, out


def test_on_windows_the_posix_and_linux_files_are_skipped_and_the_desktop_file_runs(tmp_path):
    ran = mini(tmp_path, "win32")
    out = ran.stdout + ran.stderr
    assert ran.returncode == 0, out
    assert "1 passed, 2 skipped" in out, out
    assert "('POSIX-only: it locks with fcntl (verify/desktop.csv)')" in out, out
    assert "('Linux-only: it reads /proc (verify/desktop.csv)')" in out, out


def test_on_linux_every_file_is_collected(tmp_path):
    ran = mini(tmp_path, "linux")
    out = ran.stdout + ran.stderr
    assert "1 passed, 2 errors" in out, out
    assert "not judged" not in out, out


# -- the stand-in engines -------------------------------------------------------------------------------

ECHO = (
    "import sys\n"
    "print('stand-in', *sys.argv[1:])\n"
    "print('err', file=sys.stderr)\n"
    "sys.exit(int(sys.argv[-1]) if sys.argv[-1].isdigit() else 0)\n"
)


FIRST_LINE = conftest.posix_only("a program's first line is POSIX; the Windows stand-in has its own test")


def first_line(prog: Path) -> str:
    """The program a stand-in's first line starts. No stand-in is a shell script."""
    text = prog.read_text(encoding="utf-8")
    assert "/bin/sh" not in text and "exec " not in text, text
    line = text.splitlines()[0]
    assert line.startswith("#!"), line
    return line[2:]


@FIRST_LINE
def test_a_stand_in_is_a_python_program_that_starts_no_shell(tmp_path):
    """The stand-in's first line names this Python, or a link to it where its own path cannot be a
    first line (a venv under macOS's "Application Support"): the kernel starts it with no shell, so it
    runs with PATH empty (no sh, no bash to find), and it passes its arguments and its exit code."""
    prog = conftest.stand_in(tmp_path / "bin" / "kicad-cli", ECHO)
    assert prog == tmp_path / "bin" / "kicad-cli"
    started = first_line(prog)
    if conftest.first_line_fits(sys.executable):
        assert started == sys.executable
    else:
        assert conftest.first_line_fits(started) and os.path.samefile(started, sys.executable), started
    argv = [str(prog), "pcb", "drc", "a b", "7"]
    ran = subprocess.run(argv, capture_output=True, text=True, env={"PATH": ""})
    assert (ran.returncode, ran.stdout, ran.stderr) == (7, "stand-in pcb drc a b 7\n", "err\n")


@FIRST_LINE
def test_a_stand_in_is_found_on_path_by_its_name(tmp_path):
    conftest.stand_in(tmp_path / "bin" / "ngspice", ECHO)
    assert shutil.which("ngspice", path=str(tmp_path / "bin")) == str(tmp_path / "bin" / "ngspice")


@pytest.mark.parametrize(
    ("path", "fits"),
    [
        ("/" + "a" * 124, True),
        ("/" + "a" * 125, False),
        ("/" + "é" * 62, True),  # 125 bytes in UTF-8
        ("/" + "é" * 63, False),  # 64 characters, 127 bytes: the kernel counts bytes
        ("/Users/x/Library/Application Support/via/venv/bin/python", False),
        ("/a\tb/python", False),
        ("", False),
    ],
)
def test_a_first_line_holds_at_most_125_bytes_and_no_space(path, fits):
    """Linux before 5.1 cuts a first line at 127 bytes ("#!" and 125 more); macOS's kernel splits it at a
    space or a tab."""
    assert conftest.first_line_fits(path) is fits


@FIRST_LINE
@pytest.mark.parametrize(
    ("folder", "beside"),
    [("Application Support", "bin"), ("it's Application Support", "bin"), ("Application Support", "a b/bin")],
)
def test_where_this_pythons_path_cannot_be_a_first_line_the_stand_in_names_a_link_to_it(
    tmp_path, monkeypatch, folder, beside
):
    """A first line holds no space (macOS's kernel splits it there) and at most 127 bytes; the venv of
    Via's macOS root is under "Application Support". There the first line names a link to this Python,
    beside the stand-in or, where that path cannot be a first line either, in a temporary folder. No
    shell runs: it starts with PATH empty and passes its arguments. The Python here is a link to this
    one through a folder with a space, and a quote in 1 case."""
    spaced = tmp_path / folder
    spaced.mkdir()
    real = Path(sys.base_prefix) / "bin" / Path(sys.executable).name
    (spaced / "python3").symlink_to(real if real.exists() else Path(sys.executable).resolve())
    monkeypatch.setattr(sys, "executable", str(spaced / "python3"))
    prog = conftest.stand_in(tmp_path / beside / "java", ECHO)
    started = first_line(prog)
    assert conftest.first_line_fits(started) and os.path.samefile(started, sys.executable), started
    ran = subprocess.run([str(prog), "-version", "3"], capture_output=True, text=True, env={"PATH": ""})
    assert (ran.returncode, ran.stdout) == (3, "stand-in -version 3\n"), ran.stderr


@FIRST_LINE
@pytest.mark.parametrize("beside", ["bin", "a b/bin"])
def test_the_link_to_this_python_is_beside_the_stand_in_where_its_path_can_be_a_first_line(
    tmp_path, monkeypatch, beside
):
    """The link goes in the stand-in's own folder; where that folder's path cannot be a first line (a
    space), in a temporary folder of the run. The bound of 125 bytes is lifted here, since this run's
    folders are long: what is held is the order."""
    spaced = tmp_path / "Application Support"
    spaced.mkdir()
    (spaced / "python3").symlink_to(Path(sys.executable).resolve())
    monkeypatch.setattr(sys, "executable", str(spaced / "python3"))
    monkeypatch.setattr(conftest, "first_line_fits", lambda p: bool(p) and not any(c.isspace() for c in p))
    prog = conftest.stand_in(tmp_path / beside / "java", ECHO)
    started = first_line(prog)
    where = tmp_path / "bin" if beside == "bin" else Path(tempfile.gettempdir())
    assert started.startswith(str(where) + os.sep), started
    assert os.path.samefile(started, sys.executable)
    ran = subprocess.run([str(prog), "1"], capture_output=True, text=True, env={"PATH": ""})
    assert (ran.returncode, ran.stdout) == (1, "stand-in 1\n"), ran.stderr


def spaced_venv(tmp_path: Path) -> Path:
    """The Python of a venv under macOS's default root (hostos.default_root(): "~/Library/Application
    Support/via"): bin/python is a link to this Python, beside this venv's pyvenv.cfg and lib, so it
    imports what this one imports."""
    venv = tmp_path / "Library" / "Application Support" / "via" / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").symlink_to(sys.executable)
    prefix = Path(sys.prefix)
    if (prefix / "pyvenv.cfg").is_file():
        (venv / "pyvenv.cfg").symlink_to(prefix / "pyvenv.cfg")
        (venv / "lib").symlink_to(prefix / "lib")
    return venv / "bin" / "python"


@FIRST_LINE
def test_this_file_passes_under_a_venv_in_macos_default_root(tmp_path):
    """The macOS list runs with the venv the installer made, under "Application Support": this file's
    other tests pass under that venv's Python, and none of their stand-ins is a shell script."""
    py = spaced_venv(tmp_path)
    me = "tests/test_desktop.py::test_this_file_passes_under_a_venv_in_macos_default_root"
    env = {k: v for k, v in os.environ.items() if not k.startswith("TESTSHARDS_")}
    args = ["-q", "-p", "no:cacheprovider", "--basetemp", str(tmp_path / "bt"), "--deselect", me]
    ran = subprocess.run(
        [str(py), "-m", "pytest", *args, "tests/test_desktop.py"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert ran.returncode == 0, ran.stdout[-4000:] + ran.stderr[-2000:]
    assert " passed" in ran.stdout and " failed" not in ran.stdout, ran.stdout[-2000:]


def test_on_windows_the_stand_in_is_a_cmd_file_that_starts_this_python(tmp_path, monkeypatch):
    """Windows runs no first line: the stand-in is `<name>.cmd`, found on PATH by PATHEXT, whose 1 line
    starts this Python on the program beside it with every argument (%*). On Windows cmd runs the file;
    elsewhere the line is read as cmd would split it (its words in double quotes) and run: the program
    answers as it does on Linux."""
    monkeypatch.setattr(sys, "platform", "win32")
    prog = conftest.stand_in(tmp_path / "bin" / "kicad-cli", ECHO)
    assert prog == tmp_path / "bin" / "kicad-cli.cmd"
    script = tmp_path / "bin" / "kicad-cli-stand-in.py"
    (line,) = prog.read_bytes().decode("utf-8").splitlines()
    assert line == f'@"{sys.executable}" "{script}" %*'
    assert prog.read_bytes().endswith(b"\r\n")
    if os.name == "nt":
        argv = [str(prog), "pcb", "export", "5"]
    else:
        argv = shlex.split(line.lstrip("@").replace("%*", "pcb export 5"))
    ran = subprocess.run(argv, capture_output=True, text=True)
    assert (ran.returncode, ran.stdout) == (5, "stand-in pcb export 5\n")


# -- no home folder ------------------------------------------------------------------------------------


def test_on_windows_no_home_takes_out_every_variable_path_home_reads(tmp_path, monkeypatch):
    """Windows' Path.home() reads USERPROFILE, then HOMEDRIVE and HOMEPATH (Python's ntpath), and has no
    pwd. The child runs with pwd taken out of sys.modules, as on Windows: the start does not import it,
    and Path.home() raises as the tests of a no-home run need."""
    monkeypatch.setattr(sys, "platform", "win32")
    env = {**os.environ, "USERPROFILE": "C:\\Users\\x", "HOMEDRIVE": "C:", "HOMEPATH": "\\Users\\x"}
    cmd, bare = conftest.no_home_command(tmp_path / "home.py", "a", env=env)
    for name in ("HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH"):
        assert name not in bare
    assert "pwd" not in cmd[2]
    script = tmp_path / "home.py"
    text = "import sys\nfrom pathlib import Path\nprint(sys.argv[1:])\nPath.home()\n"
    script.write_text(text, encoding="utf-8")
    windows = [cmd[0], "-c", "import sys\nsys.modules['pwd'] = None\n" + cmd[2], *cmd[3:]]
    ran = subprocess.run(windows, env=bare, capture_output=True, text=True, check=False)
    assert ran.stdout == "['a']\n", ran.stderr
    assert ran.stderr.strip().splitlines()[-1] == "RuntimeError: Could not determine home directory."


@conftest.posix_only("it holds the POSIX start; the Windows one has its own test")
def test_on_linux_no_home_runs_as_before(tmp_path):
    cmd, bare = conftest.no_home_command(tmp_path / "s.py", 1, env={"HOME": "/h", "A": "b"})
    assert bare == {"A": "b"}
    assert cmd == [sys.executable, "-c", conftest.NO_HOME, str(tmp_path / "s.py"), "1"]


# -- the runner on Windows (stood in for on this Linux machine) ----------------------------------------------

# A stand-in taskkill: it writes its arguments to the log, then ends the process /PID names, as
# `taskkill /T /F` ends a tree. It runs as a Python program (conftest.stand_in), never a shell.
TASKKILL = (
    "import os, signal, sys\n"
    "with open(os.environ['TASKKILL_LOG'], 'a', encoding='utf-8') as fh:\n"
    "    fh.write(' '.join(sys.argv[1:]) + '\\n')\n"
    "os.kill(int(sys.argv[sys.argv.index('/PID') + 1]), signal.SIGKILL)\n"
)


@conftest.posix_only("it stands in for Windows' taskkill; on Windows the real one runs")
def test_on_windows_the_clean_up_ends_each_running_shards_tree_with_taskkill(tmp_path, monkeypatch):
    """Windows has no process group to kill: `end_all` ends each running shard through
    hostos.kill_tree, which runs `taskkill /T /F /PID <pid>`. sys.platform is "win32" here and a
    stand-in taskkill stands first on PATH: it is called once for each of the 2 running shards, not for
    the 1 that had ended, and every shard has a return code after."""
    conftest.stand_in(tmp_path / "bin" / "taskkill", TASKKILL)
    log = tmp_path / "taskkill.log"
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("TASKKILL_LOG", str(log))
    sleeper = [sys.executable, "-c", "import time; time.sleep(60)"]
    procs = [subprocess.Popen(sleeper) for _ in range(2)]
    done = subprocess.Popen([sys.executable, "-c", "pass"])
    done.wait()
    procs.insert(1, done)
    try:
        monkeypatch.setattr(sys, "platform", "win32")
        testshards.end_all(procs)
        monkeypatch.setattr(sys, "platform", "linux")
        assert [p.returncode for p in procs] == [-signal.SIGKILL, 0, -signal.SIGKILL]
        assert log.read_text(encoding="utf-8").splitlines() == [
            f"/T /F /PID {procs[0].pid}",
            f"/T /F /PID {procs[2].pid}",
        ]
    finally:
        for p in procs:
            if p.returncode is None:
                p.kill()
                p.wait()


def test_the_clean_up_ends_each_running_shard_on_this_system():
    """On every system: 2 shards that sleep 60 s, started as the runner starts them, and 1 that has
    ended. `end_all` returns within 30 s, and each has a return code. On Windows this is the run of the
    real taskkill."""
    sleeper = [sys.executable, "-c", "import time; time.sleep(60)"]
    procs = [subprocess.Popen(sleeper, start_new_session=True) for _ in range(2)]
    done = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
    done.wait()
    procs.insert(1, done)
    try:
        ended = threading.Thread(target=testshards.end_all, args=(procs,), daemon=True)
        ended.start()
        ended.join(timeout=30)
        assert not ended.is_alive(), "end_all did not return within 30 s: a shard was not ended"
        assert procs[1].returncode == 0
        assert procs[0].returncode not in (None, 0) and procs[2].returncode not in (None, 0)
    finally:
        for p in procs:
            if p.returncode is None:
                p.kill()
                p.wait()


@conftest.posix_only("it takes SIGHUP out of a POSIX Python to stand in for Windows'")
def test_the_runner_loads_where_python_has_no_sighup_and_stops_on_windows_signals(tmp_path):
    """Windows' Python has no SIGHUP (Python's signal documentation). A child takes it out of the signal
    module and sets sys.platform to "win32" before it loads the runner: the load works, and the signals
    it stops on are hostos.stop_signals(): SIGTERM, and SIGBREAK where the Python has it."""
    probe = (
        "import signal, sys\n"
        "del signal.SIGHUP\n"
        "sys.platform = 'win32'\n"
        f"sys.path.insert(0, {str(ROOT / 'verify')!r})\n"
        "import testshards\n"
        "print(sorted(int(s) for s in testshards.stops()))\n"
    )
    ran = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=60)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == f"[{int(signal.SIGTERM)}]\n"


def test_the_runner_stops_on_term_and_hup_and_on_windows_on_term_and_break():
    names = ("SIGTERM", "SIGBREAK") if sys.platform == "win32" else ("SIGTERM", "SIGHUP")
    assert testshards.stops() == tuple(getattr(signal, n) for n in names)


# -- the runner on a named list of test files (testshards.py run --only) ------------------------------------


def only_list(root: Path, text: str) -> Path:
    path = root / "list.csv"
    path.write_text(text, encoding="utf-8")
    return path


def gate_only(root: Path, listing: Path, work: str = "work") -> subprocess.CompletedProcess:
    args = ["run", "--root", str(root), "--table", str(root / "shards.csv"), "--jobs", "2"]
    args += ["--python", sys.executable, "--work", str(root.parent / work), "--only", str(listing)]
    return subprocess.run(
        [sys.executable, str(ROOT / "verify" / "testshards.py"), *args],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def test_only_runs_the_desktop_rows_of_the_list_and_1_process_collects_the_same_files(tmp_path):
    """4 files of 2 tests; the list (verify/desktop.csv's columns) names p and q to run everywhere and r
    for POSIX only, and leaves s out. p and q run: 4 ids collected in 1 process, 4 run, green. A failing
    test in r or s would turn it red if either ran."""
    files = dict(FOUR)
    files["test_r.py"] = files["test_s.py"] = "def test_fails():\n    assert False\n"
    root = folder(tmp_path, files)
    listing = only_list(
        root,
        "file,runs,reason\ntests/test_p.py,desktop,a\ntests/test_q.py,desktop,b\ntests/test_r.py,posix,c\n",
    )
    proc = gate_only(root, listing)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "tests: 2 files in 1 shards" in proc.stdout or "tests: 2 files in 2 shards" in proc.stdout
    assert f"  only: 2 files, the desktop rows of {listing}" in proc.stdout
    assert "ids: 4 collected in 1 process, 4 run in" in proc.stdout
    assert "test_r.py" not in proc.stdout and "test_s.py" not in proc.stdout
    assert "TESTS GREEN: 4 tests" in proc.stdout


def test_only_takes_a_list_with_a_file_column_alone(tmp_path):
    root = folder(tmp_path, FOUR)
    proc = gate_only(root, only_list(root, "file\ntests/test_s.py\n"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ids: 2 collected in 1 process, 2 run in 1 shards" in proc.stdout


def test_only_with_a_file_that_is_not_there_is_refused_with_its_name(tmp_path):
    """The message names the list and the line of the row (the header is line 1)."""
    root = folder(tmp_path, FOUR)
    text = "file,runs,reason\ntests/test_p.py,desktop,a\ntests/test_gone.py,desktop,b\n"
    listing = only_list(root, text)
    proc = gate_only(root, listing)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert proc.stderr == f"{listing}:3: 'tests/test_gone.py' is not a test file under the tests folder\n"
    assert not (tmp_path / "work").exists()


def test_only_with_a_list_with_no_file_column_is_refused(tmp_path):
    root = folder(tmp_path, FOUR)
    listing = only_list(root, "name,runs\ntests/test_p.py,desktop\n")
    proc = gate_only(root, listing)
    assert (proc.returncode, proc.stderr) == (2, f"{listing}:1: no column file\n"), proc.stdout
    assert not (tmp_path / "work").exists()


def test_only_with_a_list_that_is_not_there_is_refused_with_no_traceback(tmp_path):
    root = folder(tmp_path, FOUR)
    proc = gate_only(root, root / "absent.csv")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "No such file" in proc.stderr and "absent.csv" in proc.stderr, proc.stderr
    assert "Traceback" not in proc.stderr and len(proc.stderr.splitlines()) == 1, proc.stderr
    assert not (tmp_path / "work").exists()


def test_a_padded_cell_of_the_table_names_the_file_all_the_same(tmp_path):
    """A row written with spaces around its cells (` tests/test_x.py , posix , it forks `) skips its
    file as the row without them does."""
    table = tmp_path / "desktop.csv"
    table.write_text("file,runs,reason\n tests/test_x.py , posix , it forks \n", encoding="utf-8")
    assert conftest.host_rows(table) == {"tests/test_x.py": ("posix", "it forks")}
    why = conftest.host_skip("tests/test_x.py", conftest.host_rows(table), "win32")
    assert why == "POSIX-only: it forks (verify/desktop.csv)"


def test_a_second_stop_of_either_kind_during_the_clean_up_is_ignored(monkeypatch):
    """The first stop raises Stopped and ignores every stop signal from then on: under `enginelock.py
    hold` the second may be the other kind (TERM, then HUP from the closing terminal)."""
    kept = {s: signal.getsignal(s) for s in testshards.stops()}
    try:
        for s in testshards.stops():
            signal.signal(s, signal.SIG_DFL)
        first = testshards.stops()[0]
        with pytest.raises(testshards.Stopped) as stopped:
            testshards._stop(first, None)
        assert stopped.value.signum == first
        assert {s: signal.getsignal(s) for s in testshards.stops()} == dict.fromkeys(
            testshards.stops(), signal.SIG_IGN
        )
        assert len(testshards.stops()) == 2 or sys.platform == "win32"
    finally:
        for s, handler in kept.items():
            signal.signal(s, handler)


def test_only_with_a_list_that_names_no_file_is_refused(tmp_path):
    root = folder(tmp_path, FOUR)
    proc = gate_only(root, only_list(root, "file,runs,reason\ntests/test_p.py,linux,a\n"))
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "names no file to run" in proc.stderr


# -- a shard that ends on Windows (no signal to plant there) ------------------------------------------------


def test_a_shard_that_exits_mid_run_names_its_exit_and_the_test_it_was_running(tmp_path):
    """Windows' Python has no SIGKILL, and its os.kill ends a process by TerminateProcess with the
    signal's number as the exit code, so no crash is written. The test there ends its own pytest by
    os._exit(3): the gate names the exit, the test the shard started last and the end of its output.
    test_testshards.py holds the POSIX twins, by SIGKILL and by SIGSEGV."""
    files = dict(FOUR)
    files["test_s.py"] = (
        "import os\n\n\ndef test_one():\n    pass\n\n\n"
        "def test_exit():\n    os._exit(3)\n\n\ndef test_after():\n    pass\n"
    )
    root = folder(tmp_path, files)
    shard = shard_of(root, "test_s.py")
    proc = gate(root)
    assert proc.returncode == 1, proc.stdout
    log = root.parent / "work" / f"shard-{shard}" / "pytest.log"
    header = (
        f"why: shard {shard} ended with no report from pytest (exit 3); "
        f"the test it started last and did not end: tests/test_s.py::test_exit; "
        f"the last lines of its output, {log}:"
    )
    assert header in proc.stdout.splitlines(), proc.stdout


# -- what a desktop file may hold ---------------------------------------------------------------------------

# Names Windows' Python lacks (Python's os and signal documentation), and the folder only Linux has.
POSIX_NAMES = frozenset({"SIGKILL", "SIGSEGV", "SIGHUP", "killpg", "getuid", "symlink_to"})
PROC = "/proc/"
PLATFORM_MARKS = frozenset({"posix_only", "linux_only"})
# Tests that read a POSIX name only after they stand it in where Python lacks it: the run of
# test_hostos.py with those names taken away (below) is what holds each.
STOOD_IN = {
    "tests/test_hostos.py::test_lock_dir_on_posix_is_one_folder_per_user_in_tmp": "on() stands in os.getuid",
    "tests/test_hostos.py::test_lock_dir_leaves_workcenter_lock_dir_to_the_lock": "on() stands in os.getuid",
    "tests/test_hostos.py::test_stop_signals_on_posix_are_term_and_hup": "on() stands in signal.SIGHUP",
    "tests/test_hostos.py::test_kill_tree_on_posix_kills_the_process_group": "on() stands in signal.SIGKILL",
}
# The files whose tests are of the first line itself.
FIRST_LINES = {"tests/test_desktop.py": "its tests are of conftest.stand_in's first line"}


def _called(node: ast.AST) -> str | None:
    func = node.func if isinstance(node, ast.Call) else node
    if isinstance(func, ast.Name):
        return func.id
    return func.attr if isinstance(func, ast.Attribute) else None


def scan(path: Path) -> tuple[list[str], list[str], int]:
    """A desktop file read as Python: its tests that use a POSIX name or /proc, by themselves or by a
    module-level function they call, and carry no platform mark; its strings that begin a first line
    (`#!`); and the count of its tests that carry a platform mark. A platform mark is posix_only(...),
    linux_only(...), a name given 1 of them, or a skipif that reads sys.platform."""
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    marks = set(PLATFORM_MARKS)
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if _called(node.value) in PLATFORM_MARKS:
                marks |= {t.id for t in node.targets if isinstance(t, ast.Name)}

    def posix(node: ast.AST) -> set[str]:
        found = set()
        for n in ast.walk(node):
            if isinstance(n, ast.Attribute) and n.attr in POSIX_NAMES:
                found.add(n.attr)
            elif isinstance(n, ast.Constant) and isinstance(n.value, str) and PROC in n.value:
                found.add(PROC)
        return found

    helpers = {
        n.name: posix(n)
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and not n.name.startswith("test_") and posix(n)
    }
    unmarked, marked = [], 0
    for node in tree.body:
        if not (isinstance(node, ast.FunctionDef) and node.name.startswith("test_")):
            continue
        is_marked = any(
            (isinstance(d, ast.Name) and d.id in marks)
            or (isinstance(d, ast.Call) and _called(d) in PLATFORM_MARKS)
            or (isinstance(d, ast.Call) and _called(d) == "skipif" and "sys.platform" in ast.unparse(d))
            for d in node.decorator_list
        )
        marked += is_marked
        used = posix(node) | {
            name for n in ast.walk(node) if isinstance(n, ast.Call) and (name := _called(n)) in helpers
        }
        if used and not is_marked:
            unmarked.append(f"{node.name} ({', '.join(sorted(used))})")
    lines = sorted(
        {
            n.lineno
            for n in ast.walk(tree)
            if isinstance(n, (ast.Constant, ast.JoinedStr))
            and (ast.get_source_segment(text, n) or "").lstrip("rbuf").lstrip("\"'").startswith("#!")
        }
    )
    return unmarked, [f"line {n}" for n in lines], marked


def test_no_test_of_a_desktop_file_uses_a_posix_name_without_its_mark():
    """Every test of a desktop file runs on Windows unless it says otherwise: 1 that sends SIGKILL or
    SIGSEGV, reads /proc, kills a process group, asks for the user id or makes a symbolic link carries
    posix_only(...) or linux_only(...). A test that stands the name in first is listed in STOOD_IN."""
    found = []
    for r in rows():
        if r["runs"] == "desktop":
            unmarked, _, _ = scan(ROOT / r["file"])
            found += [f"{r['file']}::{t}" for t in unmarked if f"{r['file']}::{t.split()[0]}" not in STOOD_IN]
    assert found == []


def test_the_tests_it_stands_in_for_are_tests_of_desktop_files():
    desktop = {r["file"] for r in rows() if r["runs"] == "desktop"}
    for name in STOOD_IN:
        file, test = name.split("::")
        assert file in desktop and f"def {test}(" in (ROOT / file).read_text(encoding="utf-8"), name


def test_no_desktop_file_writes_a_first_line_by_hand():
    """A stand-in engine goes through conftest.stand_in: a first line written by hand breaks on Windows
    and on a venv under "Application Support"."""
    found = {}
    for r in rows():
        if r["runs"] == "desktop" and r["file"] not in FIRST_LINES:
            _, lines, _ = scan(ROOT / r["file"])
            if lines:
                found[r["file"]] = lines
    assert found == {}


def test_a_desktop_row_whose_file_skips_a_test_somewhere_says_what_is_not_proved():
    """The row's reason is what the not-judged table of macOS and Windows reads: where a file of the
    list skips a test on a system, its reason says `not proved` there, and what."""
    missing = []
    for r in rows():
        if r["runs"] == "desktop":
            _, _, marked = scan(ROOT / r["file"])
            if marked and "not proved" not in r["reason"]:
                missing.append(f"{r['file']}: {marked} marked")
    assert missing == []


# Taken away where pytest has started, as Windows' Python lacks them: os.getuid, os.killpg, SIGHUP and
# SIGKILL. pytest itself starts with them (its temporary folder reads os.getuid unless --basetemp).
NO_POSIX_NAMES = """\
import os
import signal

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session):
    for module, name in ((os, "getuid"), (os, "killpg"), (signal, "SIGHUP"), (signal, "SIGKILL")):
        if hasattr(module, name):
            delattr(module, name)
"""


def test_the_platform_layers_tests_pass_where_python_lacks_the_posix_names(tmp_path):
    """test_hostos.py in a pytest of its own, whose Python lacks os.getuid, os.killpg, signal.SIGHUP and
    signal.SIGKILL, as Windows' does. Its 2 tests that run on Linux alone are left out: on Windows they
    skip. Every other test passes."""
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    (plugins / "no_posix_names.py").write_text(NO_POSIX_NAMES, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH" and not k.startswith("TESTSHARDS_")}
    env["PYTHONPATH"] = str(plugins)
    linux = [
        "tests/test_hostos.py::test_kill_tree_on_linux_ends_a_grandchild_the_test_started",
        "tests/test_hostos.py::test_on_linux_hostos_returns_what_the_code_returns_today",
    ]
    args = ["-q", "-p", "no_posix_names", "-p", "no:cacheprovider", "--basetemp", str(tmp_path / "bt")]
    for name in linux:
        args += ["--deselect", name]
    ran = subprocess.run(
        [sys.executable, "-m", "pytest", *args, "tests/test_hostos.py"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert ran.returncode == 0, ran.stdout[-4000:] + ran.stderr[-2000:]
    assert " failed" not in ran.stdout, ran.stdout[-2000:]


# -- the engine guard on Windows (tools/ci/guard/engine_watch.py) --------------------------------------------


@pytest.mark.parametrize(
    ("platform", "argv", "engine"),
    [
        ("win32", ["C:\\Program Files\\KiCad\\10.0\\bin\\kicad-cli.exe", "pcb", "drc"], "kicad-cli"),
        ("win32", ["C:/Spice64/bin/NGSPICE_CON.EXE", "-b"], "ngspice_con"),
        ("win32", ["ngspice.exe", "-b"], "ngspice"),
        ("win32", ["OPENEMS.EXE"], "openEMS"),
        ("win32", ["xvfb-run", "-a", "java.exe", "-jar", "fr.jar"], "java"),
        ("win32", ["kicad-cli.txt"], None),
        ("win32", ["notepad.exe"], None),
        ("linux", ["/usr/bin/kicad-cli", "pcb"], "kicad-cli"),
        ("linux", ["kicad-cli.exe"], None),
    ],
)
def test_the_engine_guard_knows_an_engine_by_its_windows_program_name(
    tmp_path, monkeypatch, platform, argv, engine
):
    """On Windows a program is `<name>.exe` (or another PATHEXT extension) in any case: the guard of the
    fast lane, and its refusal under WORKCENTER_NO_ENGINES=1, know the engine by it. ngspice's console
    program there is ngspice_con (hostos.ngspice_candidates). Linux reads names as before. A program
    under the temporary folder is a stand-in; here that folder is 1 of the test's own, since on Linux
    `C:/...` is a path under the working folder."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "temp"))
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setenv("PATHEXT", ".COM;.EXE;.BAT;.CMD")
    assert engine_watch.engine_of(argv, path="") == engine


# -- a stand-in is reached the ways the workcenter starts engines -------------------------------------------


def test_a_stand_in_on_path_is_reached_the_ways_the_workcenter_starts_engines(tmp_path):
    """test_new's stand-ins prove a command started no engine by an empty log: the control is that a
    stand-in, once started, writes its line. Through shutil.which (doctor, the gates' checks) it does on
    every system. By its bare name it does on Linux and macOS; on Windows a bare-name start looks for
    `<name>.exe` alone, never the `.cmd` stand-in, so it writes nothing (test_new's row says what that
    leaves not proved)."""
    env, log = test_new.stand_ins(tmp_path)
    found = shutil.which("kicad-cli", path=env["PATH"])
    assert found, env["PATH"]
    ran = subprocess.run([found, "version"], env=env, capture_output=True, text=True, timeout=60)
    assert ran.returncode == 97, ran.stderr
    assert log.read_text(encoding="utf-8").splitlines() == ["kicad-cli version"]
    try:
        bare = subprocess.run(["kicad-cli", "pcb"], env=env, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        bare = None
    lines = log.read_text(encoding="utf-8").splitlines()
    if sys.platform == "win32":
        assert lines == ["kicad-cli version"], lines
    else:
        assert bare is not None and bare.returncode == 97
        assert lines == ["kicad-cli version", "kicad-cli pcb"], lines
