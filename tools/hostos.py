"""Every difference between Linux, macOS and Windows that Via's tools need, in 1 place.

Each function reads `sys.platform` when it is called ("linux", "darwin", "win32"), never `os.name`, so a
test sets the platform with 1 attribute. On Linux each returns what the code returns today; the comment
of each names the file and line that holds that value at main cea464d. tools/enginelock.py calls
lock_dir, user_id, lock_file, unlock_file, flock_files and stop_signals; tools/routers.py,
tools/routebench.py and tools/mcpserver.py call it too; write_text is called by tools/kicadgen.py,
tools/newboard.py and the run decks of tools/workcenter, and installer_command by tools/guide.py. The
test runner (verify/testshards.py: kill_tree, stop_signals) and the engine guard of the tests
(tools/ci/guard/engine_watch.py: program_name) call it as well.

The macOS and Windows values come from vendor documents and build files, named beside each. None was
seen on a Mac or a Windows machine: each is marked "not confirmed in a run" until a run there shows it.

Standard library only, as the CLI (AGENTS.md invariant 3).
"""

from __future__ import annotations

import errno
import os
import shlex
import signal
import subprocess
import sys
import time
from collections.abc import Iterable
from pathlib import Path

# The KiCad 10 application bundle the official DMG and the Homebrew cask `kicad` install
# (https://www.kicad.org/download/macos/, https://formulae.brew.sh/api/cask/kicad.json). Not confirmed
# in a run.
MAC_APP = Path("/Applications/KiCad/KiCad.app")
# Inside a bundle's Contents: KiCad's own Python (kigadgets' macOS notes; KiCad's mac builder ships it as
# a relocatable Python.framework). Not confirmed in a run.
MAC_PYTHON = Path("Frameworks") / "Python.framework" / "Versions" / "Current" / "bin" / "python3"
# KiCad 10's installer for Windows puts the suite in "KiCad\<major.minor>" under Program Files, and a
# per-user install under %LOCALAPPDATA%\Programs (kicad-win-builder, nsis/install.nsi). Not confirmed in
# a run.
WIN_KICAD = Path("KiCad") / "10.0"
# Homebrew's prefixes: /opt/homebrew on Apple Silicon, /usr/local on Intel (docs.brew.sh/Installation).
BREW_BINS = ("/opt/homebrew/bin", "/usr/local/bin")
# Where ngspice's Windows archive is unpacked by convention (ngspice-47_64.7z holds a Spice64 folder).
# Neither the folder nor the console program's name is confirmed in a run.
WIN_SPICE = Path("C:\\Spice64") / "bin"
# Apple's /usr/bin/java is a launcher, not a JVM: it runs the JDK JAVA_HOME names, else the one
# /usr/libexec/java_home prints (Apple's java_home(1) man page). Not confirmed in a run.
MAC_JAVA_STUB = Path("/usr/bin/java")
MAC_JAVA_HOME = Path("/usr/libexec/java_home")
# Oracle's installer for Windows puts launchers in "Common Files\Oracle\Java\javapath" (Oracle's JDK
# installation guide for Windows). Not confirmed in a run.
WIN_JAVA_STUBS = "javapath"
# Windows' CREATE_NEW_PROCESS_GROUP and CTRL_BREAK_EVENT (Microsoft's "Process Creation Flags" and
# GenerateConsoleCtrlEvent): subprocess and signal name them only on Windows.
WIN_NEW_GROUP = 0x00000200
WIN_CTRL_BREAK = 1


def _windows() -> bool:
    return sys.platform == "win32"


def _mac() -> bool:
    return sys.platform == "darwin"


def _local_appdata() -> Path:
    """%LOCALAPPDATA%: 1 folder per user, never roamed. Windows sets it in every session."""
    named = os.environ.get("LOCALAPPDATA")
    return Path(named) if named else Path.home() / "AppData" / "Local"


def default_root() -> Path:
    """The workcenter's root when WORKCENTER_ROOT is not set; the callers read that variable.

    Linux: tools/workcenter:40, tools/routers.py:31 and :133, tools/fields.py:1442.
    macOS: a folder of the user's, so no step needs sudo. Windows: %LOCALAPPDATA%\\Via. Both are the
    plan's choice, open to the owner (winmac plan, owner decision 5)."""
    if _windows():
        return _local_appdata() / "Via"
    if _mac():
        return Path.home() / "Library" / "Application Support" / "via"
    return Path("/opt/workcenters/ee")


