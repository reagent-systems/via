"""The scope of a change: `fast` when it touches only what no engine reads, `full` for anything else.

`tools/ci/scope.py` answers from the diff between 2 commits, or from a list of paths. A path is judged
by its folder and kind; a document is judged by its shown runs too, read with the reader that
`tests/test_docs.py` uses to run them. The workflow and the Makefile both call the script, and the
workflow is held here by its parsed structure: GitHub Actions does not run on this machine.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCOPE = ROOT / "tools" / "ci" / "scope.py"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
UNKNOWN = "no rule names this path, so it needs the full gate"
SAME = "a document; its shown runs are as they were"
DESKTOP = "install or platform code, so the Windows and macOS legs run"
# The paths of the desktop scope, named here a second time on purpose: a path dropped from scope.py, or
# one added there, fails this test until the list below and ee-agent-kit/CI.md say the same.
DESKTOP_FILES = (
    ".gitattributes",
    ".github/workflows/ci.yml",
    "install-macos.sh",
    "install.ps1",
    "install.sh",
    "pyproject.toml",
    "requirements-kicad.txt",
    "requirements.txt",
    "tests/conftest.py",
    "toolchain/desktop.json",
    "tools/ci/desktop_smoke.py",
    "tools/enginelock.py",
    "tools/hostos.py",
    "tools/kicadchild.py",
    "tools/routers.py",
    "verify/desktop.csv",
    "verify/testshards.py",
    "workcenter.cmd",
)
DESKTOP_FOLDERS = (
    "tests/boards/fail-drc-clearance/",
    "tests/boards/fail-sim-spec/",
    "tests/boards/pass-first-design/",
    "tests/boards/route-me/",
)

# A README as the root's is written: prose, a shown run of the gates with its printed lines, prose after
# it, and a quick start whose commands the document tests run.
README = """# Board tools

The gates judge a board in 4 steps.

```
$ workcenter gates tests/boards/pass-rc-divider
PASS   erc        0 errors, 0 warnings  [0.41s]
PASS   drc        0 errors, 0 warnings  [0.75s]
GREEN: rc_divider  report tests/boards/pass-rc-divider/build/gates.json
```

Each line names its gate.

## Quick start

```sh
workcenter doctor     # each engine's status
workcenter gates tests/boards/pass-first-design     # GREEN
```

## Commands

The commands.
"""

PAGE = """<html><body>
<p>The gates run in order.</p>
<pre data-run="gates"><span class="prompt">$ </span><span>workcenter gates tests/boards/pass-rc-divider</span>
PASS   erc        0 errors, 0 warnings
</pre>
<p>Read the report.</p>
</body></html>
"""


def git(repo: Path, *args: str) -> str:
    identity = ["-c", "user.name=Owner", "-c", "user.email=owner@example.org", "-c", "commit.gpgsign=false"]
    ran = subprocess.run(["git", "-C", str(repo), *identity, *args], capture_output=True, text=True)
    assert ran.returncode == 0, ran.stderr
    return ran.stdout.strip()


def commit(repo: Path, files: dict[str, str | None], message: str) -> str:
    """Write (or, for None, delete) each file and commit; the commit's hash."""
    for rel, text in files.items():
        path = repo / rel
        if text is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    found = tmp_path / "repo"
    found.mkdir()
    git(found, "init", "-q")
    commit(
        found,
        {
            "README.md": README,
            "site/index.html": PAGE,
            "ee-agent-kit/ROADMAP.md": "# Roadmap\n\n### 1. An item\n",
            "tools/workcenter": "print('cli')\n",
            "LICENSE": "MIT\n",
        },
        "base",
    )
    return found


def scope(*args: object, cwd: Path | None = None, env: dict[str, str] | None = None) -> tuple[int, list[str]]:
    proc = subprocess.run(
        [sys.executable, str(SCOPE), *map(str, args)],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, **(env or {})},
    )
    return proc.returncode, (proc.stdout + proc.stderr).splitlines()


