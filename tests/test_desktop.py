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

import csv
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path

import conftest
import pytest
from test_testshards import FOUR, folder

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


@FIRST_LINE
def test_a_stand_in_is_a_python_program_that_starts_no_shell(tmp_path):
    """The stand-in's first line names this Python: the kernel starts it with no shell, so it runs with
    PATH empty (no sh, no bash to find), and it passes its arguments and its exit code."""
    prog = conftest.stand_in(tmp_path / "bin" / "kicad-cli", ECHO)
    assert prog == tmp_path / "bin" / "kicad-cli"
    assert prog.read_text(encoding="utf-8").splitlines()[0] == f"#!{sys.executable}"
    argv = [str(prog), "pcb", "drc", "a b", "7"]
    ran = subprocess.run(argv, capture_output=True, text=True, env={"PATH": ""})
    assert (ran.returncode, ran.stdout, ran.stderr) == (7, "stand-in pcb drc a b 7\n", "err\n")


@FIRST_LINE
def test_a_stand_in_is_found_on_path_by_its_name(tmp_path):
    conftest.stand_in(tmp_path / "bin" / "ngspice", ECHO)
    assert shutil.which("ngspice", path=str(tmp_path / "bin")) == str(tmp_path / "bin" / "ngspice")


@FIRST_LINE
def test_where_this_pythons_path_cannot_be_a_first_line_the_stand_in_starts_it_by_sh(tmp_path, monkeypatch):
    """A first line holds no space (macOS's kernel splits it there) and at most 127 bytes; the venv of
    Via's macOS root is under "Application Support". There the stand-in is `#!/bin/sh` and 1 exec line,
    and the program beside it. The Python here is a link to this one through a folder with a space."""
    spaced = tmp_path / "Application Support"
    spaced.mkdir()
    real = Path(sys.base_prefix) / "bin" / Path(sys.executable).name
    (spaced / "python3").symlink_to(real if real.exists() else Path(sys.executable).resolve())
    monkeypatch.setattr(sys, "executable", str(spaced / "python3"))
    prog = conftest.stand_in(tmp_path / "bin" / "java", ECHO)
    assert prog.read_text(encoding="utf-8").splitlines()[0] == "#!/bin/sh"
    ran = subprocess.run([str(prog), "-version", "3"], capture_output=True, text=True, env={"PATH": ""})
    assert (ran.returncode, ran.stdout) == (3, "stand-in -version 3\n"), ran.stderr


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
    root = folder(tmp_path, FOUR)
    proc = gate_only(root, only_list(root, "file,runs,reason\ntests/test_gone.py,desktop,a\n"))
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "tests/test_gone.py" in proc.stderr and "not a test file under" in proc.stderr
    assert not (tmp_path / "work").exists()


def test_only_with_a_list_that_names_no_file_is_refused(tmp_path):
    root = folder(tmp_path, FOUR)
    proc = gate_only(root, only_list(root, "file,runs,reason\ntests/test_p.py,linux,a\n"))
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "names no file to run" in proc.stderr