def lock_dir() -> Path:
    """The engine lock's folder when WORKCENTER_LOCK_DIR is not set; tools/enginelock.py reads that
    variable and checks the folder.

    Linux and macOS: tools/enginelock.py:132, 1 folder per machine and user in /tmp (macOS has /tmp).
    Windows: os.getuid does not exist there (Python's os documentation), and %LOCALAPPDATA% is already
    1 folder per user, so the name carries no user id."""
    if _windows():
        return _local_appdata() / "Via" / "lock"
    return Path("/tmp") / f"workcenter-lock-{os.getuid()}"


def venv_python(root: Path | str) -> Path:
    """The Python of the venv under `root`.

    Linux and macOS: tools/workcenter:5264, 5955, 5979, 6061 (`venv/bin/python`). Windows: a venv puts
    its programs in Scripts and names Python python.exe (Python's venv documentation)."""
    if _windows():
        return Path(root) / "venv" / "Scripts" / "python.exe"
    return Path(root) / "venv" / "bin" / "python"


def _named_cli() -> Path | None:
    """KICAD_CLI when it names a file by its whole path, not a name to look up on PATH."""
    named = os.environ.get("KICAD_CLI", "")
    return Path(named) if named and Path(named).is_absolute() else None


def _mac_contents() -> list[Path]:
    """The Contents folders of the KiCad bundles to look in: the one KICAD_CLI lies in (the cask's link in
    Homebrew's bin resolves into the bundle), then the one in /Applications."""
    found = []
    cli = _named_cli()
    if cli is not None:
        for path in (cli, cli.resolve()):
            if path.parent.name == "MacOS" and path.parent.parent.name == "Contents":
                found.append(path.parent.parent)
                break
    return [*found, MAC_APP / "Contents"]


def _win_installs() -> list[Path]:
    """The KiCad install folders to look in: the one KICAD_CLI's bin lies in, then the machine install,
    then the per-user install."""
    found = []
    cli = _named_cli()
    if cli is not None and cli.parent.name.lower() == "bin":
        found.append(cli.parent.parent)
    program_files = Path(os.environ.get("ProgramFiles") or "C:\\Program Files")
    return [*found, program_files / WIN_KICAD, _local_appdata() / "Programs" / WIN_KICAD]


def kicad_python() -> str | None:
    """The Python that imports KiCad's `pcbnew`; None where no KiCad is found.

    Linux: tools/workcenter:5262-5265, the venv's Python, else this one. install.sh makes the venv with
    --system-site-packages, so it sees the pcbnew of KiCad's package.
    macOS: the python3 inside KiCad's bundle; 3.9.13 in the 10.0 build recipe (kicad-mac-builder,
    CMakeLists.txt PYTHON_VERSION). Windows: bin\\python.exe of the install, which build.ps1 copies from
    vcpkg's python3 3.11.5 (KiCad's vcpkg.json at tag 10.0.8). Neither version nor the import of pcbnew
    from a plain shell is confirmed in a run."""
    if _windows():
        for home in _win_installs():
            py = home / "bin" / "python.exe"
            if py.is_file():
                return str(py)
        return None
    if _mac():
        for contents in _mac_contents():
            py = contents / MAC_PYTHON
            if py.is_file():
                return str(py)
        return None
    py = venv_python(os.environ.get("WORKCENTER_ROOT", default_root()))
    return str(py) if py.exists() else sys.executable


def kicad_cli_candidates() -> list[str]:
    """The kicad-cli programs to try, in order: a name for shutil.which (which adds PATHEXT's .exe on
    Windows), or a whole path. KICAD_CLI, when set, is the only one.

    Linux: tools/workcenter:43. macOS: the program inside the bundle (KiCad 10's CLI manual,
    docs.kicad.org/10.0/en/cli). Windows: bin\\kicad-cli.exe of the machine install, then of the
    per-user one; KiCad's installer puts nothing on PATH (kicad-win-builder). The Windows paths are not
    confirmed in a run."""
    named = os.environ.get("KICAD_CLI")
    if named is not None:
        return [named]
    if _windows():
        return ["kicad-cli", *(str(home / "bin" / "kicad-cli.exe") for home in _win_installs())]
    if _mac():
        return ["kicad-cli", str(MAC_APP / "Contents" / "MacOS" / "kicad-cli")]
    return ["kicad-cli"]