def test_a_diff_that_edits_a_quoted_run_in_a_readme_is_full(repo):
    """1 printed line of the shown run changes: 0.41s stays, `0 warnings` of erc becomes `1 warnings`.
    The document test runs that command with the engines, so the change is full."""
    base = git(repo, "rev-parse", "HEAD")
    head = commit(
        repo,
        {
            "README.md": README.replace(
                "PASS   erc        0 errors, 0 warnings", "PASS   erc        0 errors, 1 warnings"
            )
        },
        "edit the run",
    )
    code, lines = scope("--repo", repo, "--base", base, "--head", head)
    assert code == 0, lines
    assert lines == [
        "full  README.md: a shown run changed: workcenter gates tests/boards/pass-rc-divider",
        "full",
    ]


def test_a_diff_that_edits_prose_beside_a_quoted_run_is_fast(repo):
    """The line after the block changes, and the line before it; the run's 4 lines are as they were."""
    base = git(repo, "rev-parse", "HEAD")
    text = README.replace("Each line names its gate.", "Each printed line names 1 gate.")
    text = text.replace("The gates judge a board in 4 steps.", "The gates judge a board.")
    head = commit(repo, {"README.md": text}, "edit the prose")
    code, lines = scope("--repo", repo, "--base", base, "--head", head)
    assert code == 0, lines
    assert lines == [f"fast  README.md: {SAME}", "fast"]


def test_a_command_of_the_quick_start_that_changes_is_full(repo):
    """The quick start's commands are run as written by a document test that needs the engines."""
    base = git(repo, "rev-parse", "HEAD")
    head = commit(repo, {"README.md": README.replace("pass-first-design", "pass-lc-filter")}, "quick start")
    _, lines = scope("--repo", repo, "--base", base, "--head", head)
    assert lines == ["full  README.md: the quick start changed: its commands run with the engines", "full"]


def test_a_shown_run_on_a_page_of_the_site_is_read_as_the_page_shows_it(repo):
    """A page gives its run inside `<pre data-run>`, between tags: the tags are left out as test_docs
    leaves them out. The printed line under the command changes: full. The paragraph after: fast."""
    base = git(repo, "rev-parse", "HEAD")
    prose = commit(repo, {"site/index.html": PAGE.replace("Read the report.", "Read its report.")}, "prose")
    _, lines = scope("--repo", repo, "--base", base, "--head", prose)
    assert lines == ["fast  site/index.html: the site; its shown runs are as they were", "fast"]
    run = commit(
        repo, {"site/index.html": PAGE.replace("0 errors, 0 warnings", "0 errors, 2 warnings")}, "run"
    )
    _, lines = scope("--repo", repo, "--base", prose, "--head", run)
    assert lines == [
        "full  site/index.html: a shown run changed: workcenter gates tests/boards/pass-rc-divider",
        "full",
    ]


def test_one_path_an_engine_reads_makes_the_whole_change_full(repo):
    """3 paths: 2 documents (fast) and the CLI (full). The answer is the widest of the 3."""
    base = git(repo, "rev-parse", "HEAD")
    head = commit(
        repo,
        {
            "ee-agent-kit/ROADMAP.md": "# Roadmap\n\n### 1. An item, renamed\n",
            "site/site.css": "body { color: black; }\n",
            "tools/workcenter": "print('cli 2')\n",
        },
        "three",
    )
    _, lines = scope("--repo", repo, "--base", base, "--head", head)
    assert lines == [
        f"fast  ee-agent-kit/ROADMAP.md: {SAME}",
        "fast  site/site.css: the site",
        f"full  tools/workcenter: {UNKNOWN}",
        "full",
    ]


def test_a_list_of_paths_is_judged_by_folder_and_kind_alone():
    """A list carries no text, so a document that shows a run is full: the list cannot show whether the
    run changed. Each other path is judged by its rule. The paths are read from this checkout."""
    code, lines = scope(
        "--repo",
        ROOT,
        "--paths",
        "ee-agent-kit/STATUS.md",
        "site/build.sh",
        "site/media/README.md",
        "README.md",
        "tests/boards/README.md",
        ".claude/skills/ratings/SKILL.md",
        "examples/rosetta/README.md",
        "templates/project/gates.md",
        "LICENSE",
        ".github/workflows/ci.yml",
    )
    assert code == 0, lines
    # The lines are in the order of (answer, path): fast before full, and "." and capitals first.
    assert lines == [
        "fast  ee-agent-kit/STATUS.md: a document",
        "fast  site/build.sh: the site",
        "fast  site/media/README.md: the site",
        "full  .claude/skills/ratings/SKILL.md: a command reads the files under .claude/",
        f"full  .github/workflows/ci.yml: {UNKNOWN}",
        f"full  LICENSE: {UNKNOWN}",
        "full  README.md: a list of paths cannot show whether its shown runs changed",
        "full  examples/rosetta/README.md: a command reads the files under examples/",
        "full  templates/project/gates.md: a command reads the files under templates/",
        "full  tests/boards/README.md: a command reads the files under tests/",
        f"desktop  .github/workflows/ci.yml: {DESKTOP}",
        "full",
    ]


