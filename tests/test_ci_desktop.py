"""The Windows and macOS legs: tools/ci/desktop_smoke.py with stand-in commands, and the 2 workflows'
desktop jobs by their parsed structure.

Nothing here runs macOS or Windows. The smoke's steps, their order, their exit codes and their lines
are held with a stand-in `workcenter` and a stand-in verify/testshards.py in a checkout of the test's
own; the jobs are held as YAML (GitHub Actions does not run on this machine). The first run of the
merged branch on GitHub is the proof the legs work; ee-agent-kit/CI.md, "Windows and macOS", says what
it confirms.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import conftest
import pytest

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "tools" / "ci" / "desktop_smoke.py"
FLOWS = ROOT / ".github" / "workflows"
sys.path.insert(0, str(SMOKE.parent))
import desktop_smoke  # noqa: E402

# The tools/hostos.py the smoke imported: a test sets its lookups there.
hostos = desktop_smoke.hostos

ORDER = ["doctor", "gates-green", "gates-drc", "gates-sim", "design-check", "next", "autoroute", "tests"]

# The stand-in `workcenter`: it writes its argv and working folder to LOG, then answers as the real
# command answers on the fixtures, unless STANDIN names another answer for its step as JSON
# {"<step>": [code, ["line", ...], seconds]}.
WORKCENTER = r"""
import json, os, sys, time
args = sys.argv[1:]
with open(os.environ["STANDIN_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({"argv": args, "cwd": os.getcwd()}) + "\n")
def step():
    if args[0] == "gates":
        where = args[-1]
        if "pass-first-design" in where:
            return "gates-green"
        return "gates-drc" if "drc" in where else "gates-sim"
    return {"doctor": "doctor", "design": "design-check", "next": "next", "autoroute": "autoroute"}[args[0]]
answers = {
    "doctor": [0, ["kicad-cli  ok  10.0.8", "status: ok"], 0],
    "gates-green": [0, ["PASS   erc        0 errors", "GREEN: divider  report build/gates.json"], 0],
    "gates-drc": [1, ["FAIL   drc        1 errors", "       - error: clearance: Clearance violation",
                      "RED: rc_divider  report build/gates.json"], 0],
    "gates-sim": [1, ["FAIL   sim        1 bound failed", "       - rc_divider: vout = 2.5 not in [3, 4]",
                      "RED: fail-sim-spec  report build/gates.json"], 0],
    "design-check": [0, ["design --check: the same files"], 0],
    "next": [1, ["NEXT       Run the ratings", "RUN        workcenter ratings ."], 0],
    "autoroute": [0, ["PASS   autoroute  0 unconnected, 0 errors"], 0],
}
answers.update(json.loads(os.environ.get("STANDIN", "{}")))
code, lines, seconds = answers[step()][:3]
for line in lines:
    print(line)
sys.stdout.flush()
if len(answers[step()]) > 3:
    # A child in a session of its own: the step's tree kill cannot reach it, and it holds the pipe.
    import subprocess
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], start_new_session=True)
    with open(os.environ["STANDIN_ORPHAN"], "w", encoding="utf-8") as f:
        f.write(str(child.pid))
time.sleep(seconds)
sys.exit(code)
"""

# What verify/testshards.py prints at its end when 3 tests passed (its `outcomes:` line, then its verdict).
TESTS_GREEN = [
    "outcomes: 3 passed, 0 failed, 0 skipped, 0 xfailed, 0 xpassed",
    "TESTS GREEN: 3 tests in 1 shards",
]

TESTSHARDS = r"""
import json, os, sys
with open(os.environ["STANDIN_LOG"], "a", encoding="utf-8") as log:
    seen = {"argv": ["testshards", *sys.argv[1:]], "cwd": os.getcwd(), "path": os.environ["PATH"]}
    log.write(json.dumps(seen) + "\n")
green = ["outcomes: 3 passed, 0 failed, 0 skipped, 0 xfailed, 0 xpassed", "TESTS GREEN: 3 tests in 1 shards"]
answer = json.loads(os.environ.get("STANDIN", "{}")).get("tests", [0, green, 0])
for line in answer[1]:
    print(line)
