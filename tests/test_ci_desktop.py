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
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "tools" / "ci" / "desktop_smoke.py"
FLOWS = ROOT / ".github" / "workflows"
sys.path.insert(0, str(SMOKE.parent))
import desktop_smoke  # noqa: E402

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
code, lines, seconds = answers[step()]
for line in lines:
    print(line)
sys.stdout.flush()
time.sleep(seconds)
sys.exit(code)
"""

TESTSHARDS = r"""
import json, os, sys
with open(os.environ["STANDIN_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps({"argv": ["testshards", *sys.argv[1:]], "cwd": os.getcwd()}) + "\n")
answer = json.loads(os.environ.get("STANDIN", "{}")).get("tests", [0, ["VERIFY TESTS GREEN"], 0])
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


def test_a_failed_test_run_fails_the_last_step(stage, capsys, monkeypatch):
    monkeypatch.setenv("STANDIN", json.dumps({"tests": [1, ["TESTS RED: 1 failed"], 0]}))
    code, lines = smoke(stage, capsys, "--only", "tests")
    assert code == 1
    assert verdicts(lines) == ["desktop-smoke: [1/1] tests: FAIL (exit 1, wanted 0)"]
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