def test_without_a_base_or_with_a_base_git_cannot_read_the_change_is_full(repo, tmp_path):
    """The nightly run and a run by hand have no base. A base the shallow clone does not hold cannot
    be read. Neither is judged as fast."""
    _, lines = scope("--repo", repo, "--base", "")
    assert lines == [
        "full  (no base): no base to compare with",
        "desktop  (no base): no base to compare with",
        "full",
    ]
    code, lines = scope("--repo", repo, "--base", "0" * 40, "--head", "HEAD")
    assert code == 0
    assert lines[0].startswith(f"full  (diff): git cannot read the change from {'0' * 40}: ")
    assert lines[1].startswith(f"desktop  (diff): git cannot read the change from {'0' * 40}: ")
    assert lines[-1] == "full" and len(lines) == 3


def test_without_a_head_the_working_tree_is_the_change_with_its_new_files(repo):
    """A developer's tree before a commit: an edited file and a file git does not track yet."""
    base = git(repo, "rev-parse", "HEAD")
    (repo / "ee-agent-kit" / "ROADMAP.md").write_text(
        "# Roadmap\n\n### 1. An item, edited\n", encoding="utf-8"
    )
    (repo / "notes.md").write_text("# Notes\n", encoding="utf-8")
    _, lines = scope("--repo", repo, "--base", base)
    assert lines == [
        f"fast  ee-agent-kit/ROADMAP.md: {SAME}",
        f"fast  notes.md: {SAME}",
        "fast",
    ]
    (repo / "tools" / "new.py").write_text("x = 1\n", encoding="utf-8")
    _, lines = scope("--repo", repo, "--base", base)
    assert lines[-2:] == [f"full  tools/new.py: {UNKNOWN}", "full"]


def test_a_rename_is_judged_at_both_of_its_paths(repo):
    """A file moved out of tools/ into site/ changed what tools/ holds: the old path is full."""
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "mv", "tools/workcenter", "site/workcenter")
    head = commit(repo, {}, "move")
    _, lines = scope("--repo", repo, "--base", base, "--head", head)
    assert lines == [
        "fast  site/workcenter: the site",
        f"full  tools/workcenter: {UNKNOWN}",
        "full",
    ]


def test_a_path_whose_name_is_not_utf_8_is_judged_and_shown_with_its_byte_escaped(repo):
    """A commit adds docs/caf<0xE9>.md, a name in Latin-1. git gives the bytes as they are; the script
    judges the path by its rule (a document, fast) and shows the byte that is not UTF-8 as `\\xe9`."""
    base = git(repo, "rev-parse", "HEAD")
    name = os.fsdecode(b"caf\xe9.md")
    (repo / "docs").mkdir()
    (repo / "docs" / name).write_text("# Notes\n", encoding="utf-8")
    head = commit(repo, {}, "a Latin-1 name")
    code, lines = scope("--repo", repo, "--base", base, "--head", head)
    assert code == 0, lines
    assert lines == [f"fast  docs/caf\\xe9.md: {SAME}", "fast"]


def test_a_listed_document_that_is_absent_is_full(repo):
    """A list carries no text, and a document that is not in the working tree cannot show that it held
    no run: README.md held 1 run before it was deleted. A site page that is absent is the same."""
    (repo / "README.md").unlink()
    (repo / "site" / "index.html").unlink()
    absent = "absent from the working tree, so a list of paths cannot show whether it showed a run"
    _, lines = scope("--repo", repo, "--paths", "README.md", "docs/gone.md", "site/index.html")
    assert lines == [
        f"full  README.md: {absent}",
        f"full  docs/gone.md: {absent}",
        f"full  site/index.html: {absent}",
        "full",
    ]


