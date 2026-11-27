"""made_check — the result of Via's gates on a board someone added at made.via.computer, as 1 line of
JSON for .github/workflows/made-check.yml.

    python3 tools/ci/made_check.py BOARD_FOLDER REPORT [EXIT_CODE]

It reads the gates' report (`workcenter gates --report`) and draws the board from its .kicad_pcb with
site/examples.py's draw_board, then prints {"green", "verdict", "report", "facts", "kicad", "picture"}:
`picture` is the drawing gzipped and in base64, left out when it is bigger than the workflow's outputs
take; `kicad` is each board file's path in the folder, for OSH Park's link. With --bundle DIR it also
writes DIR/gerbers.zip: the Gerbers and drill files the gates' EXPORT wrote (build/fab/gerbers/), 1
folder in the zip for each board when there are several, for JLCPCB and PCBWay. A GREEN is green
only as board-gates.yml judges it: the report's GREEN line, and ERC, DRC and EXPORT each with a row
that is not `skip`.

The workflow runs this in a container of its own, with no network, after the board's own code has
run: a file of the board is read as data, and a symlink is not followed out of the board's folder.
"""

from __future__ import annotations

import base64
import gzip
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

REPORT_MOST = 20000
PICTURE_MOST = 600_000  # base64 characters: GitHub keeps 1 MB of a job's outputs


def inside(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except (OSError, ValueError):
        return False


def judged(report: str, code: int) -> tuple[bool, str]:
    """Whether the gates passed, and their verdict line, as board-gates.yml reads a report."""
    line = next((ln.strip() for ln in report.splitlines() if re.match(r"^(GREEN|RED|SKIPPED)\b", ln)), "")
    if not line:
        return False, "The gates wrote no verdict."
    verdict = line.split(" on 20")[0].rstrip(":")
    if not line.startswith("GREEN") or code != 0:
        return False, verdict
    for gate in ("ERC", "DRC", "EXPORT"):
        row = re.search(rf"^\| {gate} \| (\w+) \|", report, re.M)
        if not row:
            return False, f"RED: {gate} has no row in the gates table, so it judged nothing"
        if row.group(1) == "skip":
            return False, f"RED: {gate} was skipped, so it judged nothing"
    return True, verdict


def regular(path: Path, folder: Path) -> bool:
    """A file of the board's own, read as data: not a symlink, and inside the board's folder."""
    return path.is_file() and not path.is_symlink() and inside(path, folder)


def boards(folder: Path) -> list[Path]:
    found = sorted(folder.glob("*.kicad_pcb")) or sorted(folder.glob("*/*.kicad_pcb"))
    return [p for p in found if p.is_file() and not p.is_symlink() and inside(p, folder)][:20]


def drawn(folder: Path) -> tuple[dict, str | None]:
    """The board's facts (parts, layers, area, boards) and its first board's drawing."""
    # site/ on the path only while examples.py is imported: left there, a later `import guide` finds
    # site/guide.py (M296).
    before = list(sys.path)
    sys.path.insert(0, str(ROOT / "site"))
    try:
        from examples import draw_board
    finally:
        sys.path[:] = before

    facts = {"parts": 0, "layers": 0, "area": 0.0, "boards": 0}
    picture = None
    for i, path in enumerate(boards(folder)):
        try:
            board = draw_board(path)
        except Exception:  # noqa: BLE001 - a board's file is the board's own; a bad one draws nothing
            continue
        facts["parts"] += board.parts
        facts["layers"] = max(facts["layers"], board.layers)
        facts["area"] = round(facts["area"] + board.width * board.height, 1)
        facts["boards"] += 1
        if i == 0 or picture is None:
            packed = base64.b64encode(gzip.compress(board.svg.encode("utf-8"), 9)).decode("ascii")
            picture = packed if len(packed) <= PICTURE_MOST else None
    return facts, picture


ZIP_MOST = 4_000_000  # bytes: what the site keeps of 1 zip


def bundle(folder: Path, dest: Path) -> Path | None:
    """The Gerbers and drill files of each board in the folder, in 1 zip: only regular files inside
    the folder, none through a symlink. None when there are none, or the zip is bigger than the site
    keeps."""
    import zipfile

    found = []
    for pcb in boards(folder):
        gerbers = pcb.parent / "build" / "fab" / "gerbers"
        if gerbers.is_dir() and not gerbers.is_symlink() and inside(gerbers, folder):
            files = [f for f in sorted(gerbers.iterdir()) if regular(f, folder)]
            if files:
                found.append((pcb, files))
    if not found:
        return None
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / "gerbers.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for pcb, files in found:
            prefix = f"{pcb.stem}/" if len(found) > 1 else ""
            for f in files:
                z.write(f, prefix + f.name)
    if out.stat().st_size > ZIP_MOST:
        out.unlink()
        return None
    return out


def main(argv: list[str]) -> int:
    args = list(argv)
    dest = None
    if "--bundle" in args:
        at = args.index("--bundle")
        dest = Path(args[at + 1])
        del args[at : at + 2]
    folder = Path(args[1])
    report_path = Path(args[2])
    code = int(args[3]) if len(args) > 3 and args[3].lstrip("-").isdigit() else 1
    report = ""
    if report_path.is_file() and not report_path.is_symlink():
        report = report_path.read_text(encoding="utf-8", errors="replace")
    green, verdict = judged(report, code)
    nothing = {"parts": 0, "layers": 0, "area": 0, "boards": 0}
    facts, picture = drawn(folder) if folder.is_dir() else (nothing, None)
    kicad = [p.relative_to(folder).as_posix() for p in boards(folder)] if folder.is_dir() else []
    out = {"green": green, "verdict": verdict, "report": report[-REPORT_MOST:], "facts": facts}
    out["kicad"] = kicad
    if dest is not None and folder.is_dir():
        bundle(folder, dest)
    if picture:
        out["picture"] = picture
    print(json.dumps(out, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