def ngspice_candidates() -> list[str]:
    """The ngspice programs to try, in order, as kicad_cli_candidates. NGSPICE, when set, is the only one.

    Linux: tools/workcenter:44. macOS: Homebrew's formula `ngspice` (47) links it into Homebrew's bin,
    which a shell that did not read Homebrew's profile lacks on PATH. Windows: the console program first;
    KiCad's install ships ngspice only as a library. Not confirmed in a run: the name ngspice_con.exe and
    the Spice64 folder."""
    named = os.environ.get("NGSPICE")
    if named is not None:
        return [named]
    if _windows():
        return ["ngspice_con", "ngspice", str(WIN_SPICE / "ngspice_con.exe"), str(WIN_SPICE / "ngspice.exe")]
    if _mac():
        return ["ngspice", *(f"{b}/ngspice" for b in BREW_BINS)]
    return ["ngspice"]


def kicad_share() -> Path:
    """The install's folder of KiCad's stock libraries, whatever the variables say.

    Linux: /usr/share/kicad (tools/workcenter:70 keeps its 3dmodels apart from every variable).
    macOS: the bundle's Contents/SharedSupport. Windows: share\\kicad of the first install that has one,
    else of the first install. Not confirmed in a run off Linux."""
    if _windows():
        installs = _win_installs()
        home = next((h for h in installs if (h / "share" / "kicad").is_dir()), installs[0])
        return home / "share" / "kicad"
    if _mac():
        return _mac_contents()[0] / "SharedSupport"
    return Path("/usr/share/kicad")


def kicad_dirs() -> dict[str, Path]:
    """KiCad's library folders: "symbols", "footprints" and "3dmodels".

    Each takes Via's own variable first, where it has one (KICAD_SYMBOL_DIR, KICAD_FOOTPRINT_DIR), then
    KiCad's own (KICAD10_SYMBOL_DIR, KICAD10_FOOTPRINT_DIR, KICAD10_3DMODEL_DIR), then the install's.
    Linux: tools/kicadgen.py:46-47 read only Via's 2 variables and the 3D folder reads
    KICAD10_3DMODEL_DIR (tools/workcenter:70 and :2505), so Linux reads no KICAD10_ library variable
    here either. macOS: the bundle's Contents/SharedSupport (KiCad 10's common/paths.cpp). Windows:
    share\\kicad of the first install that has one (KiCad's stock data beside bin). Not confirmed in a
    run off Linux."""
    linux = not (_windows() or _mac())
    stock = kicad_share()

    def pick(via: str | None, kicad: str, name: str) -> Path:
        if via is not None and via in os.environ:
            return Path(os.environ[via])
        if kicad in os.environ and (not linux or name == "3dmodels"):
            return Path(os.environ[kicad])
        return stock / name

    return {
        "symbols": pick("KICAD_SYMBOL_DIR", "KICAD10_SYMBOL_DIR", "symbols"),
        "footprints": pick("KICAD_FOOTPRINT_DIR", "KICAD10_FOOTPRINT_DIR", "footprints"),
        "3dmodels": pick(None, "KICAD10_3DMODEL_DIR", "3dmodels"),
    }


def awt_lib(java_home: Path | str) -> Path:
    """The AWT library a JVM needs to draw FreeRouting 1.9.0's window.

    Linux: tools/routers.py:49, lib/libawt_xawt.so (the X11 AWT). macOS: OpenJDK builds the Cocoa AWT as
    awt_lwawt and no X11 AWT; Windows: its AWT is `awt` (OpenJDK 21's
    make/modules/java.desktop/lib/Awt2dLibraries.gmk, jdk21u). A JDK on Windows keeps its native
    libraries in bin. Not confirmed in an installed JDK on either."""
    if _windows():
        return Path(java_home) / "bin" / "awt.dll"
    if _mac():
        return Path(java_home) / "lib" / "libawt_lwawt.dylib"
    return Path(java_home) / "lib" / "libawt_xawt.so"