def test_no_change_is_fast_and_the_answer_goes_to_the_github_output(repo, tmp_path):
    base = git(repo, "rev-parse", "HEAD")
    out = tmp_path / "github_output"
    _, lines = scope(
        "--repo", repo, "--base", base, "--head", base, "--github-output", env={"GITHUB_OUTPUT": str(out)}
    )
    assert lines == ["fast  (no path): the 2 commits hold the same files", "fast"]
    assert out.read_text(encoding="utf-8") == "scope=fast\ndesktop=no\n"
    code, lines = scope("--repo", repo, "--paths", "README.md", "--github-output", env={"GITHUB_OUTPUT": ""})
    assert code == 2 and lines[-1] == "scope.py: --github-output needs $GITHUB_OUTPUT, the file GitHub reads"


# ---------------------------------------------------------------- the desktop scope


def test_the_desktop_scope_names_its_paths_and_no_other():
    """scope.py's list is the list here, file by file and folder by folder."""
    sys.path.insert(0, str(SCOPE.parent))
    try:
        import scope as module
    finally:
        sys.path.remove(str(SCOPE.parent))
    assert module.DESKTOP_FILES == DESKTOP_FILES
    assert module.DESKTOP_FOLDERS == DESKTOP_FOLDERS


def test_each_path_of_install_or_platform_code_asks_the_desktop_legs(tmp_path):
    """Each named file, and a file inside each named fixture, prints its desktop line and writes
    desktop=yes; the fast or full answer is the one it had before."""
    for path in (*DESKTOP_FILES, *(f"{folder}design.py" for folder in DESKTOP_FOLDERS)):
        out = tmp_path / "out"
        out.unlink(missing_ok=True)
        code, lines = scope(
            "--repo", ROOT, "--paths", path, "--github-output", env={"GITHUB_OUTPUT": str(out)}
        )
        assert code == 0, lines
        assert lines[-2] == f"desktop  {path}: {DESKTOP}", lines
        assert lines[-1] == "full" and lines[0].startswith(f"full  {path}: "), lines
        assert out.read_text(encoding="utf-8") == "scope=full\ndesktop=yes\n", path


def test_paths_beside_the_desktop_scope_do_not_ask_it(tmp_path):
    """Code that every full change touches (the CLI, the generator), another fixture, the nightly
    workflow, a document, the site: full or fast as before, and desktop=no."""
    others = (
        "tools/workcenter",
        "tools/kicadgen.py",
        "tools/ci/scope.py",
        "tests/test_gates.py",
        "tests/boards/pass-rc-divider/rc_divider.kicad_pcb",
        "tests/boards/route-me-too/x.kicad_pcb",
        ".github/workflows/nightly.yml",
        "install.sh.orig",
        "toolchain/other.json",
        "ee-agent-kit/CI.md",
        "site/index.html",
    )
    out = tmp_path / "out"
    code, lines = scope(
        "--repo", ROOT, "--paths", *others, "--github-output", env={"GITHUB_OUTPUT": str(out)}
    )
    assert code == 0, lines
    assert not [line for line in lines if line.startswith("desktop")], lines
    assert out.read_text(encoding="utf-8") == "scope=full\ndesktop=no\n"


def test_a_diff_that_touches_an_installer_asks_the_desktop_legs(repo, tmp_path):
    """From git, as the scope job reads a pull request: 1 desktop path among others."""
    base = git(repo, "rev-parse", "HEAD")
    head = commit(
        repo, {"install.ps1": "Write-Host via\n", "ee-agent-kit/ROADMAP.md": "# Roadmap\n"}, "installer"
    )
    out = tmp_path / "out"
    _, lines = scope(
        "--repo", repo, "--base", base, "--head", head, "--github-output", env={"GITHUB_OUTPUT": str(out)}
    )
    assert lines == [
        f"fast  ee-agent-kit/ROADMAP.md: {SAME}",
        f"full  install.ps1: {UNKNOWN}",
        f"desktop  install.ps1: {DESKTOP}",
        "full",
    ]
    assert out.read_text(encoding="utf-8") == "scope=full\ndesktop=yes\n"


