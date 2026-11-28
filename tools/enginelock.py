#!/usr/bin/env python3
"""The engine lock: long commands take turns on 1 machine, first come first served.

A long command (the table `LONG`) takes a ticket in the lock's folder and runs when no live ticket with
a lower number is left. A ticket is a file `<number>.ticket` whose process holds an exclusive flock on
it for as long as it lives; the kernel drops that flock when the process ends by any signal, SIGKILL
too. So a ticket is live while its flock is held, and nothing else is trusted: not a pid, which a
restart or a new process may reuse, and not the file being there. A dead ticket is removed by the next
process that looks, unless a process its run started (an engine) still runs: such a process carries
`WORKCENTER_LOCK_TICKET` naming the ticket in its environment (/proc/<pid>/environ), and the ticket counts
until the last of them ends. A run stopped by SIGTERM or SIGHUP passes the signal to the processes it
started before it frees its place.

Numbers come from `.seq` under its own flock, so 2 runs that come in the same millisecond get 2 numbers.
The kernel's flock on 1 file would serve waiters in no fixed order; the numbers keep the order they came.

A long command started by the holder, or by a process the holder started, runs at once: the live
holder's pid is the process itself or one of its ancestors (/proc/<pid>/stat). The holder hands its
children `WORKCENTER_LOCK_TICKET`, the path of its ticket; the variable alone opens nothing.

A waiting run says so on stderr, or in the file `WORKCENTER_LOCK_LOG` names: a test session names one
(tests/conftest.py), so a run of another session adds no line to the stderr a test compares.

macOS and Windows have no /proc, and every platform difference goes through tools/hostos.py:
- macOS: the lock is flock, as on Linux. `enginelock.py hold` hands its command the ticket's descriptor
  (`pass_fds()`), and the command shares its flock, so a ticket whose run died stays locked until that
  command ends. The other callers (`workcenter` commands and the engines they start) do not hand it on
  yet: a `workcenter sim` killed outright frees the lock while its ngspice runs. SIGTERM is not passed
  on: no list of the processes a run started can be read. A run inside the holder is known by
  `WORKCENTER_LOCK_TICKET` alone, so a stranger with a copy of it counts as inside.
- Windows: the lock is msvcrt.locking of 1 byte (hostos.lock_file). A ticket is written, closed,
  renamed and then locked, since a file open in Python cannot be renamed there. The weaker guarantee:
  the lock belongs to the run's own handle, so a run that dies frees it at once, even while an engine
  it started runs on; no engine is counted and none is passed SIGTERM. The stop signals are SIGTERM and
  SIGBREAK (hostos.stop_signals), and the lock folder is %LOCALAPPDATA%\\Via\\lock with no owner check.

Standard library only, as the CLI is (AGENTS.md invariants 3 and 14). `python3 tools/enginelock.py hold
-- CMD` runs any command under the lock, `held` answers whether this process may run without waiting,
and `state` prints who holds it.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime
import json
import os
import signal
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import clock
import hostos

ENV_DIR = "WORKCENTER_LOCK_DIR"
ENV_SWITCH = "WORKCENTER_LOCK"
ENV_TICKET = "WORKCENTER_LOCK_TICKET"
ENV_EVERY = "WORKCENTER_LOCK_EVERY"
ENV_LOG = "WORKCENTER_LOCK_LOG"
OFF = {"0", "off", "no", "false"}
EVERY = 30.0
POLL = 0.1
# Where Linux lists its processes; macOS and Windows have none.
PROC = Path("/proc")
# The flags of every os.open: O_CLOEXEC is POSIX only, and O_BINARY (Windows only) keeps os.write from
# turning "\n" into "\r\n" (Python's os documentation). On Linux this is O_CLOEXEC, as before.
OPEN = getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_BINARY", 0)

# Which commands take the lock, and when. A command starts an engine (kicad-cli, ngspice, FreeRouting,
# openEMS, a compiler, the chip tools) for more than a few seconds on the fixtures; the times are
# measured in docs/CONFIGURATION.md's table. Every other command never takes it and never waits.
LONG = {
    "gates": "always",
    "sim": "always",
    "mutate": "always",
    "bench": "always",
    "fields": "always",
    "autoroute": "always",
    "render": "always",
    "pictures": "always",
    "ci": "always",
    "copper": "always",
    "highspeed": "always",
    "export": "always",
    "design": "with --route",
    "verify": "without --init",
    "chip": "except chip init",
    "inspect": "inspect map only",
    # `measure` runs the project's whole sim, every deck and corner, as `sim` does (tools/measureplan.py).
    "measure": "always",
    # `legend` starts no engine, but judges every text against every other: 6.14 s on basalt v0.3.
    "legend": "always",
}

# The commands that never take the lock, each named so that a command added later is classed on purpose
# (tests/test_enginelock.py holds that every command of `workcenter --help` is in LONG or here).
SHORT = (
    "doctor",
    "erc",
    "drc",
    "procure",
    "sources",
    "fetch",
    "curve",
    "placement",
    "docs",
    "costs",
    "version",
    "diagram",
    "next",
    "ratings",
    "references",
    "now",
    "standards",
    "new",
    "image",  # reads 3 files at a commit with git and starts no engine: 0.22 s on 2026-11-18
    "mcp",  # a server that runs for a whole session; each command it starts takes the lock itself
)


def is_long(args: argparse.Namespace) -> bool:
    """True when this parsed command line takes the lock."""
    cmd = getattr(args, "command", None)
    if cmd == "design":
        # `--rules-only` refuses --route before any engine starts: it waits for no one's turn.
        return bool(getattr(args, "route", False)) and not getattr(args, "rules_only", False)
    if cmd == "verify":
        return not getattr(args, "init", False)
    if cmd == "chip":
        return getattr(args, "chip_command", None) != "init"
    if cmd == "inspect":
        return getattr(args, "view", None) == "map"
    return LONG.get(cmd) == "always"


class Refused(Exception):
    """The lock folder cannot be used; the message is the 1-line refusal."""


def lock_dir() -> Path:
    """`WORKCENTER_LOCK_DIR`, else 1 folder per machine and user (hostos.lock_dir):
    /tmp/workcenter-lock-<uid> on Linux and macOS, %LOCALAPPDATA%\\Via\\lock on Windows. Not the
    system's temporary folder, which follows TMPDIR: 2 runs whose TMPDIR differ would take 2 locks."""
    named = os.environ.get(ENV_DIR)
    return Path(named) if named else hostos.lock_dir()


