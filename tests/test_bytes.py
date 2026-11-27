"""Byte parity: a design writes the same bytes on Windows as on Linux, and what Via reads back from an
engine, or links for one, does not rest on Linux.

Linux cannot be Windows, so each test stands in for 1 of its ways and runs the real code under it:
- Windows' text files: Python's own `_pyio.open` with `os.linesep` set to CRLF, which is what the C `open`
  does on Windows (`newline=None` writes `os.linesep` for each "\\n");
- Windows' locale: `subprocess._text_encoding` answering cp1252, the code page of a Western Windows;
- a Windows user without Developer Mode: `os.symlink` raising OSError, as it does there;
- Windows paths: PureWindowsPath, which Linux can make.
A Git checkout with core.autocrlf=true (Git for Windows' default) is run for real: Git behaves the same
on Linux.
"""

from __future__ import annotations

import _pyio
import builtins
import csv
import hashlib
import importlib.machinery
import io
import os
import shutil
import subprocess
import sys
import types
from pathlib import Path, PureWindowsPath

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
# A committed fixture with no pour: generating it starts no engine. It reads KiCad's symbol library.
FIXTURE = ROOT / "tests" / "boards" / "pass-copper-strip"
sys.path.insert(0, str(ROOT / "tools"))
import kicadgen  # noqa: E402

needs_symbols = pytest.mark.skipif(
    not (kicadgen.SYMBOL_DIR / "Device.kicad_sym").is_file(), reason="KiCad's symbol library is absent"
)


def load_cli():
    loader = importlib.machinery.SourceFileLoader("workcenter_cli_bytes", str(CLI))
    module = types.ModuleType("workcenter_cli_bytes")
    module.__file__ = str(CLI)
    sys.modules[module.__name__] = module  # dataclasses look the defining module up here
    loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cli():
    return load_cli()


@pytest.fixture
def crlf(monkeypatch):
    """Text files as Windows writes them: every "\\n" written with newline=None becomes CRLF."""
    monkeypatch.setattr(os, "linesep", "\r\n")
    monkeypatch.setattr(io, "open", _pyio.open)
    monkeypatch.setattr(builtins, "open", _pyio.open)


def test_the_stand_in_writes_crlf_as_windows_does(crlf, tmp_path):
    """Without this, the tests below would prove nothing: a plain write gets CRLF under the stand-in."""
    (tmp_path / "plain.txt").write_text("a\nb\n", encoding="utf-8")
    assert (tmp_path / "plain.txt").read_bytes() == b"a\r\nb\r\n"


def tree(folder: Path) -> dict[str, bytes]:
    found = sorted(p for p in folder.rglob("*") if p.is_file())
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in found}


@needs_symbols
def test_a_design_writes_the_same_bytes_with_crlf_line_ends(cli, tmp_path, monkeypatch):
    """Design.write on Linux and under the Windows stand-in: every file, byte for byte."""
    design = kicadgen.load_design(FIXTURE / "design.py")
    design.write(tmp_path / "linux")
    with monkeypatch.context() as patch:
        patch.setattr(os, "linesep", "\r\n")
        patch.setattr(io, "open", _pyio.open)
        patch.setattr(builtins, "open", _pyio.open)
        kicadgen.load_design(FIXTURE / "design.py").write(tmp_path / "windows")
    linux, windows = tree(tmp_path / "linux"), tree(tmp_path / "windows")
    assert len(linux) >= 3 and linux.keys() == windows.keys()
    assert [name for name in linux if linux[name] != windows[name]] == []
    assert not [name for name, data in windows.items() if b"\r\n" in data]


@needs_symbols
def test_design_check_holds_on_a_committed_fixture_with_crlf_line_ends(cli, crlf, capsys):
    """`design --check` regenerates the project and compares it with the committed files: under the
    stand-in it still finds them the same, so a Windows run agrees with Linux."""
    code = cli.main(["design", str(FIXTURE / "design.py"), "--check"])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "differs" not in out and out.count("check: same") >= 2