def test_a_run_that_asks_the_desktop_legs_gets_them_whatever_its_paths(repo, tmp_path):
    """A push to main runs the legs on every change (the owner's cadence): the scope job passes
    --desktop, and a change of prose alone still writes desktop=yes."""
    base = git(repo, "rev-parse", "HEAD")
    head = commit(repo, {"ee-agent-kit/ROADMAP.md": "# Roadmap\n\n### 1. Renamed\n"}, "prose")
    out = tmp_path / "out"
    _, lines = scope(
        "--repo",
        repo,
        "--base",
        base,
        "--head",
        head,
        "--desktop",
        "--github-output",
        env={"GITHUB_OUTPUT": str(out)},
    )
    assert lines == [
        f"fast  ee-agent-kit/ROADMAP.md: {SAME}",
        "desktop  (asked): the run asks the Windows and macOS legs whatever its paths",
        "fast",
    ]
    assert out.read_text(encoding="utf-8") == "scope=fast\ndesktop=yes\n"


# ---------------------------------------------------------------- the workflow, by its parsed structure


def workflow() -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def run_lines(job: dict) -> str:
    return "\n".join(step.get("run", "") for step in job.get("steps", []))


def test_the_workflow_is_1_workflow_whose_first_job_alone_decides_the_scope():
    """No path filter on any trigger: every push and pull request starts the 1 workflow, and its jobs
    decide what runs. The scope job is the only job that runs the script; the others read its output."""
    flow = workflow()
    triggers = flow[True]  # PyYAML reads the key `on` as True
    assert set(triggers) == {"push", "pull_request", "workflow_dispatch"}
    assert all("paths" not in (t or {}) and "paths-ignore" not in (t or {}) for t in triggers.values())
    jobs = flow["jobs"]
    assert list(jobs) == ["scope", "fast", "full", "desktop", "desktop-wsl", "verdict"]
    assert "tools/ci/scope.py" in run_lines(jobs["scope"])
    assert [name for name, job in jobs.items() if "scope.py" in run_lines(job)] == ["scope"]
    assert jobs["scope"]["outputs"] == {
        "scope": "${{ steps.scope.outputs.scope }}",
        "desktop": "${{ steps.scope.outputs.desktop }}",
    }
    assert jobs["fast"]["needs"] == "scope" and jobs["full"]["needs"] == "scope"
    # The fast job runs on every change, beside the full one: a test that needs KiCad's files and
    # does not say so fails on the pull request that adds it, not on main's next fast push (P12).
    assert "if" not in jobs["fast"]
    assert jobs["full"]["if"] == "needs.scope.outputs.scope == 'full'"


# CI's install line: the 2 bounds, and the command install.sh runs after a download pass too slow to
# finish (tests/test_ci_apt_archive.py runs the step and reads what it hands to sudo).
INSTALL_LINE = (
    "sudo env REQUIRE_FREEROUTING=1 APT_UPDATE_TIMEOUT=120 APT_DOWNLOAD_TIMEOUT=570 APT_OTHER_TIMEOUT=300 "
    'APT_FILE_RETRIES="$retries" APT_FILE_TIMEOUT="$seconds" APT_SLOW_PASS_COMMAND="$slow" ./install.sh'
)


def test_the_fast_job_installs_no_engine_and_the_full_job_is_the_gate_of_today():
    jobs = workflow()["jobs"]
    fast, full = run_lines(jobs["fast"]), run_lines(jobs["full"])
    assert "install.sh" not in fast and "make verify-site" in fast
    assert "make verify-site" not in full
    install = INSTALL_LINE
    assert install in full.split("\n") and "make verify" in full.split("\n")


