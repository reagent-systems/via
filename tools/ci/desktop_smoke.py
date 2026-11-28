#!/usr/bin/env python3
"""desktop_smoke — the proof that Via works where its installer put it: CI's Windows and macOS legs.

It runs the installed `workcenter` command, as a person runs it after the installer, in this order:

    1 doctor        `workcenter doctor`: exit 0, no required engine missing
    2 gates-green   `workcenter gates --strict` on a copy of tests/boards/pass-first-design: GREEN, exit 0
    3 gates-drc     `workcenter gates` on a copy of tests/boards/fail-drc-clearance: RED, exit 1, `clearance`
    4 gates-sim     `workcenter gates` on a copy of tests/boards/fail-sim-spec: RED, exit 1, `vout`
    5 design-check  `workcenter design tests/boards/pass-first-design/design.py --check`: exit 0
    6 next          `workcenter next` on the copy of pass-first-design: exit 0 or 1, a `NEXT` line
    7 autoroute     `workcenter autoroute --apply` on a copy of tests/boards/route-me: exit 0, a `PASS` line
    8 tests         verify/testshards.py on the test files verify/desktop.csv names: exit 0, at least 1 passed

The 2 RED fixtures matter as much as the GREEN one: a gate that passes because its engine never ran
must show as wrong. A gate whose engine is absent exits 2 (SKIPPED), never 1. Each fixture is copied
into the work folder first, so the gates write nothing into the checkout.

Each step prints its command, its output under `  | `, then 1 line: `desktop-smoke: [n/8] <name>: ok`
or `FAIL (<why>)`, with its seconds. Every step runs, after a failed one too, so 1 run reports every
step's state. The last line is `DESKTOP SMOKE GREEN: ...` (exit 0) or `DESKTOP SMOKE RED: ...` (exit 1);
misuse is exit 2. Standard library only, and tools/hostos.py to end a step's process tree on time.

    desktop_smoke.py [--repo R] [--workcenter W] [--python P] [--work D] [--only STEP ...] [--list]
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import hostos  # noqa: E402

# The fixtures the steps copy, under tests/boards/.
FIXTURES = ("pass-first-design", "fail-drc-clearance", "fail-sim-spec", "route-me")
# The file verify/testshards.py reads for the files this system must pass (the wtests piece writes it).
DESKTOP_TABLE = "verify/desktop.csv"
# A step's bound in s. No run on macOS or Windows is measured yet; on Linux 1 fixture's gates take
# seconds. The bound only ends a step that hangs (a router waiting for a window), well inside the leg.
STEP_SECONDS = 900
TESTS_SECONDS = 1800
# After a step's tree is ended, how long its output pipe may stay open. On Windows taskkill can fail, and
# Popen.kill() then ends only workcenter.cmd's cmd.exe while its Python holds the pipe.
DRAIN_SECONDS = 30
# A count of passed tests, as testshards' `outcomes: 12 passed, ...` line and pytest's own summary give it.
PASSED = re.compile(r"\b[1-9]\d* passed\b")


@dataclass
class Step:
    name: str
    title: str
    argv: list[str]
    codes: tuple[int, ...]
    # Each check: what the output must show, and the test on (output lines).
    checks: list[tuple[str, Callable[[list[str]], bool]]] = field(default_factory=list)
    # The step's bound in s; 0 is STEP_SECONDS, read when the step runs.
    seconds: int = 0

    @property
    def bound(self) -> int:
        return self.seconds or STEP_SECONDS


def last_line_starts(word: str) -> tuple[str, Callable[[list[str]], bool]]:
    return (f"its last line starts with {word}", lambda lines: bool(lines) and lines[-1].startswith(word))


def a_line_starts(word: str) -> tuple[str, Callable[[list[str]], bool]]:
    return (f"a line starts with {word}", lambda lines: any(line.startswith(word) for line in lines))


def says(word: str) -> tuple[str, Callable[[list[str]], bool]]:
    return (f"it names {word}", lambda lines: any(word in line for line in lines))


def some_passed() -> tuple[str, Callable[[list[str]], bool]]:
    """Exit 0 with 0 tests run is no pass: a list that names no file, or names files that match none."""
    return ("a line names at least 1 passed test", lambda lines: any(PASSED.search(line) for line in lines))


def steps(repo: Path, wc: str, python: str, work: Path) -> list[Step]:
    boards = work / "boards"
    first = str(boards / "pass-first-design")
    return [
        Step("doctor", "workcenter doctor", [wc, "doctor"], (0,)),
        Step(
            "gates-green",
            "gates GREEN on pass-first-design",
            [wc, "gates", "--strict", first],
            (0,),
            [last_line_starts("GREEN")],
        ),
        Step(
            "gates-drc",
            "gates RED on fail-drc-clearance",
            [wc, "gates", str(boards / "fail-drc-clearance")],
            (1,),
            [last_line_starts("RED"), says("clearance")],
        ),
        Step(
            "gates-sim",
            "gates RED on fail-sim-spec",
            [wc, "gates", str(boards / "fail-sim-spec")],
            (1,),
            [last_line_starts("RED"), says("vout")],
        ),
        Step(
            "design-check",
            "design --check on pass-first-design",
            [wc, "design", str(repo / "tests" / "boards" / "pass-first-design" / "design.py"), "--check"],
            (0,),
        ),
        Step("next", "next on pass-first-design", [wc, "next", first], (0, 1), [a_line_starts("NEXT")]),
        Step(
            "autoroute",
            "autoroute --apply on route-me",
            [wc, "autoroute", str(boards / "route-me"), "--apply"],
            (0,),
            [a_line_starts("PASS")],
        ),
        Step(
            "tests",
            f"the test files of {DESKTOP_TABLE}",
            [
                python,
                str(repo / "verify" / "testshards.py"),
                "run",
                "--root",
                str(repo),
                "--table",
                str(repo / "verify" / "shards.csv"),
                "--python",
                python,
                "--only",
                str(repo / DESKTOP_TABLE),
                "--work",
                str(work / "tests"),
            ],
            (0,),
            [some_passed()],
            seconds=TESTS_SECONDS,
        ),
    ]


def shown(argv: list[str]) -> str:
    return " ".join(f'"{a}"' if (" " in a or not a) else a for a in argv)


def run_step(step: Step, cwd: Path) -> tuple[int | None, list[str], float]:
    """The step's exit code (None when it ran past its bound or could not start), its output's lines and
    its seconds. Output and errors are 1 stream, in order, read as UTF-8."""
    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            step.argv,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=os.name == "posix",
        )
    except OSError as exc:
        return None, [f"could not start: {exc}"], time.monotonic() - started
    try:
        out, _ = proc.communicate(timeout=step.bound)
        code: int | None = proc.returncode
    except subprocess.TimeoutExpired:
        hostos.kill_tree(proc)
        held = False
        try:
            out, _ = proc.communicate(timeout=DRAIN_SECONDS)
        except subprocess.TimeoutExpired as exc:
            # A process the kill did not reach holds the pipe. On Linux and macOS the exception carries
            # all that was read; on Windows Python gives none of it. The pipe is closed only where no
            # reader thread holds its lock (Windows reads it in a thread that would block the close).
            out, held = exc.output or b"", True
            if os.name == "posix" and proc.stdout is not None:
                proc.stdout.close()
        code = None
    lines = out.decode("utf-8", errors="replace").splitlines()
    if code is None:
        if held:
            lines.append(
                f"a process it started held its output open {DRAIN_SECONDS} s after the kill; "
                "what was read is above"
            )
        lines.append(f"ended after its bound of {step.bound} s")
    return code, lines, time.monotonic() - started


def judge(step: Step, code: int | None, lines: list[str]) -> list[str]:
    """What the step lacked; empty when it is ok."""
    if code is None:
        return [lines[-1] if lines else "it did not start"]
    wanted = " or ".join(str(c) for c in step.codes)
    why = [] if code in step.codes else [f"exit {code}, wanted {wanted}"]
    why += [f"not: {words}" for words, test in step.checks if not test(lines)]
    return why


def copy_fixtures(repo: Path, work: Path) -> None:
    """Each fixture into work/boards/, without what a run left in the checkout: build/, a .kicad_prl."""
    for name in FIXTURES:
        dest = work / "boards" / name
        shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(
            repo / "tests" / "boards" / name, dest, ignore=shutil.ignore_patterns("build", "*.kicad_prl")
        )


def on_path(name: str) -> str | None:
    """`name` as PATH finds it, never the working folder. On Windows shutil.which looks in the working
    folder first unless NoDefaultCurrentDirectoryInExePath is set (Microsoft's
    NeedCurrentDirectoryForExePath), and the smoke runs in the checkout, which holds workcenter.cmd: run
    46067841222 found `.\\workcenter.CMD` there, not the command install.ps1 put on PATH. A hit that
    is not a whole path came from the working folder and is not taken."""
    before = os.environ.get("NoDefaultCurrentDirectoryInExePath")
    os.environ["NoDefaultCurrentDirectoryInExePath"] = "1"
    try:
        found = shutil.which(name)
    finally:
        if before is None:
            del os.environ["NoDefaultCurrentDirectoryInExePath"]
        else:
            os.environ["NoDefaultCurrentDirectoryInExePath"] = before
    return found if found and os.path.isabs(found) else None


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="desktop_smoke.py", description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--repo", type=Path, default=ROOT, help="the checkout (default: this script's)")
    ap.add_argument("--workcenter", help="the installed command (default: `workcenter` on PATH)")
    ap.add_argument("--python", default=sys.executable, help="the Python with pytest (default: this one)")
    ap.add_argument("--work", type=Path, help="folder for the fixtures' copies and logs (default: a new one)")
    ap.add_argument("--only", nargs="+", metavar="STEP", help="run these steps alone, in the list's order")
    ap.add_argument("--list", action="store_true", help="print each step's name and title, run nothing")
    args = ap.parse_args(argv)
    repo = args.repo.resolve()
    work = (args.work or Path(tempfile.mkdtemp(prefix="desktop-smoke-"))).resolve()
    wc = args.workcenter or on_path("workcenter") or ""
    plan = steps(repo, wc or "workcenter", args.python, work)
    if args.list:
        for step in plan:
            print(f"{step.name:13} {step.title}")
        return 0
    names = [s.name for s in plan]
    unknown = [n for n in args.only or [] if n not in names]
    if unknown:
        print(f"desktop-smoke: no step {', '.join(unknown)}; the steps: {', '.join(names)}", file=sys.stderr)
        return 2
    if not wc:
        print(
            "desktop-smoke: no `workcenter` on PATH: run the installer first, or give --workcenter",
            file=sys.stderr,
        )
        return 2
    if args.only:
        plan = [s for s in plan if s.name in args.only]
    work.mkdir(parents=True, exist_ok=True)
    copy_fixtures(repo, work)
    print(f"desktop-smoke: {sys.platform}, workcenter {wc}, checkout {repo}, work {work}")
    failed: list[str] = []
    began = time.monotonic()
    for n, step in enumerate(plan, 1):
        head = f"desktop-smoke: [{n}/{len(plan)}] {step.name}"
        print(f"{head}: $ {shown(step.argv)}", flush=True)
        code, lines, seconds = run_step(step, repo)
        for line in lines:
            print(f"  | {line}")
        why = judge(step, code, lines)
        if why:
            failed.append(step.name)
            print(f"{head}: FAIL ({'; '.join(why)}) in {seconds:.1f} s", flush=True)
        else:
            print(f"{head}: ok (exit {code}) in {seconds:.1f} s", flush=True)
    total = time.monotonic() - began
    if failed:
        named = ", ".join(failed)
        print(f"DESKTOP SMOKE RED: {len(failed)} of {len(plan)} steps failed: {named} ({total:.1f} s)")
        return 1
    print(f"DESKTOP SMOKE GREEN: {len(plan)} of {len(plan)} steps passed in {total:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