def test_run_reads_an_engines_output_as_utf8_whatever_the_locale(cli, monkeypatch):
    """ngspice and kicad-cli print UTF-8 (a part's value in ohms, a path with an accent). On a Western
    Windows the locale's code page is cp1252, and `text=True` alone would read "Ω" as "Î©"."""
    monkeypatch.setattr(subprocess, "_text_encoding", lambda: "cp1252")
    said = "R1 = 10 kΩ, µ\r\n"
    proc = cli.run([sys.executable, "-c", f"import sys; sys.stdout.buffer.write({said.encode()!r})"])
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "R1 = 10 kΩ, µ\n"


def test_run_keeps_a_byte_that_is_no_utf8_as_a_replacement(cli):
    proc = cli.run([sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'ok \\xff')"])
    assert proc.stdout == "ok \ufffd"


def deck_folder(tmp_path: Path) -> tuple[Path, Path]:
    folder = tmp_path / "sim"
    (folder / "stim").mkdir(parents=True)
    (folder / "d.cir").write_text("* d\n.end\n", encoding="utf-8")
    (folder / "model.lib").write_text(".model D D\n", encoding="utf-8")
    (folder / "stim" / "pulse.txt").write_text("0 0\n1 5\n", encoding="utf-8")
    where = tmp_path / "run"
    where.mkdir()
    return folder / "d.cir", where


def refuse(*args, **kwargs):
    raise OSError(1314, "A required privilege is not held by the client")


def test_link_siblings_links_by_symlink_where_it_can(cli, tmp_path):
    try:
        os.symlink(tmp_path, tmp_path / "probe")
    except OSError:
        pytest.skip("this system refuses symlinks to this user (Windows without Developer Mode)")
    deck, where = deck_folder(tmp_path)
    cli.link_siblings(deck, where)
    assert (where / "model.lib").is_symlink() and (where / "stim" / "pulse.txt").is_symlink()
    assert (where / "stim").is_dir() and not (where / "stim").is_symlink()
    assert not (where / "d.cir").exists()


def test_link_siblings_falls_back_to_a_hard_link_when_symlink_is_refused(cli, tmp_path, monkeypatch):
    """Windows refuses os.symlink to a user without Developer Mode (Python's os.symlink documentation)."""
    deck, where = deck_folder(tmp_path)
    monkeypatch.setattr(os, "symlink", refuse)
    cli.link_siblings(deck, where)
    for name in ("model.lib", "stim/pulse.txt"):
        assert not (where / name).is_symlink()
        assert os.path.samefile(where / name, deck.parent / name), name
    assert (where / "stim").is_dir()


def test_link_siblings_copies_when_neither_link_can_be_made(cli, tmp_path, monkeypatch):
    """A hard link fails across drives and on a file system without them (FAT)."""
    deck, where = deck_folder(tmp_path)
    monkeypatch.setattr(os, "symlink", refuse)
    monkeypatch.setattr(os, "link", refuse)
    cli.link_siblings(deck, where)
    for name in ("model.lib", "stim/pulse.txt"):
        assert not os.path.samefile(where / name, deck.parent / name), name
        assert (where / name).read_bytes() == (deck.parent / name).read_bytes()


def save_as_an_editor_does(path: Path, data: bytes) -> None:
    """A new file, then os.replace: the saved file is a new one, so a hard link to the old one keeps
    the old bytes."""
    fresh = path.with_name(path.name + ".new")
    fresh.write_bytes(data)
    os.replace(fresh, path)


@pytest.mark.parametrize("refused", [("symlink",), ("symlink", "link")], ids=["hard link", "copy"])
def test_a_second_run_reads_the_siblings_as_they_are_now(cli, tmp_path, monkeypatch, refused):
    """The run folder is kept between runs (model_rows makes it with exist_ok). A hard link or a copy
    holds the bytes of the run that made it, so each run makes it again: a stimulus saved between 2
    runs, and a file added to a sibling folder, reach the second run. Review finding F1."""
    deck, where = deck_folder(tmp_path)
    for name in refused:
        monkeypatch.setattr(os, name, refuse)
    cli.link_siblings(deck, where)
    save_as_an_editor_does(deck.parent / "model.lib", b".model D D(IS=1n)\n")
    save_as_an_editor_does(deck.parent / "stim" / "pulse.txt", b"0 0\n1 3.3\n")
    (deck.parent / "stim" / "added.txt").write_bytes(b"new\n")
    cli.link_siblings(deck, where)
    for name in ("model.lib", "stim/pulse.txt", "stim/added.txt"):
        assert (where / name).read_bytes() == (deck.parent / name).read_bytes(), name


def test_a_symlink_to_the_source_is_kept_from_run_to_run(cli, tmp_path):
    """Linux as before: a symlink follows its source, so the second run leaves it as it is."""
    deck, where = deck_folder(tmp_path)
    cli.link_siblings(deck, where)
    if not (where / "model.lib").is_symlink():
        pytest.skip("this system refuses symlinks to this user")
    made = (where / "model.lib").lstat()
    cli.link_siblings(deck, where)
    assert (where / "model.lib").lstat().st_ino == made.st_ino


@pytest.mark.parametrize("refused", [(), ("symlink",)], ids=["linux", "windows"])
def test_a_dangling_symlink_in_the_run_folder_is_never_written_through(cli, tmp_path, monkeypatch, refused):
    """A run folder copied with `cp -a` keeps a symlink into another version's sim/, whose file was
    then deleted. The link is made again to the deck's own file; nothing is written into the other
    folder. At 3c1a1c3 it raised FileExistsError; at 49d60db the copy followed the link and wrote
    there. Review finding F3."""
    deck, where = deck_folder(tmp_path)
    other = tmp_path / "v0.16" / "sim" / "model.lib"
    other.parent.mkdir(parents=True)
    try:
        os.symlink(other, where / "model.lib")
    except OSError:
        pytest.skip("this system refuses symlinks to this user")
    for name in refused:
        monkeypatch.setattr(os, name, refuse)
    cli.link_siblings(deck, where)
    assert not os.path.lexists(other)
    assert (where / "model.lib").read_bytes() == (deck.parent / "model.lib").read_bytes()


def test_link_file_never_copies_through_a_name_that_is_taken(cli, tmp_path):
    """FileExistsError is no refusal of a symlink: link_file raises it, and writes nowhere."""
    src = tmp_path / "src.txt"
    src.write_bytes(b"mine\n")
    elsewhere = tmp_path / "elsewhere.txt"
    try:
        os.symlink(elsewhere, tmp_path / "dst.txt")
    except OSError:
        pytest.skip("this system refuses symlinks to this user")
    with pytest.raises(FileExistsError):
        cli.link_file(src, tmp_path / "dst.txt")
    assert not os.path.lexists(elsewhere)


def test_a_run_deck_names_its_models_with_forward_slashes(cli, tmp_path, monkeypatch):
    """ngspice reads `.include "C:/..."` on every system; a backslash is an escape in some of its
    readers (not confirmed in a run on Windows). The deck written for the run holds `/` alone."""
    library = tmp_path / "library"
    library.mkdir()
    model = library / "m.lib"
    model.write_text(".model D D\n", encoding="utf-8")
    with (library / "sources.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(cli.SOURCES_HEADER)
        row = {"MPN": "D1", "Kind": "spice", "File": "m.lib", "SHA256": cli.file_sha256(model)}
        writer.writerow([row.get(name, "") for name in cli.SOURCES_HEADER])
    deck = tmp_path / "board" / "sim" / "d.cir"
    deck.parent.mkdir(parents=True)
    deck.write_text('* d\n.include "../../library/m.lib"\n.end\n', encoding="utf-8")
    windows = PureWindowsPath("C:\\Users\\Ada\\board\\library\\m.lib")
    monkeypatch.setattr(cli, "prepared_model", lambda row, path, work: windows)
    models, problems, _, run_deck = cli.model_rows(deck, library / "sources.csv", tmp_path / "run")
    assert problems == [] and run_deck is not None
    text = run_deck.read_text(encoding="utf-8")
    assert '.include "C:/Users/Ada/board/library/m.lib"' in text and "\\" not in text


def test_a_run_deck_and_its_spiceinit_are_written_with_lf(cli, tmp_path, crlf):
    library = tmp_path / "library"
    library.mkdir()
    model = library / "m.lib"
    model.write_bytes(b".model D D\n")
    digest = hashlib.sha256(model.read_bytes()).hexdigest()
    head = ",".join(cli.SOURCES_HEADER)
    cells = {"MPN": "D1", "Kind": "spice", "File": "m.lib", "Ngspice": "ps", "SHA256": digest}
    (library / "sources.csv").write_bytes(
        (head + "\n" + ",".join(cells.get(n, "") for n in cli.SOURCES_HEADER) + "\n").encode()
    )
    deck = tmp_path / "board" / "sim" / "d.cir"
    deck.parent.mkdir(parents=True)
    deck.write_bytes(b'* d\n.include "../../library/m.lib"\n.end\n')
    _, problems, _, run_deck = cli.model_rows(deck, library / "sources.csv", tmp_path / "run")
    assert problems == [] and b"\r" not in run_deck.read_bytes()
    assert (tmp_path / "run" / ".spiceinit").read_bytes() == b"set ngbehavior=ps\n"


# ------------------------------------------------------------------ .gitattributes


def git(*args: str, cwd: Path) -> str:
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True, env=env)
    return proc.stdout


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_a_checkout_with_autocrlf_holds_the_same_bytes_as_the_commit(tmp_path):
    """Git for Windows' installer sets core.autocrlf=true. With the repository's .gitattributes, a
    checkout under it writes every file as committed: an LF file stays LF, a maker's CRLF model stays
    CRLF (its SHA256 row holds), and a binary file is untouched."""
    files = {
        ".gitattributes": (ROOT / ".gitattributes").read_bytes(),
        "install.sh": b"#!/bin/bash\necho ok\n",
        "board.kicad_sch": b"(kicad_sch\n  (version 20250114)\n)\n",
        "library/maker.lib": b"* a maker's model\r\n.model D D\r\n",
        "image.png": b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
    }
    origin = tmp_path / "origin"
    for name, data in files.items():
        (origin / name).parent.mkdir(parents=True, exist_ok=True)
        (origin / name).write_bytes(data)
    git("init", "-q", "-b", "main", cwd=origin)
    git("add", ".", cwd=origin)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "files", cwd=origin)
    assert "crlf" not in git("ls-files", "--eol", "install.sh", cwd=origin).split()[0]
    git("-c", "core.autocrlf=true", "clone", "-q", str(origin), "windows", cwd=tmp_path)
    copy = tmp_path / "windows"
    assert {name: (copy / name).read_bytes() for name in files} == files