def check(folder: Path) -> None:
    """Refuse a lock folder that cannot hold the lock, in 1 line that names the setting, the path and why.
    A folder that is not there yet is fine: the first ticket makes it."""
    named = os.environ.get(ENV_DIR)
    who = f"{ENV_DIR}={named}" if named else f"the lock folder {folder}"
    if named and not folder.is_absolute():
        raise Refused(f"engine lock: {who}: not an absolute path, so 2 runs in 2 folders would take 2 locks")
    try:
        st = folder.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise Refused(f"engine lock: {who}: {folder} cannot be read ({exc.strerror})") from None
    if not stat.S_ISDIR(st.st_mode):
        kind = "a link" if stat.S_ISLNK(st.st_mode) else "a file"
        raise Refused(
            f"engine lock: {who}: {folder} is not a folder (it is {kind}); name a folder or unset it"
        )
    uid = hostos.user_id()
    if not named and uid is not None and st.st_uid != uid:
        raise Refused(f"engine lock: {who} belongs to user {st.st_uid}, not to you ({uid})")
    if not os.access(folder, os.R_OK | os.W_OK | os.X_OK):
        raise Refused(f"engine lock: {who}: {folder} is not writable by you")


def enabled() -> bool:
    return os.environ.get(ENV_SWITCH, "").strip().lower() not in OFF


def every() -> float:
    try:
        return max(0.05, float(os.environ.get(ENV_EVERY, EVERY)))
    except ValueError:
        return EVERY


def notice(line: str, stream) -> None:
    """1 line that says a run waits for its turn or took it. It goes to the file `WORKCENTER_LOCK_LOG`
    names, where a test session sends it (tests/conftest.py): another session's run on the machine then
    adds no line to the stderr a test compares. Else, or when that file cannot be written, to `stream`."""
    named = os.environ.get(ENV_LOG)
    if named:
        try:
            with open(named, "a", encoding="utf-8") as log:
                log.write(line + "\n")
            return
        except OSError:
            pass
    print(line, file=stream, flush=True)


def _seq(name: str) -> int | None:
    stem, dot, ext = name.partition(".")
    return int(stem) if dot and ext == "ticket" and stem.isdigit() else None