def test_the_last_job_always_runs_and_passes_only_when_the_asked_jobs_passed(tmp_path):
    """The verdict job needs all 5, runs with `if: always()`, and its 1 step is run here with each
    answer: green only when the fast job succeeded, for a full change the full job too, and when the
    scope asked the desktop legs, both of them. A skipped job is not a success, and a scope job that
    failed leaves no answer. The WSL leg is experimental: its result is printed, never required."""
    jobs = workflow()["jobs"]
    verdict = jobs["verdict"]
    assert verdict["needs"] == ["scope", "fast", "full", "desktop", "desktop-wsl"]
    assert verdict["if"] == "always()"
    (step,) = verdict["steps"]
    script = tmp_path / "verdict.sh"
    script.write_text(step["run"], encoding="utf-8")
    assert step["env"] == {
        "SCOPE": "${{ needs.scope.outputs.scope }}",
        "DESKTOP_ASKED": "${{ needs.scope.outputs.desktop }}",
        "FAST": "${{ needs.fast.result }}",
        "FULL": "${{ needs.full.result }}",
        "DESKTOP": "${{ needs.desktop.result }}",
        "WSL": "${{ needs.desktop-wsl.result }}",
    }
    cases = {
        ("fast", "no", "success", "skipped", "skipped"): 0,
        ("full", "no", "success", "success", "skipped"): 0,
        ("fast", "no", "failure", "skipped", "skipped"): 1,
        ("full", "no", "success", "failure", "skipped"): 1,
        # a red fast job makes a full change red too: the full job has KiCad, the fast one has not
        ("full", "no", "failure", "success", "skipped"): 1,
        ("full", "no", "skipped", "success", "skipped"): 1,
        ("full", "no", "cancelled", "success", "skipped"): 1,
        ("fast", "no", "skipped", "success", "skipped"): 1,
        ("full", "no", "success", "skipped", "skipped"): 1,
        ("full", "no", "success", "cancelled", "skipped"): 1,
        ("", "no", "skipped", "skipped", "skipped"): 1,
        # the desktop legs, asked: both legs green, or red
        ("full", "yes", "success", "success", "success"): 0,
        ("fast", "yes", "success", "skipped", "success"): 0,
        ("full", "yes", "success", "success", "failure"): 1,
        ("full", "yes", "success", "success", "skipped"): 1,
        ("full", "yes", "success", "success", "cancelled"): 1,
        ("full", "yes", "success", "failure", "success"): 1,
        # not asked: a desktop result does not count (a run by hand of 1 job never happens here)
        ("full", "no", "success", "success", "failure"): 0,
        # a scope job that wrote a scope and no desktop answer
        ("full", "", "success", "success", "success"): 1,
        ("full", "maybe", "success", "success", "success"): 1,
    }
    for (asked, desk, fast, full, desktop), code in cases.items():
        for wsl in ("success", "failure", "skipped"):
            env = {
                **os.environ,
                "SCOPE": asked,
                "DESKTOP_ASKED": desk,
                "FAST": fast,
                "FULL": full,
                "DESKTOP": desktop,
                "WSL": wsl,
            }
            ran = subprocess.run(["bash", "-e", str(script)], env=env, capture_output=True, text=True)
            assert ran.returncode == code, (asked, desk, fast, full, desktop, wsl, ran.stdout, ran.stderr)
            said = ran.stdout.splitlines()[0]
            assert said == (
                f"scope: {asked or 'none'}; desktop asked: {desk or 'none'}; fast: {fast}; full: {full}; "
                f"desktop: {desktop}; wsl (experimental, not required): {wsl}"
            ), said


def test_the_nightly_run_stays_the_full_gate():
    yaml = pytest.importorskip("yaml")
    nightly = yaml.safe_load((ROOT / ".github" / "workflows" / "nightly.yml").read_text(encoding="utf-8"))
    assert "schedule" in nightly[True]
    lines = run_lines(nightly["jobs"]["verify"]).split("\n")
    # The gate's log is kept for the ci-failure issue (tools/ci/nightly_issue.py); pipefail keeps its code.
    assert "make verify 2>&1 | tee build/nightly-verify.log" in lines and "set -o pipefail" in lines
    # The nightly run installs as CI's full job does, with CI's 2 bounds.
    assert INSTALL_LINE in lines


def test_the_makefile_asks_the_same_script_and_names_no_path_of_its_own():
    """`make scope` prints the answer for the working tree; `make verify-site` runs what the fast job
    runs, through verify.sh, as `make verify` does."""
    ran = subprocess.run(
        ["make", "-n", "--no-print-directory", "-C", str(ROOT), "scope", "verify-site", "verify"],
        capture_output=True,
        text=True,
    )
    assert ran.returncode == 0, ran.stderr
    lines = ran.stdout.splitlines()
    assert any("tools/ci/scope.py --base" in line for line in lines)
    assert lines[-2:] == ["verify/verify.sh site", "verify/verify.sh"]
    # The scope's folders and kinds are in scope.py alone: the 2 targets' lines name none. Other
    # targets may name a test file (`mutate-ratings` names tests/ratings_mutations.py).
    ours = "\n".join(line for line in lines if "scope.py" in line or "verify.sh" in line)
    assert "*.md" not in (ROOT / "Makefile").read_text(encoding="utf-8")
    assert [d for d in ("tests/", "examples/", "templates/", ".claude/") if d in ours] == []


