"""`workcenter new <dir>`: a board project a user can edit, from Via's template.

It writes the files `workcenter next` and the commands after it read first:

    design.py            templates/project/design.py, with the folder's name and a namespace of its own
    .gitignore           templates/project/gitignore: what the engines and KiCad write
    .gitattributes       templates/project/gitattributes: `* -text`, so Git converts no line end
    parts.csv            the header `procure` and `sources` read (PARTS_COLUMNS)
    library/sources.csv  the header `fetch --row` appends to (SOURCES_HEADER)

A file that is there is kept, and a library/sources.csv that `find_sources(<dir>)` finds above (it
stops at the project's own .git) serves the project. A folder that holds a design (a design file, a
KiCad project or a chip), an empty name, and a path that cannot be written (a file where a folder
goes, or a folder where a file goes) are refused in 1 line; every path is judged before the first
write, so nothing is written. The last line names the next step. No engine runs.

Two more uses, which `next` names so that its commands run alike on Linux, macOS and Windows:
`new <dir> --empty` makes the folder alone (in place of `mkdir -p`), and `new <dir> --deck <template>
[--as <name>]` copies a template deck and its bounds into <dir>/sim/ (in place of `mkdir -p` and `cp`).
Every text is written UTF-8 with LF line ends on every system (tools/hostos.py).

Standard library only, as the CLI is (AGENTS.md invariant 3).
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import hostos  # tools/hostos.py, beside this file

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "project"
# The files that make a folder a project already: `next` answers it, and `new` would write over a design.
DESIGNS = ("design.py", "chip.json", "*.kicad_pro", "*.kicad_sch", "*.kicad_pcb")
# The template's own name and namespace: each is replaced once, or the template changed under `new`.
NAME_LINE = 'name="divider",'
NAMESPACE_RE = re.compile(r'namespace=uuid\.UUID\("[0-9a-f-]{36}"\)')


def board_name(folder: Path) -> str:
    """The folder's name as a design's name: the generated files are `<name>.kicad_*`."""
    return re.sub(r"[^A-Za-z0-9_-]+", "-", folder.name).strip("-_") or "board"


def design_text(name: str, namespace: uuid.UUID) -> str:
    """The template's design file under `name`, with `namespace`."""
    text = (TEMPLATE / "design.py").read_text(encoding="utf-8")
    if text.count(NAME_LINE) != 1 or len(NAMESPACE_RE.findall(text)) != 1:
        raise SystemExit(f"new: {TEMPLATE / 'design.py'} no longer holds 1 {NAME_LINE} and 1 namespace")
    text = text.replace(NAME_LINE, f"name={name!r},".replace("'", '"'))
    return NAMESPACE_RE.sub(f'namespace=uuid.UUID("{namespace}")', text)


def held(folder: Path) -> list[str]:
    """The design files a folder holds already."""
    return sorted(p.name for pattern in DESIGNS for p in folder.glob(pattern))


def blocked(path: Path) -> str | None:
    """Why `path` cannot be written as a file, or None: a folder is there, or the nearest thing above
    it that is there is a file, so no folder can be made for it."""
    if path.is_dir():
        return f"{path} is a folder, where a file goes"
    for above in path.parents:
        if above.exists():
            return None if above.is_dir() else f"{above} is a file, where {path} needs a folder"
    return None


def make_empty(target: Path, quoted: str) -> int:
    """`new --empty`: the folder alone, with the folders above it. `next` names this for a project
    folder that is not there; `mkdir -p` would run in a POSIX shell alone."""
    if target.is_dir():
        print(f"new: {target} is there already; nothing written. Next: workcenter next {quoted}")
        return 0
    why = blocked(target)
    if why:
        print(f"new: {why}; nothing written.")
        return 1
    target.mkdir(parents=True)
    print(f"new: made {target}, empty. Next: workcenter next {quoted}")
    return 0


