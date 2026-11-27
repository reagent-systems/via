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


def test_the_attributes_turn_every_conversion_off():
    """`* -text`: Git converts no file. `text=auto eol=lf` was the other choice; it would store the files
    committed with CRLF (makers' models among them) again as LF on their next change."""
    lines = [ln for ln in (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert [ln for ln in lines if not ln.startswith("#")] == ["* -text"]