def _alive(path: Path) -> bool:
    """True while a process holds the ticket's lock. A ticket that is gone is not alive."""
    try:
        fd = os.open(path, os.O_RDONLY | OPEN)
    except OSError:
        return False
    try:
        if not hostos.lock_file(fd):
            return True
        hostos.unlock_file(fd)
    finally:
        os.close(fd)
    return False


def _unlink(path: Path) -> None:
    """Remove a file that may be gone. On Windows a file another process has open cannot be removed:
    it stays, and the next survey that finds it dead removes it."""
    gone = (FileNotFoundError,) if hostos.flock_files() else (FileNotFoundError, PermissionError)
    with contextlib.suppress(*gone):
        path.unlink()


def _remove(path: Path) -> None:
    for p in (path, path.with_suffix(".held")):
        _unlink(p)


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return data if isinstance(data, dict) else {}


def _read_seq(fd: int) -> bytes:
    """The counter in `.seq`: its first 32 bytes. lseek and read, since os.pread is POSIX only."""
    os.lseek(fd, 0, os.SEEK_SET)
    return os.read(fd, 32)


def _pids() -> list[int]:
    try:
        return [int(n) for n in os.listdir(PROC) if n.isdigit()]
    except OSError:
        return []


def _procfs() -> bool:
    """True where the processes can be read in /proc (Linux): /proc/self/stat is there. A /proc that is
    an empty folder (a container may mount one) lists no process and counts as none."""
    return (PROC / "self" / "stat").is_file()


# The descriptor of the ticket this process holds, while it holds it. At most 1: a second `take` in the
# process is inside the holder and takes no ticket (tests/test_enginelock.py, 1 ticket at most).
_HELD: list[int] = []


def pass_fds() -> tuple[int, ...]:
    """The descriptors a run that holds the lock hands to the processes it starts:
    `subprocess.run(cmd, pass_fds=enginelock.pass_fds())`. Where there is no /proc and the lock is flock
    (macOS), the ticket's: the started processes then share its flock, and a ticket whose run died stays
    locked until the last of them ends. On Linux /proc finds them (`carriers`), and on Windows a child
    shares no lock: there it is empty, and so is it out of a run."""
    if not _HELD or not hostos.flock_files() or _procfs():
        return ()
    return (_HELD[-1],)


def carriers(path: Path, skip: set[int]) -> list[int]:
    """The processes, other than those in `skip`, that carry `WORKCENTER_LOCK_TICKET=<path>` in their
    environment: those a run started while it held the ticket. A process of another user, or a zombie,
    shows no environment and is not counted."""
    key = f"{ENV_TICKET}={path}".encode()
    found = []
    for pid in _pids():
        if pid in skip:
            continue
        try:
            env = (PROC / str(pid) / "environ").read_bytes()
        except OSError:
            continue
        if key in env.split(b"\0"):
            found.append(pid)
    return found