def java_home(java: Path | str) -> Path:
    """The JVM folder of a java program: the folder above its bin, links resolved.

    Linux: tools/routers.py:93. macOS: the same for a JDK's own java and Homebrew's links; Apple's
    /usr/bin/java is a launcher, so its JVM is JAVA_HOME's, else the 1 line /usr/libexec/java_home
    prints. Windows: the same, except Oracle's launchers in a `javapath` folder, whose JVM is
    JAVA_HOME's. Where none is named, the launcher's own folder is returned, and the caller finds no JVM
    there. Not confirmed in a run off Linux."""
    found = Path(java).resolve()
    home = found.parent.parent
    if _mac():
        stub = found == MAC_JAVA_STUB
    elif _windows():
        stub = found.parent.name.lower() == WIN_JAVA_STUBS
    else:
        stub = False
    if not stub:
        return home
    named = os.environ.get("JAVA_HOME")
    if named:
        return Path(named)
    if _mac():
        try:
            done = subprocess.run([str(MAC_JAVA_HOME)], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return home
        lines = done.stdout.strip().splitlines()
        if done.returncode == 0 and len(lines) == 1:
            return Path(lines[0].strip())
    return home


def own_group() -> dict:
    """Popen's keyword arguments that make the child lead a process group of its own, so kill_tree and
    stop_tree reach it and what it starts, and a terminal's Ctrl+C does not.

    Linux and macOS: tools/routers.py:266, start_new_session. Windows ignores start_new_session and
    refuses preexec_fn (Python's subprocess documentation); CREATE_NEW_PROCESS_GROUP makes the group."""
    if _windows():
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", WIN_NEW_GROUP)}
    return {"start_new_session": True}


def stop_tree(proc: subprocess.Popen) -> None:
    """Ask `proc` and what it started to stop, as a terminal's stop does; `proc` was started with
    own_group().

    Linux and macOS: tools/mcpserver.py:498, SIGTERM to the process group; ProcessLookupError when the
    group is gone. Windows: CTRL_BREAK_EVENT to the console process group `proc` leads (Python's
    os.kill), which a Python there gets as SIGBREAK. It needs a console the 2 share: with none it raises
    OSError, and the caller ends the tree with kill_tree. Not confirmed in a run on Windows."""
    if _windows():
        os.kill(proc.pid, getattr(signal, "CTRL_BREAK_EVENT", WIN_CTRL_BREAK))
        return
    os.killpg(proc.pid, signal.SIGTERM)


def kill_tree(proc: subprocess.Popen) -> None:
    """Kill `proc` and every process it started.

    Linux and macOS: tools/routers.py:273, SIGKILL to the process group; the caller starts `proc` with
    start_new_session=True so that it leads 1. Windows has neither killpg nor SIGKILL (Python's os and
    signal documentation): `taskkill /T /F` ends the tree (Microsoft's taskkill reference), and where it
    cannot run or fails, Popen.kill() ends `proc` alone. Not confirmed in a run on Windows."""
    if not _windows():
        os.killpg(proc.pid, signal.SIGKILL)
        return
    try:
        done = subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, text=True, timeout=60
        )
    except (OSError, subprocess.TimeoutExpired):
        proc.kill()
        return
    if done.returncode != 0:
        proc.kill()


def stop_signals() -> tuple[int, ...]:
    """The signals by which a host stops a run: a run passes each to its engines.

    Linux and macOS: tools/enginelock.py:466, SIGTERM and SIGHUP. Windows has no SIGHUP; Python there
    handles SIGTERM and SIGBREAK (Python's signal documentation), and Ctrl+Break reaches a console
    process group as SIGBREAK. A signal this Python lacks is left out."""
    names = ("SIGTERM", "SIGBREAK") if _windows() else ("SIGTERM", "SIGHUP")
    return tuple(getattr(signal, name) for name in names if hasattr(signal, name))


def shell_word(word: str) -> str:
    """`word` quoted as 1 word of a command a person pastes into the system's shell; a plain word or
    path stays as written, so Linux's commands are today's.

    Linux and macOS: sh's quoting (shlex.quote); macOS's default root holds "Application Support".
    Windows: double quotes where needed (subprocess.list2cmdline), as cmd.exe and PowerShell take them;
    a user folder can hold a space. Not confirmed in a run off Linux."""
    if _windows():
        return subprocess.list2cmdline([word])
    return shlex.quote(word)


def signal_ends_reads() -> bool:
    """Whether a signal ends a read that blocks the main thread, so Python runs its handler at once.

    Linux and macOS: yes, the read returns EINTR (tools/mcpserver.py reads stdin on the main thread at
    e702b47). Windows: no. The system runs a console control handler (Ctrl+C, Ctrl+Break) on a thread of
    its own, a read of a pipe has no EINTR, and Python runs the handler only when the read returns
    (Python's signal documentation). A program that must stop on a signal reads on another thread there.
    Not confirmed in a run on Windows."""
    return not _windows()


def installer_command(src: Path | str) -> str:
    """The command line that installs the toolchain from the checkout at `src`, as `next` prints it.

    Linux: tools/guide.py:834, `sudo <src>/install.sh`. macOS: install-macos.sh, which asks before it
    uses sudo itself (winmac plan, piece E). Windows: install.ps1 run by Windows PowerShell, which every
    Windows 10 and 11 has (winmac plan, piece F2); the path is in double quotes, which cmd.exe and
    PowerShell both read and which no Windows file name holds. Both scripts sit at the checkout's root;
    neither has run on its system yet."""
    if _windows():
        script = str(src).rstrip("\\/") + "\\install.ps1"
        return f'powershell -NoProfile -ExecutionPolicy Bypass -File "{script}"'
    if _mac():
        return shlex.quote(f"{src}/install-macos.sh")
    return f"sudo {Path(src) / 'install.sh'}"


