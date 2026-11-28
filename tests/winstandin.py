"""A stand-in for Windows on Linux, for the tests of the router and of `workcenter mcp`.

Nothing here runs Windows. It holds what the code may and may not use there, and runs the real code:
- `sys.platform` is "win32", which tools/hostos.py reads.
- os.killpg and signal.SIGHUP are gone, as on Windows (Python's os and signal documentation), and
  signal.SIGBREAK is there.
- subprocess.Popen refuses start_new_session and preexec_fn: Windows ignores the first and refuses the
  second, so a call that passes either does not do there what it does here. It keeps `creationflags`
  in its record and starts the child without them, which Linux cannot take.
- `taskkill` on PATH is a stand-in: it writes its arguments to a log and ends the pid it names with
  SIGKILL, the pid alone. Windows' taskkill /T ends the tree too; nothing here shows that.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path

TASKKILL = """#!{python}
import json, os, signal, sys
with open({log!r}, "a", encoding="utf-8") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
os.kill(int(sys.argv[sys.argv.index("/PID") + 1]), signal.SIGKILL)
"""


class Windows:
    """What the stand-in saw: each Popen's keyword arguments, and each taskkill's arguments."""

    def __init__(self, folder: Path):
        self.popens: list[dict] = []
        self.log = folder / "taskkill.jsonl"

    def taskkills(self) -> list[list[str]]:
        if not self.log.is_file():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]


def windows(monkeypatch, folder: Path) -> Windows:
    """Make this process look like Windows to the code under test, as the module's docstring says."""
    folder.mkdir(parents=True, exist_ok=True)
    seen = Windows(folder)
    real = subprocess.Popen

    class Popen(real):
        def __init__(self, *args, **kwargs):
            seen.popens.append(dict(kwargs))
            if kwargs.get("start_new_session"):
                raise AssertionError("start_new_session does nothing on Windows")
            if kwargs.get("preexec_fn") is not None:
                raise ValueError("preexec_fn is not supported on Windows platforms")
            kwargs.pop("creationflags", None)
            super().__init__(*args, **kwargs)

    bin_dir = folder / "bin"
    bin_dir.mkdir(exist_ok=True)
    taskkill = bin_dir / "taskkill"
    taskkill.write_text(TASKKILL.format(python=sys.executable, log=str(seen.log)), encoding="utf-8")
    taskkill.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setattr(subprocess, "Popen", Popen)
    monkeypatch.setattr(sys, "platform", "win32")
    # shutil.which reads PATHEXT on win32 and splits it on os.pathsep, ":" here.
    monkeypatch.setenv("PATHEXT", os.pathsep.join([".COM", ".EXE", ".BAT", ".CMD"]))
    monkeypatch.delattr(os, "killpg")
    monkeypatch.delattr(signal, "SIGHUP")
    monkeypatch.setattr(signal, "SIGBREAK", 21, raising=False)
    return seen