def descendants(pid: int | None = None) -> list[int]:
    """The process's children, their children and so on, from /proc; [] where /proc cannot be read."""
    root = os.getpid() if pid is None else pid
    kids: dict[int, list[int]] = {}
    for p in _pids():
        try:
            ppid = int((PROC / str(p) / "stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        kids.setdefault(ppid, []).append(p)
    found, todo = [], [root]
    while todo:
        for child in kids.get(todo.pop(), []):
            found.append(child)
            todo.append(child)
    return found


def survey(folder: Path | None = None) -> list[dict]:
    """The live tickets in the order they came, each with its number, path, pid, command and the time
    it came and took the lock (`since`, absent while it waits). A ticket whose process ended still counts
    while a process it started runs (`left`, their pids). Dead tickets are removed on the way."""
    folder = folder or lock_dir()
    check(folder)
    try:
        names = os.listdir(folder)
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise Refused(f"engine lock: the lock folder {folder} cannot be read ({exc.strerror})") from None
    tickets = [(name, folder / name) for name in sorted(n for n in names if _seq(n) is not None)]
    flocked = {name: _alive(path) for name, path in tickets}
    skip = {os.getpid()} | {_read(p).get("pid") for n, p in tickets if flocked[n]}
    live = []
    for name, path in tickets:
        left = [] if flocked[name] else carriers(path, skip)
        if not flocked[name] and not left:
            _remove(path)
            continue
        info = _read(path)
        if left:
            info["left"] = left
        with contextlib.suppress(OSError, ValueError):
            info["since"] = float(path.with_suffix(".held").read_text(encoding="utf-8"))
        info.update(seq=_seq(name), path=str(path))
        live.append(info)
    names = set(os.listdir(folder)) if folder.is_dir() else set()
    for name in names:
        if name.endswith(".held") and name[: -len(".held")] + ".ticket" not in names:
            _unlink(folder / name)
    return live


def state(folder: Path | None = None) -> dict:
    """The lock as `doctor` prints it: the folder, whether it is on, the holder and how many wait."""
    folder = folder or lock_dir()
    try:
        live = survey(folder)
    except Refused as exc:
        why = str(exc).removeprefix("engine lock: ")
        return {"dir": str(folder), "enabled": enabled(), "holder": None, "waiting": 0, "not_judged": why}
    return {
        "dir": str(folder),
        "enabled": enabled(),
        "holder": live[0] if live else None,
        "waiting": max(0, len(live) - 1),
    }


def ancestors(pid: int | None = None) -> list[int] | None:
    """The process's parent, grandparent and so on, from /proc; None where /proc cannot be read."""
    chain: list[int] = []
    p = os.getpid() if pid is None else pid
    for _ in range(4096):
        try:
            stat = (PROC / str(p) / "stat").read_text(encoding="utf-8")
        except OSError:
            return chain or None
        ppid = int(stat.rsplit(")", 1)[1].split()[1])
        if ppid <= 0:
            break
        chain.append(ppid)
        p = ppid
    return chain


def inside(folder: Path | None = None) -> dict | None:
    """The live holder when it is this process or an ancestor of it, else None. Where /proc cannot be
    read, a `WORKCENTER_LOCK_TICKET` equal to the live holder's ticket stands in for the ancestry."""
    live = survey(folder)
    if not live:
        return None
    holder = live[0]
    if holder.get("since") is None:
        return None
    # A holder that ended counts through the processes it started: a run under one of them is inside.
    pids = {holder.get("pid"), *holder.get("left", [])}
    chain = ancestors()
    if chain is None:
        return holder if os.environ.get(ENV_TICKET) == holder["path"] else None
    return holder if os.getpid() in pids or pids & set(chain) else None


def _clock(t: float) -> str:
    return datetime.datetime.fromtimestamp(t).strftime("%H:%M:%S")


def _span(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min {s % 60} s"
    return f"{s // 3600} h {s % 3600 // 60} min"


def _runs(n: int) -> str:
    return f"{n} run{'' if n == 1 else 's'} ahead"


def holder_text(holder: dict, now: float | None = None) -> str:
    now = clock.stamp() if now is None else now
    what = holder.get("what") or "an unnamed run"
    since = holder.get("since")
    when = f"since {_clock(since)}, {_span(now - since)} ago" if since else "taking it now"
    text = f"held by `{what}` (pid {holder.get('pid')}) {when}"
    left = holder.get("left")
    if left:
        pids = ", ".join(str(p) for p in left)
        if len(left) == 1:
            text += f", which ended; 1 process it started still runs (pid {pids})"
            text += " and keeps the lock until it ends"
        else:
            text += f", which ended; {len(left)} processes it started still run (pid {pids})"
            text += " and keep the lock until they end"
    return text


class Ticket:
    """1 run's place in the line. `wait()` returns when it is the first live ticket; `release()` frees
    it. A process that dies frees it as well, by the kernel."""

    def __init__(self, what: str, folder: Path | None = None):
        self.folder = folder or lock_dir()
        self.what = what
        self.came = clock.stamp()
        self.fd: int | None = None
        self.path: Path | None = None
        self.seq = 0
        self.ahead = 0
        self.waited = 0.0
        self._take()

    def _take(self) -> None:
        check(self.folder)
        try:
            self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            seq_fd = os.open(self.folder / ".seq", os.O_RDWR | os.O_CREAT | OPEN, 0o600)
        except OSError as exc:
            raise Refused(
                f"engine lock: the lock folder {self.folder} cannot be written ({exc.strerror})"
            ) from None
        locked = False
        try:
            locked = hostos.lock_file(seq_fd, wait=True)
            raw = _read_seq(seq_fd).strip()
            names = os.listdir(self.folder)
            last = max([_seq(n) or 0 for n in names] + [int(raw) if raw.isdigit() else 0])
            # A run that died between its file and its rename left `.new-*`; under `.seq` no one
            # else is making one, so each is dead.
            for name in names:
                if name.startswith(".new-"):
                    _unlink(self.folder / name)
            self.seq = last + 1
            tmp = self.folder / f".new-{os.getpid()}-{self.seq}"
            info = {"pid": os.getpid(), "what": self.what, "cwd": os.getcwd(), "came": self.came}
            data = json.dumps(info).encode()
            self.path = self.folder / f"{self.seq:012d}.ticket"
            fd = os.open(tmp, os.O_RDWR | os.O_CREAT | os.O_TRUNC | OPEN, 0o600)
            if hostos.flock_files():
                # Locked before it has its name: no survey ever finds this ticket unlocked.
                if not hostos.lock_file(fd):
                    raise BlockingIOError(f"engine lock: {tmp} is locked by another process")
                os.write(fd, data)
                os.rename(tmp, self.path)
                self.fd = fd
            else:
                os.write(fd, data)
                os.close(fd)
                self.fd = self._own(tmp, data)
            os.ftruncate(seq_fd, 0)
            os.lseek(seq_fd, 0, os.SEEK_SET)
            os.write(seq_fd, str(self.seq).encode())
        finally:
            # Windows frees the lock of a handle closed while locked only "at a time that depends upon
            # available system resources" (LockFileEx), and the next run waits on `.seq` till then.
            if locked:
                hostos.unlock_file(seq_fd)
            os.close(seq_fd)

    def _own(self, tmp: Path, data: bytes) -> int:
        """Windows: rename the closed ticket to its name, open it again and lock it. A file Python has
        open cannot be renamed there (hostos.flock_files). Between the rename and the open, another run's
        survey may find the ticket unlocked and remove it: it is written and renamed again. Between the
        open and the lock it cannot be removed (it is open), and a survey's own short lock is waited out.
        No other run takes this number meanwhile: this run holds `.seq`."""
        while True:
            os.rename(tmp, self.path)
            try:
                fd = os.open(self.path, os.O_RDWR | OPEN)
            except FileNotFoundError:
                again = os.open(tmp, os.O_RDWR | os.O_CREAT | os.O_TRUNC | OPEN, 0o600)
                os.write(again, data)
                os.close(again)
                continue
            hostos.lock_file(fd, wait=True)
            return fd

    def wait(self, stream=None) -> None:
        stream = sys.stderr if stream is None else stream
        start = time.monotonic()
        told = None
        while True:
            live = survey(self.folder)
            ahead = [t for t in live if t["seq"] < self.seq]
            self.ahead = len(ahead)
            self.waited = time.monotonic() - start
            if not ahead:
                break
            if told is None or time.monotonic() - told >= every():
                told = time.monotonic()
                line = f"workcenter: waiting on the engine lock: {_runs(len(ahead))}; {holder_text(ahead[0])}"
                notice(f"{line}; lock folder {self.folder}", stream)
            time.sleep(POLL)
        if told is not None:
            notice(f"workcenter: took the engine lock after {_span(self.waited)}", stream)
        held = self.path.with_suffix(".held")
        tmp = self.folder / f".held-{os.getpid()}-{self.seq}"
        tmp.write_text(repr(clock.stamp()), encoding="utf-8")
        os.rename(tmp, held)

    def release(self, unlink: bool = True) -> None:
        """Free the place. `unlink=False` leaves the file for the next survey, which keeps it while a
        process this run started still runs."""
        if self.fd is None:
            return
        if hostos.flock_files():
            if unlink:
                _remove(self.path)
            os.close(self.fd)
        else:
            # Windows removes no file this run still has open: close it first.
            hostos.unlock_file(self.fd)
            os.close(self.fd)
            if unlink:
                _remove(self.path)
        self.fd = None


# SIGTERM and SIGHUP on Linux and macOS, SIGTERM and SIGBREAK on Windows (hostos.stop_signals).
_STOPS = hostos.stop_signals()


@contextlib.contextmanager
def _told_on_stop(ticket: Ticket, stream):
    """A run stopped by SIGTERM or SIGHUP (a host's time limit) passes the signal to the processes it
    started, prints 1 line that says so, frees its ticket, and dies of the same signal. Where it started
    any, the ticket file stays: it counts until the last of them has ended (`survey`). Without /proc it
    finds none to pass the signal to; a run that holds the lock leaves the file while `pass_fds()` names
    it: on macOS the processes that took it keep it locked until they end. A waiting run, and a run on
    Windows, removes it. Only the main thread may set handlers."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    phase = {"held": None}

    def stop(signum, _frame):
        name = signal.Signals(signum).name
        if phase["held"] is None:
            doing = f"after waiting {_span(ticket.waited)} on the engine lock, {_runs(ticket.ahead)}"
        else:
            doing = f"after holding the engine lock for {_span(time.monotonic() - phase['held'])}"
        sent = 0
        for pid in descendants():
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signum)
                sent += 1
        passed = f"; passed it to {sent} process{'' if sent == 1 else 'es'} it started" if sent else ""
        print(
            f"workcenter: stopped by signal {signum} ({name}) {doing}: {ticket.what}{passed}",
            file=stream,
            flush=True,
        )
        # The file stays while a process may hold it: one it passed the signal to, or one it handed the
        # ticket's descriptor (`pass_fds`, only while it holds). A waiting run started none.
        ticket.release(unlink=not sent and not pass_fds())
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    before = {s: signal.signal(s, stop) for s in _STOPS}
    try:
        yield phase
    finally:
        for s, h in before.items():
            signal.signal(s, h)


@contextlib.contextmanager
def take(what: str, stream=None):
    """Hold the lock for the body: at once when it is off or this process is inside the holder's tree,
    else after every run that came earlier. Yields the ticket, or None when none was taken."""
    stream = sys.stderr if stream is None else stream
    if not enabled() or inside() is not None:
        yield None
        return
    ticket = Ticket(what)
    before = os.environ.get(ENV_TICKET)
    try:
        with _told_on_stop(ticket, stream) as phase:
            ticket.wait(stream)
            if phase is not None:
                phase["held"] = time.monotonic()
            os.environ[ENV_TICKET] = str(ticket.path)
            _HELD.append(ticket.fd)
            yield ticket
    finally:
        if ticket.fd in _HELD:
            _HELD.remove(ticket.fd)
        ticket.release()
        if before is None:
            os.environ.pop(ENV_TICKET, None)
        else:
            os.environ[ENV_TICKET] = before


def for_command(args: argparse.Namespace, argv: list[str]):
    """The lock for 1 `workcenter` command line: taken when the command is long, else nothing."""
    if not is_long(args):
        return contextlib.nullcontext()
    return take(hostos.shell_line(["workcenter", *argv]))


def status_line(st: dict) -> str:
    if st.get("not_judged"):
        return f"not judged: {st['not_judged']}"
    if not st["enabled"]:
        return f"off ({ENV_SWITCH}={os.environ.get(ENV_SWITCH)}); folder {st['dir']}"
    if st["holder"] is None:
        return f"free ({st['dir']})"
    return f"{holder_text(st['holder'])}, {st['waiting']} waiting ({st['dir']})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="enginelock.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("hold", help="run 1 command under the engine lock; its exit code is the command's")
    p.add_argument("--what", help="the name the waiting line and doctor show (default: the command)")
    p.add_argument("cmd", nargs=argparse.REMAINDER, help="-- and the command")
    sub.add_parser("held", help="exit 0 when this process may run a long command without waiting")
    p = sub.add_parser("state", help="who holds the lock, since when, and how many wait")
    p.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        return _act(parser, args)
    except Refused as exc:
        print(f"enginelock.py: {exc}", file=sys.stderr)
        return 2


def _act(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    if args.action == "held":
        return 0 if not enabled() or inside() is not None else 1
    if args.action == "state":
        st = state()
        if st.get("not_judged"):
            raise Refused(f"engine lock: {st['not_judged']}")
        print(json.dumps(st, indent=2) if args.json else f"engine lock: {status_line(st)}")
        return 0
    cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    if not cmd:
        parser.error("hold needs a command after --")
    with take(args.what or hostos.shell_line(cmd)):
        try:
            code = subprocess.run(cmd, pass_fds=pass_fds()).returncode
            # A command that died of a signal exits as a shell reports it: 128 and the signal.
            return 128 - code if code < 0 else code
        except FileNotFoundError:
            print(f"enginelock.py: no command {cmd[0]}", file=sys.stderr)
            return 127


if __name__ == "__main__":
    sys.exit(main())