def copy_deck(target: Path, quoted: str, stem: str, name: str | None) -> int:
    """`new --deck`: a template deck of templates/project/sim/ and its bounds, copied byte for byte into
    the project's sim/ under `name`, else the first name sim/ does not hold (tools/simneeds.py). A
    folder that holds a design takes it: a deck is added to a board. A file is never replaced."""
    import simneeds  # beside this file, on the path the CLI put its tools folder on

    decks = TEMPLATE / "sim"
    known = sorted(p.name.removesuffix(".cir") for p in decks.glob("*.cir"))
    if stem not in known:
        print(f"new: no template deck {stem!r}; the templates are {', '.join(known)}. Nothing written.")
        return 1
    sim = target / "sim"
    name = name or simneeds.free_name(sim, stem)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        print(f"new: --as {name!r}: letters, digits and _ . - only. Nothing written.")
        return 1
    copies = {decks / f"{stem}{ext}": sim / f"{name}{ext}" for ext in (".cir", ".expect.json")}
    for path in copies.values():
        why = f"{path} is there already" if path.exists() else blocked(path)
        if why:
            print(f"new: {why}; nothing written.")
            return 1
    sim.mkdir(parents=True, exist_ok=True)
    for src, dest in copies.items():
        dest.write_bytes(src.read_bytes())
        print(f"wrote {dest}")
    print(f"new: copied the {stem} deck as sim/{name}.cir. Next: fill it, then workcenter gates {quoted}")
    return 0


def cmd_new(args, cli) -> int:
    if not args.dir.strip():
        print("new: the folder's name is empty; name a folder. Nothing written.")
        return 1
    target = Path(args.dir).resolve()
    quoted = hostos.shell_word(args.dir)
    if target.exists() and not target.is_dir():
        print(f"new: {target} is a file; name a folder. Nothing written.")
        return 1
    if args.as_name and not args.deck:
        print("new: --as names the copy of --deck; give --deck too. Nothing written.")
        return 1
    if args.empty:
        return make_empty(target, quoted)
    if args.deck:
        return copy_deck(target, quoted, args.deck, args.as_name)
    there = held(target) if target.is_dir() else []
    if there:
        named = ", ".join(there)
        print(
            f"new: {target} holds a design already ({named}); nothing written. Next: workcenter next {quoted}"
        )
        return 1
    # As the readers find it (`fetch --row`, `sources`): from the project itself, stopping at its .git.
    above = cli.find_sources(target)
    if above == target / "library" / "sources.csv":
        above = None  # the project's own: kept below as any file that is there
    files = {
        "design.py": design_text(board_name(target), uuid.uuid4()),
        ".gitignore": (TEMPLATE / "gitignore").read_text(encoding="utf-8"),
        ".gitattributes": (TEMPLATE / "gitattributes").read_text(encoding="utf-8"),
        "parts.csv": ",".join(cli.PARTS_COLUMNS) + "\n",
    }
    if above is None:
        files["library/sources.csv"] = ",".join(cli.SOURCES_HEADER) + "\n"
    # Every path is judged before the first is written, so a refusal leaves the folder as it was.
    for relative in files:
        path = target / relative
        why = blocked(path) if not path.is_file() else None
        if why:
            print(f"new: {why}; nothing written.")
            return 1
    wrote, kept = [], []
    for relative, text in files.items():
        path = target / relative
        if path.exists():
            kept.append(relative)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        hostos.write_text(path, text)
        wrote.append(relative)
    for relative in wrote:
        print(f"wrote {target / relative}")
    for relative in kept:
        print(f"kept  {target / relative} (it is there already)")
    if above is not None:
        print(f"kept  {above} (the library above serves this project)")
    then = f"Next: edit {quoted}/design.py, then workcenter next {quoted}"
    print(f"new: {len(wrote)} files written, {len(kept)} kept. {then}")
    return 0


def register(sub, cli) -> None:
    """Add `new` to Via's parser."""
    p = sub.add_parser(
        "new",
        help="start a board project in a folder: design.py from the template, .gitignore, .gitattributes, "
        "parts.csv and library/sources.csv with their headers; refuses a folder that holds a design; runs no "
        "engine",
    )
    p.add_argument("dir", help="the project's folder (made when it is not there)")
    only = p.add_mutually_exclusive_group()
    only.add_argument("--empty", action="store_true", help="make the folder alone and write nothing in it")
    only.add_argument(
        "--deck",
        metavar="TEMPLATE",
        help="copy templates/project/sim/TEMPLATE.cir and its .expect.json into the folder's sim/, "
        "under a name sim/ does not hold; a folder that holds a design takes it",
    )
    p.add_argument("--as", dest="as_name", metavar="NAME", help="with --deck: the copy's name (sim/NAME.cir)")
    p.set_defaults(run=lambda a: cmd_new(a, cli))