def program_name(word: str, known: Iterable[str] = ()) -> str:
    """The name of the program a command's first word starts, as a list of names such as `known` holds.

    Linux and macOS: the last part of the path (tools/ci/guard/engine_watch.py:93). Windows: the last part
    after `\\` or `/`, less an extension PATHEXT names (`.exe`, `.cmd`), and a name of `known` matches in
    any case, as Windows' names do (Microsoft's `where` and PATHEXT references):
    `C:\\KiCad\\bin\\KICAD-CLI.EXE` is `kicad-cli`. Not confirmed in a run on Windows."""
    if not _windows():
        return os.path.basename(word)
    import ntpath

    name = ntpath.basename(word)
    stem, ext = ntpath.splitext(name)
    exts = os.environ.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD"
    if ext and ext.lower() in {e.strip().lower() for e in exts.split(";") if e.strip()}:
        name = stem
    return next((k for k in known if k.lower() == name.lower()), name)


def write_text(path: Path | str, text: str) -> int:
    """Write `text` to `path` as UTF-8 with "\\n" line ends on every system; the count of characters.

    newline="\\n" turns off the translation to os.linesep that Windows does by default, and the encoding
    does not follow the locale (Python's `open`). On Linux the bytes are those of today's writes, which
    rest on a UTF-8 locale."""
    return Path(path).write_text(text, encoding="utf-8", newline="\n")


# The byte msvcrt.locking locks on Windows. Windows enforces a lock on reads too (LockFileEx: an
# exclusive lock "denies all other processes both read and write access"), so the lock sits past any
# text the engine lock writes, where it stops no reader. Locking past the end of a file is allowed
# ("Locking a region that goes beyond the current end-of-file position is not an error", LockFileEx).
WIN_LOCK_AT = 1 << 30


def flock_files() -> bool:
    """True where the engine lock's file lock is flock(2), on Linux and macOS.

    There, a lock belongs to the open file, which a child that inherits the descriptor shares (Linux
    `man 2 flock`; BSD flock on macOS), and an open file can be renamed or removed. On Windows neither
    holds: a lock of msvcrt.locking belongs to the handle and process that took it, and a file that
    Python's os.open opened (no FILE_SHARE_DELETE) can be neither renamed nor removed until it is closed
    (CreateFileW, FILE_SHARE_DELETE). Not confirmed in a run on Windows."""
    return not _windows()


def user_id() -> int | None:
    """The user's id that the lock folder must belong to; None on Windows, which has no os.getuid
    (Python's os documentation) and whose default lock folder is under the user's own %LOCALAPPDATA%.

    Linux and macOS: tools/enginelock.py:153."""
    return None if _windows() else os.getuid()


def lock_file(fd: int, wait: bool = False) -> bool:
    """Take the exclusive lock on the open file `fd`: True once taken, False when another holds it and
    `wait` is False. `wait` waits as long as it takes.

    Linux and macOS: tools/enginelock.py:197, :408 and :421, flock(LOCK_EX), with LOCK_NB unless it
    waits. Windows: msvcrt.locking of 1 byte at WIN_LOCK_AT with LK_NBLCK, tried again every 0.01 s when
    it waits: LK_LOCK gives up after 10 tries 1 s apart (Python's msvcrt documentation). A lock held by
    another raises OSError with EACCES (the CRT's _locking); any other error is raised. The system frees
    the lock when the process ends (LockFileEx). Not confirmed in a run on Windows."""
    if not _windows():
        import fcntl

        try:
            fcntl.flock(fd, fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True
    import msvcrt

    while True:
        os.lseek(fd, WIN_LOCK_AT, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EDEADLK):
                raise
            if not wait:
                return False
        time.sleep(0.01)


def unlock_file(fd: int) -> None:
    """Free the lock `lock_file` took, before `fd` is closed.

    Linux and macOS: nothing; close(2) drops a flock at once, as tools/enginelock.py does today.
    Windows: msvcrt.locking with LK_UNLCK on the same byte; Windows frees the lock of a closed handle
    only at a time that "depends upon available system resources" (LockFileEx). Not confirmed in a run."""
    if not _windows():
        return
    import msvcrt

    os.lseek(fd, WIN_LOCK_AT, os.SEEK_SET)
    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