sys.exit(answer[0])
"""


def executable(path: Path, body: str) -> Path:
    path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def stage(tmp_path, monkeypatch):
    """A checkout with the 4 fixtures (1 file each, and what a run leaves: build/, a .kicad_prl), the
    stand-in testshards and the stand-in workcenter; the log the stand-ins write."""
    repo = tmp_path / "repo"
    for name in desktop_smoke.FIXTURES:
        board = repo / "tests" / "boards" / name
        (board / "build").mkdir(parents=True)
        (board / "board.kicad_pcb").write_text(f"({name})\n", encoding="utf-8")
        (board / "build" / "gates.json").write_text("[]\n", encoding="utf-8")
        (board / "board.kicad_prl").write_text("{}\n", encoding="utf-8")
    (repo / "verify").mkdir()
    executable(repo / "verify" / "testshards.py", TESTSHARDS)
    (repo / "verify" / "shards.csv").write_text("file,seconds,engine,alone\n", encoding="utf-8")
    (repo / "verify" / "desktop.csv").write_text("file\ntests/test_gates.py\n", encoding="utf-8")
    wc = executable(tmp_path / "workcenter", WORKCENTER)
    log = tmp_path / "standin.jsonl"
    monkeypatch.setenv("STANDIN_LOG", str(log))
    monkeypatch.delenv("STANDIN", raising=False)
    return {"repo": repo, "wc": wc, "log": log, "work": tmp_path / "work"}


def smoke(stage, capsys, *extra: str) -> tuple[int, list[str]]:
    code = desktop_smoke.main(
        ["--repo", str(stage["repo"]), "--workcenter", str(stage["wc"]), "--work", str(stage["work"]), *extra]
    )
    return code, capsys.readouterr().out.splitlines()


def verdicts(lines: list[str]) -> list[str]:
    """Each step's own line, its seconds left out."""
    return [
        line.rsplit(" in ", 1)[0]
        for line in lines
        if line.startswith("desktop-smoke: [") and ": $ " not in line
    ]


def calls(stage) -> list[dict]:
    return [json.loads(x) for x in stage["log"].read_text(encoding="utf-8").splitlines()]