def test_the_fast_gate_hides_kicads_libraries_as_the_fast_job_lacks_them(tmp_path):
    """The fast job's runner has no KiCad. `make verify-site` runs its tests with KiCad's symbol and
    footprint folders (tools/kicadgen.py reads KICAD_SYMBOL_DIR and KICAD_FOOTPRINT_DIR) set to empty
    folders of its own, so on a machine with KiCad a test that loads a library without saying so fails
    there too. The fast gate's lines are run here up to its tests, with stand-ins for the programs."""
    text = (ROOT / "verify" / "verify.sh").read_text(encoding="utf-8")
    site = text.split('if [[ "$mode" == site ]]; then', 1)[1].split("\nfi\n", 1)[0]
    (pytest_line,) = [line for line in site.splitlines() if "-m pytest" in line]
    assert 'KICAD_SYMBOL_DIR="$nokicad/symbols"' in pytest_line
    assert 'KICAD_FOOTPRINT_DIR="$nokicad/footprints"' in pytest_line
    assert "WORKCENTER_NO_ENGINES=1" in pytest_line and '-m "not engine"' in pytest_line
    # Run the block with stand-ins: each prints the 2 folders it was given and whether each is empty.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("shellcheck", "sh"):
        (bin_dir / name).write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    report = tmp_path / "report"
    py = bin_dir / "py"
    py.write_text(
        "#!/bin/bash\n"
        'for d in "$KICAD_SYMBOL_DIR" "$KICAD_FOOTPRINT_DIR"; do'
        f' [[ -d "$d" && -z "$(ls -A "$d")" ]] && echo "empty $d" >> {report}; done\n',
        encoding="utf-8",
    )
    py.chmod(0o755)
    body = "\n".join(line for line in site.splitlines() if "kit_checks" not in line and "exit 0" not in line)
    script = tmp_path / "site.sh"
    script.write_text(f"set -euo pipefail\nstep() {{ :; }}\nPY={py}\n{body}\n", encoding="utf-8")
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    ran = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, cwd=tmp_path)
    assert ran.returncode == 0, ran.stderr
    lines = report.read_text(encoding="utf-8").splitlines()
    assert [line.rsplit("/", 1)[1] for line in lines] == ["symbols", "footprints"], lines
    assert all("/usr/share/kicad" not in line for line in lines)


def test_each_gate_takes_the_engine_lock_under_its_own_name():
    """verify.sh takes the engine lock before it reads its mode (tools/enginelock.py); a waiting run
    names the holder by `--what`, so the fast gate is named `make verify-site`, not `make verify`."""
    text = (ROOT / "verify" / "verify.sh").read_text(encoding="utf-8")
    line = next(x for x in text.splitlines() if "enginelock.py hold --what" in x)
    what = line.split("--what ", 1)[1].split(" -- ", 1)[0]
    named = {}
    for argv in ([], ["site"]):
        ran = subprocess.run(
            ["bash", "-c", f"set -u; printf %s {what}", "verify.sh", *argv], capture_output=True, text=True
        )
        assert ran.returncode == 0, ran.stderr
        named[" ".join(argv)] = ran.stdout
    assert named == {"": "make verify", "site": "make verify-site"}


# The longest `fast` job measured: 711 s on pull request 128's head 797bff6 (job 135849299580), against
# 570 s on pull request 127, 502 s on 662fe5b (pull request 124's last run) and 578 s on wip/install2 at
# c49fece (run 44585103119, stopped at its limit then, 600 s, in step 3 of 4). The job's limit keeps half
# as much again beyond the longest: one more batch of tests or a slower runner is not red.
FAST_LONGEST = 711


def test_the_fast_job_s_limit_keeps_half_again_beyond_its_longest_measured_run():
    fast = workflow()["jobs"]["fast"]
    assert fast["timeout-minutes"] * 60 >= 1.5 * FAST_LONGEST, fast["timeout-minutes"]