def test_the_attributes_turn_every_conversion_off_but_for_code():
    """`* -text`: Git converts no file. `text=auto eol=lf` was the other choice; it would store the files
    committed with CRLF (makers' models among them) again as LF on their next change. Code is the
    exception: Python and shell files are stored LF, whatever an editor on Windows saves."""
    lines = [ln for ln in (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert [ln for ln in lines if not ln.startswith("#")] == [
        "* -text",
        "*.py text eol=lf",
        "*.sh text eol=lf",
        "tools/workcenter text eol=lf",
    ]


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_code_saved_with_crlf_on_windows_is_committed_with_lf(tmp_path):
    """An editor on Windows saves CRLF into a .py or .sh file. Under `* -text` alone Git would commit
    the CR, and bash on Linux stops at it. Review finding F8."""
    origin = tmp_path / "origin"
    (origin / "tools").mkdir(parents=True)
    (origin / ".gitattributes").write_bytes((ROOT / ".gitattributes").read_bytes())
    saved = {
        "install.sh": b"#!/bin/bash\r\necho ok\r\n",
        "tools/a.py": b"print(1)\r\n",
        "tools/workcenter": b"#!/usr/bin/env python3\r\n",
        "library/maker.lib": b"* a maker's model\r\n",
    }
    for name, data in saved.items():
        (origin / name).parent.mkdir(parents=True, exist_ok=True)
        (origin / name).write_bytes(data)
    git("init", "-q", "-b", "main", cwd=origin)
    git("-c", "core.autocrlf=true", "add", ".", cwd=origin)
    listed = git("ls-files", "--eol", cwd=origin).splitlines()
    eol = {line.split("\t")[-1]: line.split()[0] for line in listed}
    assert {name: eol[name] for name in saved} == {
        "install.sh": "i/lf",
        "tools/a.py": "i/lf",
        "tools/workcenter": "i/lf",
        "library/maker.lib": "i/crlf",
    }


def test_no_committed_code_holds_crlf():
    """The 15 files committed with CRLF are tables and makers' models; no .py or .sh file is one."""
    if not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    listed = git("ls-files", "--eol", cwd=ROOT).splitlines()
    crlf = [line.split("\t")[-1] for line in listed if line.split()[0] == "i/crlf"]
    assert [name for name in crlf if name.endswith((".py", ".sh")) or name == "tools/workcenter"] == []


# ------------------------------------------------------------------ a board project's checkout


@needs_symbols
@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_a_project_made_by_new_checks_the_same_after_a_windows_checkout(cli, tmp_path, capsys):
    """`new` writes the project's .gitattributes (`* -text`), so Git for Windows' core.autocrlf=true
    checks its generated files out as committed, and `design --check` holds there. Review finding F2."""
    board = tmp_path / "board"
    assert cli.main(["new", str(board)]) == 0
    template = ROOT / "templates" / "project" / "gitattributes"
    assert (board / ".gitattributes").read_bytes() == template.read_bytes()
    assert cli.main(["design", str(board / "design.py")]) == 0
    git("init", "-q", "-b", "main", cwd=board)
    git("add", ".", cwd=board)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "board", cwd=board)
    git("-c", "core.autocrlf=true", "clone", "-q", str(board), "windows", cwd=tmp_path)
    clone = tmp_path / "windows"
    assert not [p.name for p in clone.glob("*.kicad_*") if b"\r\n" in p.read_bytes()]
    capsys.readouterr()
    assert cli.main(["design", str(clone / "design.py"), "--check"]) == 0, capsys.readouterr().out


@needs_symbols
def test_design_check_names_line_ends_as_the_cause_of_a_crlf_checkout(cli, tmp_path, capsys):
    """A project checked out with CRLF line ends (no .gitattributes, core.autocrlf=true) differs from the
    design in its line ends alone. The check says so and names the fix; it showed `'(end)'` on both
    sides, because a split line hides its CR."""
    copy = tmp_path / FIXTURE.name
    shutil.copytree(FIXTURE, copy)
    shutil.copy(FIXTURE.parent / "copper_strip.py", tmp_path)  # the design file imports it from above
    for path in copy.glob("*.kicad_*"):
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    code = cli.main(["design", str(copy / "design.py"), "--check"])
    out = capsys.readouterr().out
    assert code == 1
    assert "(end)" not in out
    differs = out.count("check: differs")
    assert differs >= 2, out
    assert out.count("line ends: CRLF where design.py writes LF") == differs, out
    assert out.count("write `* -text` in the project's .gitattributes") == differs, out


# ------------------------------------------------------------------ the other writes and reads


def test_symbol_add_writes_the_library_with_lf(crlf, tmp_path):
    lib = tmp_path / "sym" / "Mine.kicad_sym"
    pins = [{"number": "1", "name": "A", "type": "passive", "side": "left"}]
    kicadgen.symbol_add(lib, "One", pins)
    kicadgen.symbol_add(lib, "Two", pins)
    assert b"\r" not in lib.read_bytes()


@needs_symbols
def test_a_routed_and_poured_board_is_written_again_with_lf(crlf, tmp_path, monkeypatch):
    """Design.write's second write of the board, after stitch_zones added vias; the engines are stubbed."""
    design = kicadgen.load_design(FIXTURE / "design.py")
    design.zones, design.segments = [{"net": "GND"}], [("stub",)]
    monkeypatch.setattr(design, "board", lambda: "(kicad_pcb\n\t(stitched)\n)\n")
    monkeypatch.setattr(kicadgen, "fill_zones", lambda pcb: {})
    monkeypatch.setattr(kicadgen, "stitch_zones", lambda design, pcb: (1, []))
    design.write(tmp_path)
    assert (tmp_path / f"{design.name}.kicad_pcb").read_bytes() == b"(kicad_pcb\n\t(stitched)\n)\n"


def test_stitch_zones_writes_the_board_with_lf(crlf, tmp_path, monkeypatch):
    """stitch_zones' own write, each round it adds a via: pcbnew and KiCad are stubbed."""
    pcbnew = types.SimpleNamespace(VECTOR2I_MM=lambda x, y: (x, y))
    monkeypatch.setitem(sys.modules, "pcbnew", pcbnew)
    pieces = [("F.Cu", None, 0, ["R1.1"]), ("B.Cu", None, 0, ["R2.1"])]
    graph = {"pieces": pieces, "components": [[0], [1]]}
    monkeypatch.setattr(kicadgen, "pour_pieces", lambda pcb, net: graph)
    monkeypatch.setattr(kicadgen, "_holes", lambda pcbnew, pcb: [])
    monkeypatch.setattr(kicadgen, "_via_blocker", lambda *args: None)
    monkeypatch.setattr(kicadgen, "_via_spot", lambda *args, **kwargs: (1.0, 2.0))
    monkeypatch.setattr(kicadgen, "fill_zones", lambda pcb: {})
    design = types.SimpleNamespace(
        zones=[{"net": "GND"}],
        pcb_net_name=lambda net: net,
        class_of=lambda net: {"via": 0.6, "via_drill": 0.3},
        pad_boxes=lambda: [],
        copper_names=lambda: ["F.Cu", "B.Cu"],
        vias=[],
        stitches=[],
        board=lambda: "(kicad_pcb\n\t(via)\n)\n",
    )
    pcb = tmp_path / "b.kicad_pcb"
    assert kicadgen.stitch_zones(design, pcb, rounds=1) == (1, [])
    assert pcb.read_bytes() == b"(kicad_pcb\n\t(via)\n)\n"


@pytest.mark.parametrize("order", [False, True], ids=["1 route", "stages"])
def test_route_writes_each_dsn_with_lf(crlf, tmp_path, monkeypatch, order):
    """route() hands the router a DSN it wrote: 1, or 1 per stage. The router is stubbed."""

    def run(dsn, ses, log, *rest):
        ses.write_bytes(b"(session)\n")
        return ""

    engine = types.SimpleNamespace(
        name="stub", absent=lambda: None, run=run, unrouted=lambda text: 0, violations=lambda text: 0
    )
    monkeypatch.setattr(kicadgen.routers, "get", lambda name: engine)
    design = types.SimpleNamespace(
        name="b",
        dsn=lambda *args, **kwargs: "(pcb b\n\t(structure)\n)\n",
        merge_ses=lambda text: (0, 0),
        route_stages=lambda: [("fine", ["A"]), ("rest", ["B"])],
        bare_connections=lambda: 0,
    )
    kicadgen.route(design, tmp_path, order=order)
    written = sorted(tmp_path.glob("*.dsn"))
    assert len(written) == (2 if order else 1)
    assert [p.read_bytes() for p in written] == [b"(pcb b\n\t(structure)\n)\n"] * len(written)


def test_drc_report_reads_kicad_clis_words_as_utf8(tmp_path, monkeypatch):
    """kicad-cli says why it failed in UTF-8; on a Western Windows the locale's code page is cp1252."""
    monkeypatch.setattr(subprocess, "_text_encoding", lambda: "cp1252")
    stub = tmp_path / "kicad-cli"
    said = "R1 = 10 kΩ: no such board µ"
    stub.write_text(
        f"#!{sys.executable}\nimport sys\nsys.stderr.buffer.write({said.encode()!r})\nsys.exit(3)\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    with pytest.raises(RuntimeError) as raised:
        kicadgen.drc_report(tmp_path / "b.kicad_pcb", str(stub))
    assert str(raised.value).endswith(said)


def test_new_writes_every_file_with_lf(cli, crlf, tmp_path, capsys):
    """`new` in this process, under the Windows stand-in: every file it writes holds no CR."""
    board = tmp_path / "board"
    assert cli.main(["new", str(board)]) == 0
    written = [p for p in board.rglob("*") if p.is_file()]
    assert len(written) >= 4 and [p.name for p in written if b"\r" in p.read_bytes()] == []


@pytest.mark.parametrize("stem", ["i2c_rise", "load_step"])
def test_new_deck_copies_byte_for_byte_under_the_stand_in(cli, crlf, tmp_path, stem):
    board = tmp_path / "board"
    assert cli.main(["new", str(board), "--deck", stem]) == 0
    decks = ROOT / "templates" / "project" / "sim"
    for ext in (".cir", ".expect.json"):
        assert (board / "sim" / f"{stem}{ext}").read_bytes() == (decks / f"{stem}{ext}").read_bytes()