def test_the_steps_are_the_8_of_the_task_in_their_order(capsys):
    """--list names each step and runs nothing: doctor, the 3 gates, design --check, next, the route,
    the tests."""
    assert desktop_smoke.main(["--list"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert [line.split()[0] for line in lines] == ORDER
    assert [s.name for s in desktop_smoke.steps(Path("r"), "wc", "py", Path("w"))] == ORDER


def test_a_green_run_runs_each_step_in_order_and_says_ok_for_each(stage, capsys):
    """Each step prints its command, its output under `  | `, then its line; the last line is the
    verdict. The gates run on copies in the work folder, never on the checkout; design --check reads
    the checkout's design file; the tests are the files verify/desktop.csv names, by testshards."""
    code, lines = smoke(stage, capsys)
    assert code == 0, lines
    ones = ("gates-drc", "gates-sim", "next")
    assert verdicts(lines) == [
        f"desktop-smoke: [{n}/8] {name}: ok (exit {1 if name in ones else 0})"
        for n, name in enumerate(ORDER, 1)
    ]
    assert lines[-1].startswith("DESKTOP SMOKE GREEN: 8 of 8 steps passed in ")
    assert "  | GREEN: divider  report build/gates.json" in lines
    repo, work = stage["repo"], stage["work"]
    argvs = [c["argv"] for c in calls(stage)]
    assert argvs[:7] == [
        ["doctor"],
        ["gates", "--strict", str(work / "boards" / "pass-first-design")],
        ["gates", str(work / "boards" / "fail-drc-clearance")],
        ["gates", str(work / "boards" / "fail-sim-spec")],
        ["design", str(repo / "tests" / "boards" / "pass-first-design" / "design.py"), "--check"],
        ["next", str(work / "boards" / "pass-first-design")],
        ["autoroute", str(work / "boards" / "route-me"), "--apply"],
    ]
    tests = argvs[7]
    assert tests[:2] == ["testshards", "run"]
    assert tests[tests.index("--only") + 1] == str(repo / "verify" / "desktop.csv")
    assert tests[tests.index("--python") + 1] == sys.executable
    assert tests[tests.index("--root") + 1] == str(repo)
    assert tests[tests.index("--work") + 1] == str(work / "tests")
    # Each step ran in the checkout.
    assert {c["cwd"] for c in calls(stage)} == {str(repo)}


def test_the_fixtures_are_copied_without_what_a_run_left_and_the_checkout_keeps_its_files(stage, capsys):
    smoke(stage, capsys, "--only", "doctor")
    for name in desktop_smoke.FIXTURES:
        copy = stage["work"] / "boards" / name
        assert sorted(p.name for p in copy.iterdir()) == ["board.kicad_pcb"]
        assert (stage["repo"] / "tests" / "boards" / name / "build" / "gates.json").is_file()


def test_a_red_gate_that_exits_2_is_a_skipped_engine_and_fails_its_step(stage, capsys, monkeypatch):
    """`gates` exits 2 when an engine is absent (SKIPPED): the RED fixture must exit 1, so the step
    fails, names both codes, and every other step still runs. The run is RED, exit 1."""
    monkeypatch.setenv("STANDIN", json.dumps({"gates-drc": [2, ["SKIPPED (DRC: engine missing): x"], 0]}))
    code, lines = smoke(stage, capsys)
    assert code == 1
    got = verdicts(lines)
    assert got[2] == (
        "desktop-smoke: [3/8] gates-drc: FAIL (exit 2, wanted 1; not: its last line starts with RED; "
        "not: it names clearance)"
    )
    assert [line.endswith(")") and ": ok (" in line for line in got] == [True, True, False, *[True] * 5]
    assert lines[-1].startswith("DESKTOP SMOKE RED: 1 of 8 steps failed: gates-drc (")
    assert len(calls(stage)) == 8


def test_a_gate_that_exits_0_and_says_red_fails_and_so_does_a_green_red_fixture(stage, capsys, monkeypatch):
    """The exit code alone is not the verdict: the last line is read too. A RED fixture that comes out
    GREEN (its engine passed what it must fail) fails on its code and on its line."""
    monkeypatch.setenv(
        "STANDIN",
        json.dumps(
            {
                "gates-green": [0, ["RED: divider"], 0],
                "gates-sim": [0, ["PASS   sim  vout held", "GREEN: fail-sim-spec"], 0],
            }
        ),
    )
    code, lines = smoke(stage, capsys)
    assert code == 1
    got = verdicts(lines)
    assert got[1] == "desktop-smoke: [2/8] gates-green: FAIL (not: its last line starts with GREEN)"
    assert got[3] == (
        "desktop-smoke: [4/8] gates-sim: FAIL (exit 0, wanted 1; not: its last line starts with RED)"
    )
    assert lines[-1].startswith("DESKTOP SMOKE RED: 2 of 8 steps failed: gates-green, gates-sim (")


def test_next_passes_on_0_and_1_with_a_next_line_and_fails_on_an_error(stage, capsys, monkeypatch):
    for answer, ok in (
        ([0, ["NEXT       Nothing: the gates are GREEN"], 0], True),
        ([1, ["NEXT       Run the ratings"], 0], True),
        ([2, ["workcenter: error: no such project"], 0], False),
        ([1, ["Traceback (most recent call last):"], 0], False),
    ):
        monkeypatch.setenv("STANDIN", json.dumps({"next": answer}))
        code, lines = smoke(stage, capsys, "--only", "next")
        assert (code == 0) is ok, (answer, lines)
        (line,) = verdicts(lines)
        assert line.startswith("desktop-smoke: [1/1] next: " + ("ok" if ok else "FAIL")), line


def test_a_step_fails_on_its_code_or_on_each_line_it_lacks(stage, capsys, monkeypatch):
    """Each check is its own: a RED fixture without its fault named, a route with no PASS line, `next`
    exiting 2 with a NEXT line, a GREEN line that is not the last."""
    for name, answer, why in (
        ("gates-sim", [1, ["FAIL   sim", "RED: fail-sim-spec"], 0], "not: it names vout"),
        ("gates-drc", [1, ["FAIL   drc", "RED: rc_divider"], 0], "not: it names clearance"),
        ("autoroute", [0, ["routed 13 segments"], 0], "not: a line starts with PASS"),
        ("next", [2, ["NEXT       Run the ratings"], 0], "exit 2, wanted 0 or 1"),
        (
            "gates-green",
            [0, ["GREEN: divider", "warning: a late line"], 0],
            "not: its last line starts with GREEN",
        ),
        ("doctor", [1, ["status: fail"], 0], "exit 1, wanted 0"),
        ("design-check", [1, ["design --check: 1 file differs"], 0], "exit 1, wanted 0"),
    ):
        monkeypatch.setenv("STANDIN", json.dumps({name: answer}))
        code, lines = smoke(stage, capsys, "--only", name)
        assert code == 1, (name, lines)
        assert verdicts(lines) == [f"desktop-smoke: [1/1] {name}: FAIL ({why})"], (name, lines)


def test_the_tests_step_fails_when_no_test_passed(stage, capsys, monkeypatch):
    """Exit 0 with no test run is not a pass: the step needs a line that names at least 1 passed test,
    as testshards' `outcomes:` line does. A run of 0 tests, or one that prints no count, fails."""
    for lines_out in (
        ["outcomes: 0 passed, 0 failed, 0 skipped, 0 xfailed, 0 xpassed", "TESTS GREEN: 0 tests in 0 shards"],
        ["TESTS GREEN"],
        ["outcomes: 10 failed"],
    ):
        monkeypatch.setenv("STANDIN", json.dumps({"tests": [0, lines_out, 0]}))
        code, lines = smoke(stage, capsys, "--only", "tests")
        assert code == 1, lines
        assert verdicts(lines) == [
            "desktop-smoke: [1/1] tests: FAIL (not: a line names at least 1 passed test)"
        ]
    for lines_out in (TESTS_GREEN, ["outcomes: 10 passed, 1 skipped"], ["1 passed in 0.3s"]):
        monkeypatch.setenv("STANDIN", json.dumps({"tests": [0, lines_out, 0]}))
        code, lines = smoke(stage, capsys, "--only", "tests")
        assert code == 0, lines


def test_each_step_has_its_bound_and_the_tests_theirs(monkeypatch):
    """A step's bound is STEP_SECONDS when it names none, read when it runs; the tests have their own."""
    plan = {s.name: s for s in desktop_smoke.steps(Path("r"), "wc", "py", Path("w"))}
    assert plan["tests"].bound == desktop_smoke.TESTS_SECONDS == 1800
    assert plan["doctor"].bound == desktop_smoke.STEP_SECONDS == 900
    monkeypatch.setattr(desktop_smoke, "STEP_SECONDS", 7)
    assert plan["doctor"].bound == 7 and plan["tests"].bound == 1800
    assert desktop_smoke.Step("x", "x", ["x"], (0,), seconds=12).bound == 12


def off_path_engines(tmp_path, monkeypatch) -> tuple[str, dict[str, Path]]:
    """kicad-cli and ngspice where only hostos's candidates name them, as install.ps1 and the macOS
    route leave them (run 46093588252): each in a folder of its own that PATH lacks, by its whole path.
    PATH is 1 empty folder; the 2 lookups are hostos's, each with the name first, as on macOS."""
    found = {}
    for name in ("kicad-cli", "ngspice"):
        found[name] = conftest.stand_in(
            tmp_path / "installs" / name / "bin" / name, "import sys; sys.exit(0)\n"
        )
    monkeypatch.setattr(hostos, "kicad_cli_candidates", lambda: ["kicad-cli", str(found["kicad-cli"])])
    monkeypatch.setattr(hostos, "ngspice_candidates", lambda: ["ngspice", str(found["ngspice"])])
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    return str(empty), found


def test_the_tests_step_finds_both_engines_where_only_hostos_names_them(tmp_path, monkeypatch):
    """Run 46093588252's gates ran kicad-cli and ngspice through the installed command, and its tests
    step skipped 57 tests for ngspice and 42 for kicad-cli on Windows, 44 for kicad-cli on macOS: their
    marks looked on PATH alone. The tests step's PATH ends with the folder of each engine Via finds off
    PATH, so a lookup by name finds the program the gates run; the other steps keep the runner's own
    environment, as a person's shell has it (M328)."""
    empty, found = off_path_engines(tmp_path, monkeypatch)
    assert shutil.which("kicad-cli") is None and shutil.which("ngspice") is None  # what the marks saw
    plan = {s.name: s for s in desktop_smoke.steps(Path("r"), "wc", "py", Path("w"))}
    env = plan["tests"].env
    assert env is not None
    assert env["PATH"].split(os.pathsep) == [
        empty,
        str(found["kicad-cli"].parent),
        str(found["ngspice"].parent),
    ]
    for name, program in found.items():
        assert shutil.which(name, path=env["PATH"]) == str(program), name
    assert plan["tests"].notes == [
        f"kicad-cli: {found['kicad-cli']}, its folder at the end of PATH",
        f"ngspice: {found['ngspice']}, its folder at the end of PATH",
    ]
    assert all(s.env is None and s.notes == [] for s in plan.values() if s.name != "tests")


def test_an_engine_on_path_leaves_path_as_it_was_and_one_via_does_not_find_is_named(tmp_path, monkeypatch):
    """Linux and the WSL leg: both engines on PATH by name, and PATH is the runner's. An engine Via finds
    nowhere adds nothing, and the step says where Via looked."""
    bin_ = tmp_path / "bin"
    conftest.stand_in(bin_ / "kicad-cli", "import sys; sys.exit(0)\n")
    monkeypatch.setattr(hostos, "kicad_cli_candidates", lambda: ["kicad-cli"])
    monkeypatch.setattr(hostos, "ngspice_candidates", lambda: ["ngspice", str(tmp_path / "no" / "ngspice")])
    monkeypatch.setenv("PATH", str(bin_))
    env, notes = desktop_smoke.tests_env(dict(os.environ))
    assert env["PATH"] == str(bin_)
    assert notes == [
        "kicad-cli: on PATH",
        f"ngspice: Via finds none where it looks (ngspice, {tmp_path / 'no' / 'ngspice'}); its tests skip",
    ]
    # A folder PATH already holds is not added again.
    conftest.stand_in(bin_ / "ngspice_con", "import sys; sys.exit(0)\n")
    monkeypatch.setattr(hostos, "ngspice_candidates", lambda: ["ngspice_con"])
    env, notes = desktop_smoke.tests_env(dict(os.environ))
    assert env["PATH"] == str(bin_), notes


def test_the_tests_step_runs_with_that_path_and_says_what_it_added(stage, tmp_path, capsys, monkeypatch):
    """The step's process gets the environment: the stand-in testshards logs its PATH."""
    empty, found = off_path_engines(tmp_path, monkeypatch)
    code, lines = smoke(stage, capsys, "--only", "tests")
    assert code == 0, lines
    folders = [str(found["kicad-cli"].parent), str(found["ngspice"].parent)]
    assert calls(stage)[-1]["path"].split(os.pathsep) == [empty, *folders]
    assert f"  + kicad-cli: {found['kicad-cli']}, its folder at the end of PATH" in lines
    assert verdicts(lines) == ["desktop-smoke: [1/1] tests: ok (exit 0)"]


def test_a_failed_test_run_fails_the_last_step(stage, capsys, monkeypatch):
    monkeypatch.setenv("STANDIN", json.dumps({"tests": [1, ["TESTS RED: 1 failed"], 0]}))
    code, lines = smoke(stage, capsys, "--only", "tests")
    assert code == 1
    assert verdicts(lines) == [
        "desktop-smoke: [1/1] tests: FAIL (exit 1, wanted 0; not: a line names at least 1 passed test)"
    ]
    assert "  | TESTS RED: 1 failed" in lines


def test_a_step_past_its_bound_is_ended_with_its_tree_and_fails(stage, capsys, monkeypatch):
    """A router that waits for a window never ends by itself: past its bound the step's tree is ended
    (tools/hostos.py kill_tree), its output so far kept, and the run goes on to the next step."""
    monkeypatch.setattr(desktop_smoke, "STEP_SECONDS", 2)
    monkeypatch.setenv("STANDIN", json.dumps({"autoroute": [0, ["routing ..."], 60]}))
    code, lines = smoke(stage, capsys, "--only", "autoroute", "doctor")
    assert code == 1
    assert verdicts(lines) == [
        "desktop-smoke: [1/2] doctor: ok (exit 0)",
        "desktop-smoke: [2/2] autoroute: FAIL (ended after its bound of 2 s)",
    ]
    assert "  | routing ..." in lines


@pytest.mark.skipif(os.name != "posix", reason="the stand-in leaves its child with start_new_session")
def test_a_child_that_escapes_the_kill_and_holds_the_pipe_does_not_hang_the_run(
    stage, capsys, monkeypatch, tmp_path
):
    """On Windows taskkill can fail, and Popen.kill() then ends only workcenter.cmd's cmd.exe: its Python
    keeps the pipe open. Here a child in a session of its own does the same. The smoke waits DRAIN_SECONDS
    for the pipe, keeps what it read, says why, and goes on."""
    orphan = tmp_path / "orphan.pid"
    monkeypatch.setenv("STANDIN_ORPHAN", str(orphan))
    monkeypatch.setattr(desktop_smoke, "STEP_SECONDS", 1)
    monkeypatch.setattr(desktop_smoke, "DRAIN_SECONDS", 1)
    monkeypatch.setenv("STANDIN", json.dumps({"autoroute": [0, ["routing ..."], 60, "orphan"]}))
    began = time.monotonic()
    try:
        code, lines = smoke(stage, capsys, "--only", "autoroute", "doctor")
    finally:
        if orphan.exists():
            os.kill(int(orphan.read_text(encoding="utf-8")), signal.SIGKILL)
    assert time.monotonic() - began < 30, lines
    assert code == 1
    assert verdicts(lines) == [
        "desktop-smoke: [1/2] doctor: ok (exit 0)",
        "desktop-smoke: [2/2] autoroute: FAIL (ended after its bound of 1 s)",
    ]
    assert "  | routing ..." in lines
    assert "  | a process it started held its output open 1 s after the kill; what was read is above" in lines


def test_the_command_is_the_installed_one_on_path_not_the_checkouts(tmp_path, monkeypatch):
    """Run 46067841222, Windows: `desktop-smoke: win32, workcenter .\\workcenter.CMD`. shutil.which on
    Windows looks in the working folder before PATH unless NoDefaultCurrentDirectoryInExePath is set
    (Microsoft's NeedCurrentDirectoryForExePath), and the smoke runs in the checkout, which holds
    workcenter.cmd: the smoke ran the checkout's file, not the one install.ps1 put on PATH. This
    stand-in `which` answers as Windows' does."""
    installed = str(tmp_path / "Via" / "bin" / "workcenter.cmd")

    def which(cmd, mode=os.F_OK | os.X_OK, path=None):
        if os.environ.get("NoDefaultCurrentDirectoryInExePath"):
            return installed
        return ".\\workcenter.CMD"

    monkeypatch.delenv("NoDefaultCurrentDirectoryInExePath", raising=False)
    monkeypatch.setattr(desktop_smoke.shutil, "which", which)
    assert desktop_smoke.on_path("workcenter") == installed
    assert "NoDefaultCurrentDirectoryInExePath" not in os.environ
    # A hit that is still not a whole path came from the working folder: it is no installed command.
    monkeypatch.setattr(desktop_smoke.shutil, "which", lambda *a, **k: ".\\workcenter.CMD")
    assert desktop_smoke.on_path("workcenter") is None


def test_misuse_exits_2(stage, capsys, monkeypatch):
    """No `workcenter` to run, or a step the smoke does not have: exit 2 and 1 line on stderr."""
    monkeypatch.setenv("PATH", str(stage["work"]))
    assert desktop_smoke.main(["--repo", str(stage["repo"]), "--work", str(stage["work"])]) == 2
    err = capsys.readouterr().err
    assert err == "desktop-smoke: no `workcenter` on PATH: run the installer first, or give --workcenter\n"
    assert desktop_smoke.main(["--workcenter", str(stage["wc"]), "--only", "doctor", "lint"]) == 2
    assert "desktop-smoke: no step lint; the steps: doctor, " in capsys.readouterr().err


def test_the_script_runs_as_a_program_with_its_exit_code(stage):
    """The workflow runs it as a file with the venv's Python: its own exit code and its last line."""
    env = {**os.environ, "STANDIN": json.dumps({"doctor": [1, ["status: fail"], 0]})}
    ran = subprocess.run(
        [
            sys.executable,
            str(SMOKE),
            "--repo",
            str(stage["repo"]),
            "--workcenter",
            str(stage["wc"]),
            "--work",
            str(stage["work"]),
            "--only",
            "doctor",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert ran.returncode == 1, ran.stderr
    assert ran.stdout.splitlines()[-1].startswith("DESKTOP SMOKE RED: 1 of 1 steps failed: doctor (")


# ---------------------------------------------------------------- the workflows' desktop jobs


def flow(name: str) -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load((FLOWS / name).read_text(encoding="utf-8"))


def runs(job: dict) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


def test_the_desktop_job_is_a_matrix_of_macos_and_windows_asked_by_the_scope():
    job = flow("ci.yml")["jobs"]["desktop"]
    assert job["needs"] == "scope" and job["if"] == "needs.scope.outputs.desktop == 'yes'"
    assert job["strategy"] == {"fail-fast": False, "matrix": {"os": ["macos-latest", "windows-latest"]}}
    assert job["runs-on"] == "${{ matrix.os }}" and job["name"] == "desktop ${{ matrix.os }}"
    assert job["timeout-minutes"] == 60
    assert "continue-on-error" not in job


def test_each_leg_installs_with_the_installer_a_person_runs_then_runs_the_smoke():
    steps = {s.get("id"): s for s in flow("ci.yml")["jobs"]["desktop"]["steps"] if s.get("id")}
    mac, win = steps["install-macos"], steps["install-windows"]
    assert mac["if"] == "runner.os == 'macOS'" and "./install-macos.sh --yes" in mac["run"].splitlines()
    assert win["if"] == "runner.os == 'Windows'"
    assert "powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1 -Yes" in win["run"].splitlines()
    for os_name, smoke_step in (("macOS", steps["smoke-macos"]), ("Windows", steps["smoke-windows"])):
        assert smoke_step["if"] == f"runner.os == '{os_name}'"
        assert "tools/ci/desktop_smoke.py --work" in smoke_step["run"]
    # The smoke runs with the venv's Python the installer made, never the runner's own.
    assert "Library/Application Support/via/venv/bin/python" in steps["smoke-macos"]["run"]
    assert "Via\\venv\\Scripts\\python.exe" in steps["smoke-windows"]["run"]
    names = [s.get("uses", s.get("id")) for s in flow("ci.yml")["jobs"]["desktop"]["steps"]]
    assert names.index("install-macos") < names.index("smoke-macos")
    assert names.index("install-windows") < names.index("smoke-windows")


def test_the_downloads_are_kept_by_the_hash_of_the_pins_and_saved_only_off_pull_requests():
    steps = flow("ci.yml")["jobs"]["desktop"]["steps"]
    (restore,) = [s for s in steps if s.get("uses") == "actions/cache/restore@v4"]
    (save,) = [s for s in steps if s.get("uses") == "actions/cache/save@v4"]
    key = (
        "via-desktop-downloads-v1-${{ runner.os }}-${{ runner.arch }}-"
        "${{ hashFiles('toolchain/desktop.json') }}"
    )
    assert restore["with"]["key"] == key and save["with"]["key"] == key
    assert restore["with"]["path"] == save["with"]["path"]
    assert "~/Library/Application Support/via/downloads" in save["with"]["path"]
    assert "~\\AppData\\Local\\Via\\downloads" in save["with"]["path"]
    assert restore["continue-on-error"] is True and save["continue-on-error"] is True
    assert "pull_request" not in save["if"] and "github.event_name == 'push'" in save["if"]
    assert steps.index(restore) < steps.index(save)


def test_the_wsl_leg_is_experimental_and_reported():
    job = flow("ci.yml")["jobs"]["desktop-wsl"]
    assert job["runs-on"] == "windows-latest" and job["continue-on-error"] is True
    assert job["if"] == "needs.scope.outputs.desktop == 'yes'"
    text = runs(job)
    assert "wsl --install -d Ubuntu-24.04 --no-launch" in text
    assert "./install.sh" in text and "tools/ci/desktop_smoke.py" in text
    # install.sh with CI's 3 bounds, as the full job gives it.
    assert "APT_UPDATE_TIMEOUT=120 APT_DOWNLOAD_TIMEOUT=570 APT_OTHER_TIMEOUT=300" in text


def test_the_wsl_leg_reports_each_steps_outcome_itself(tmp_path):
    """A job marked continue-on-error may hand a reader `success` for a failed run (users' reports; the
    needs context's documentation is silent). So no job reads needs.desktop-wsl: each WSL step carries
    its own continue-on-error and an id, a later step runs only on an earlier success, and the last step
    runs always and prints each outcome, into the log and the job's summary. It exits 1 unless all 3
    succeeded, so the job's own mark is red."""
    for name in ("ci.yml", "nightly.yml"):
        text = (FLOWS / name).read_text(encoding="utf-8")
        assert "needs.desktop-wsl" not in text, name
    job = flow("ci.yml")["jobs"]["desktop-wsl"]
    named = {s["id"]: s for s in job["steps"] if "id" in s}
    assert [s.get("id") for s in job["steps"]] == [None, "wsl", "install", "smoke", "report"]
    for sid in ("wsl", "install", "smoke"):
        assert named[sid]["continue-on-error"] is True, sid
    assert named["install"]["if"] == "steps.wsl.outcome == 'success'"
    assert named["smoke"]["if"] == "steps.install.outcome == 'success'"
    report = named["report"]
    assert report["if"] == "always()" and report["shell"] == "bash"
    assert report["env"] == {
        "WSL": "${{ steps.wsl.outcome }}",
        "INSTALL": "${{ steps.install.outcome }}",
        "SMOKE": "${{ steps.smoke.outcome }}",
    }
    script = tmp_path / "report.sh"
    script.write_text(report["run"], encoding="utf-8")
    for wsl, install, smoke_, code in (
        ("success", "success", "success", 0),
        ("failure", "skipped", "skipped", 1),
        ("success", "failure", "skipped", 1),
        ("success", "success", "failure", 1),
        ("", "", "", 1),
    ):
        summary = tmp_path / "summary.md"
        summary.write_text("", encoding="utf-8")
        env = {
            **os.environ,
            "WSL": wsl,
            "INSTALL": install,
            "SMOKE": smoke_,
            "GITHUB_STEP_SUMMARY": str(summary),
        }
        ran = subprocess.run(["bash", "-e", str(script)], env=env, capture_output=True, text=True)
        assert ran.returncode == code, (wsl, install, smoke_, ran.stdout, ran.stderr)
        line = (
            f"wsl (experimental, not required): wsl --install: {wsl or 'none'}; install.sh: "
            f"{install or 'none'}; smoke: {smoke_ or 'none'}"
        )
        assert ran.stdout.splitlines() == [line], ran.stdout
        assert summary.read_text(encoding="utf-8") == line + "\n"


def test_no_desktop_job_holds_a_write_permission():
    """The legs run Homebrew, winget, pip, downloads and install.sh: their token reads the repository
    and writes nothing. A job's `permissions` replaces the workflow's; with neither, GitHub gives its
    default, so one of them must be set. In nightly.yml only `verify` writes issues (its last step)."""
    for name in ("ci.yml", "nightly.yml"):
        data = flow(name)
        for job_name in ("desktop", "desktop-wsl"):
            given = data["jobs"][job_name].get("permissions", data.get("permissions"))
            assert given is not None, (name, job_name)
            assert isinstance(given, dict), (name, job_name, given)
            assert "write" not in given.values(), (name, job_name, given)
    night = flow("nightly.yml")
    assert night["permissions"] == {"contents": "read"}
    assert night["jobs"]["verify"]["permissions"] == {"contents": "read", "issues": "write"}


def test_the_nightly_runs_the_same_desktop_steps_and_its_issue_reads_them():
    """nightly.yml's 2 jobs are ci.yml's, step for step, without the scope; the Linux gate waits for
    the legs, and its ci-failure step counts a leg that did not pass as a failed night."""
    ci, night = flow("ci.yml")["jobs"], flow("nightly.yml")["jobs"]
    for name in ("desktop", "desktop-wsl"):
        assert night[name]["steps"] == ci[name]["steps"], name
        same = {k: v for k, v in ci[name].items() if k not in ("needs", "if")}
        assert night[name] == same, name
    verify = night["verify"]
    assert verify["needs"] == "desktop" and verify["if"] == "${{ !cancelled() }}"
    issue = verify["steps"][-1]
    assert issue["env"]["DESKTOP"] == "${{ needs.desktop.result }}"
    script = issue["with"]["script"]
    assert "const outcome = env.DESKTOP === 'success' ? env.JOB_STATUS : 'failure';" in script
    assert "'--outcome', outcome" in script and "`desktop=${env.DESKTOP}`" in script


def test_the_scope_step_asks_the_desktop_legs_on_a_push_to_main(tmp_path):
    """The scope step as the runner runs it, on a change of prose: a pull request writes desktop=no,
    a push desktop=yes."""
    (step,) = [s for s in flow("ci.yml")["jobs"]["scope"]["steps"] if "scope.py" in s.get("run", "")]
    call = "python3 tools/ci/scope.py"
    script = tmp_path / "scope.sh"
    script.write_text(step["run"].replace(call, f"{sys.executable} {ROOT / 'tools' / 'ci' / 'scope.py'}"))
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> str:
        ident = ["-c", "user.name=Owner", "-c", "user.email=owner@example.org", "-c", "commit.gpgsign=false"]
        ran = subprocess.run(["git", "-C", str(repo), *ident, *args], capture_output=True, text=True)
        assert ran.returncode == 0, ran.stderr
        return ran.stdout.strip()

    git("init", "-q")
    (repo / "notes.md").write_text("# Notes\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    before = git("rev-parse", "HEAD")
    (repo / "notes.md").write_text("# Notes, renamed\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "prose")
    answers = {}
    for event in ("pull_request", "push"):
        out = tmp_path / f"out-{event}"
        env = {**os.environ, "EVENT": event, "BEFORE": before, "GITHUB_OUTPUT": str(out)}
        ran = subprocess.run(["bash", "-e", str(script)], cwd=repo, env=env, capture_output=True, text=True)
        assert ran.returncode == 0, ran.stderr
        answers[event] = out.read_text(encoding="utf-8")
    assert answers == {"pull_request": "scope=fast\ndesktop=no\n", "push": "scope=fast\ndesktop=yes\n"}
