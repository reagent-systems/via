"""tools/kicadchild.py: the pour-stitching step that reads KiCad's pcbnew, run as a child process under
KiCad's own Python (tools/hostos.py kicad_python), with a JSON request in and a JSON answer out.

Most tests here run a stand-in in the child's place, so they start no engine: the stand-in writes down
the request kicadgen sends and gives back an answer the test chose. The engine test at the end holds
the real child to the same bytes as the same search run in this process.
"""

from __future__ import annotations

import ast
import importlib.machinery
import importlib.util
import json
import os
import random
import re
import shutil
import subprocess
import sys
import types
import uuid
from pathlib import Path

import pytest
from conftest import engine, engine_absent

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import guide  # noqa: E402
import kicadchild  # noqa: E402
import kicadgen  # noqa: E402

CHILD = ROOT / "tools" / "kicadchild.py"
LIBS = kicadgen.SYMBOL_DIR / "Device.kicad_sym"

# The stand-in: writes each request it gets to request-<n>.json beside itself, and whether Python's
# -s was given to no-user-site-<n>; it answers with the n-th entry of answers.json there. An entry
# {"exit": code, "line": text} exits with that code instead, {"sleep": s} sleeps s seconds first, and
# {"raw": text} puts that text on stdout in place of the answer. KiCad's noise comes first every time.
STAND_IN = """\
import json, sys, time
from pathlib import Path
here = Path(__file__).resolve().parent
n = len(list(here.glob("request-*.json")))
(here / f"request-{n}.json").write_text(sys.stdin.read())
(here / f"no-user-site-{n}").write_text(str(sys.flags.no_user_site))
said = json.loads((here / "answers.json").read_text())[n]
print("Debug: Adding duplicate image handler for 'Windows bitmap file'", file=sys.stderr)
time.sleep(said.get("sleep", 0))
if "exit" in said:
    print("an earlier line of the child's", file=sys.stderr)
    print(said["line"], file=sys.stderr)
    sys.exit(said["exit"])
print("a line of the child's own", file=sys.stderr)
print(said["raw"] if "raw" in said else json.dumps(said))
"""


def stand_in(tmp_path: Path, monkeypatch, answers: list) -> Path:
    """Put the stand-in in the child's place, run by this Python; returns its folder."""
    folder = tmp_path / "child"
    folder.mkdir()
    (folder / "child.py").write_text(STAND_IN, encoding="utf-8")
    (folder / "answers.json").write_text(json.dumps(answers), encoding="utf-8")
    monkeypatch.setattr(kicadchild, "CHILD", folder / "child.py")
    monkeypatch.setattr(kicadchild, "python", lambda: sys.executable)
    return folder


def requests(folder: Path) -> list[dict]:
    return [
        json.loads((folder / f"request-{n}.json").read_text(encoding="utf-8"))
        for n in range(len(list(folder.glob("request-*.json"))))
    ]


def bare_board() -> kicadgen.Design:
    """A board with no parts (no KiCad library is read): a ground pour on both faces, 2 tracks of
    another net and a keepout. Its board text is the list of its vias: no net of a track has a pad, so
    the real writer would refuse it, and these tests read only what stitch_zones writes."""
    d = kicadgen.Design(
        name="bare",
        namespace=uuid.UUID("1b2c3d4e-0000-4000-8000-000000000077"),
        outline=(100.0, 100.0, 120.0, 110.0),
    )
    d.power_nets = {"GND": "GND"}
    d.zone("GND", layers=("F.Cu", "B.Cu"), connect="solid")
    d.track("OUT", [(102.0, 105.0), (118.0, 105.0)], "F.Cu")
    d.track("OUT", [(110.0, 101.0), (110.0, 109.0)], "B.Cu", width=0.4)
    d.keepout(kicadgen.Design.circle(104.0, 103.0, 1.0), layers=("F.Cu",), name="shell")
    d.board = lambda: f"(vias {d.vias!r})\n"
    return d


# ------------------------------------------------------------------------ the child's own file


def test_the_child_is_python_3_9_and_imports_only_the_standard_library_and_pcbnew():
    """KiCad 10 bundles Python 3.9.13 on macOS (kicad-mac-builder 10.0 CMakeLists.txt) and 3.11.5 on
    Windows (KiCad's vcpkg.json at 10.0.8). The child's half must parse there and import nothing of
    Via's; the parent's half (python, run) may import hostos, inside the function."""
    source = CHILD.read_text(encoding="utf-8")
    tree = ast.parse(source, feature_version=(3, 9))
    stdlib = set(sys.stdlib_module_names) | {"__future__"}
    parent = {"python", "run"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            assert not any(k.arg == "strict" for k in node.keywords), ast.unparse(
                node
            )  # zip(strict=) is 3.10
        if isinstance(node, ast.Match):
            pytest.fail("a match statement is Python 3.10")
    for fn in [None, *[n for n in tree.body if isinstance(n, ast.FunctionDef)]]:
        body = tree.body if fn is None else fn.body
        for stmt in ast.walk(ast.Module(body=body, type_ignores=[])) if fn else body:
            names = []
            if isinstance(stmt, ast.Import):
                names = [a.name.split(".")[0] for a in stmt.names]
            elif isinstance(stmt, ast.ImportFrom):
                names = [(stmt.module or "").split(".")[0]]
            allowed = stdlib | {"pcbnew"} | ({"hostos"} if fn is not None and fn.name in parent else set())
            assert set(names) <= allowed, (fn.name if fn else "module", names)
    # Every annotation stays a string: `str | None` is no expression Python 3.9 evaluates.
    assert "from __future__ import annotations" in source


@pytest.mark.skipif(shutil.which("python3.11") is None, reason="no Python 3.11 here")
def test_the_child_compiles_under_python_3_11():
    """Windows' KiCad Python is 3.11 (vcpkg.json at 10.0.8): a real compile, not only the parser's
    feature version."""
    proc = subprocess.run(
        [
            shutil.which("python3.11"),
            "-I",
            "-c",
            "import sys; compile(open(sys.argv[1]).read(), 'c', 'exec')",
            str(CHILD),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def run_child(tmp_path: Path, request: bytes, op: str = "stitch", pcbnew: str | None = None):
    """The real child file, copied beside a stand-in pcbnew module when one is given, run with no
    PYTHONPATH: the import of pcbnew finds the stand-in, never KiCad's."""
    folder = tmp_path / "real"
    folder.mkdir()
    shutil.copy(CHILD, folder / "kicadchild.py")
    if pcbnew is not None:
        (folder / "pcbnew.py").write_text(pcbnew, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    return subprocess.run(
        [sys.executable, "-s", str(folder / "kicadchild.py"), op],
        input=request,
        capture_output=True,
        env=env,
        check=False,
    )


def test_the_child_refuses_in_1_line_when_pcbnew_does_not_import(tmp_path):
    proc = run_child(
        tmp_path,
        json.dumps({"contract": kicadchild.CONTRACT, "pcb": "x", "nets": [], "copper": []}).encode(),
        pcbnew="raise ImportError('libkicad_3dsg.so.10.0: cannot open shared object file')\n",
    )
    lines = proc.stderr.decode().splitlines()
    assert proc.returncode == kicadchild.EXIT_NO_PCBNEW
    assert proc.stdout == b""
    assert len(lines) == 1, lines
    assert lines[0].startswith("kicadchild: pcbnew does not import in ")
    assert lines[0].endswith(": libkicad_3dsg.so.10.0: cannot open shared object file")


@pytest.mark.parametrize(
    ("request_bytes", "op", "says"),
    [
        (b'{"contract": 99}', "stitch", "kicadchild: the request's contract is 99; this child answers 1"),
        (b"not json", "stitch", "kicadchild: the request is not JSON: "),
        (b'{"contract": 1}', "fill", "kicadchild: usage: kicadchild.py {stitch} < request.json"),
    ],
)
def test_the_child_refuses_a_request_it_cannot_read_before_it_loads_pcbnew(tmp_path, request_bytes, op, says):
    proc = run_child(tmp_path, request_bytes, op, pcbnew="raise SystemExit('pcbnew was loaded')\n")
    lines = proc.stderr.decode().splitlines()
    assert proc.returncode == kicadchild.EXIT_REFUSED
    assert len(lines) == 1 and lines[0].startswith(says), lines


def test_the_child_answers_on_stdout_alone_whatever_pcbnew_prints(tmp_path):
    """KiCad's libraries print while they load; stdout carries the answer and nothing else."""
    noisy = "import os\nos.write(1, b'loading 3D plugins\\n')\nprint('pcbnew says hello')\n"
    proc = run_child(
        tmp_path, json.dumps({"contract": 1, "pcb": "x", "nets": [], "copper": []}).encode(), pcbnew=noisy
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {"stitches": [], "left": [], "contract": 1}
    assert b"pcbnew says hello" in proc.stderr and b"loading 3D plugins" in proc.stderr


# --------------------------------------------------------------- the contract, from kicadgen's side


def test_stitch_zones_sends_the_design_and_applies_the_answer(tmp_path, monkeypatch, capsys):
    d = bare_board()
    filled = []
    monkeypatch.setattr(kicadgen, "fill_zones", lambda pcb, *a: filled.append(pcb) or {})
    folder = stand_in(
        tmp_path,
        monkeypatch,
        [
            {
                "contract": 1,
                "stitches": [
                    {
                        "net": "GND",
                        "at": [104.5, 107.25],
                        "layer": "F.Cu",
                        "to": "B.Cu",
                        "island": ["J1.3", "via@104.00,107.00"],
                    }
                ],
                "left": [["R9.2"]],
            },
            {"contract": 1, "stitches": [], "left": [["R9.2"]]},
        ],
    )
    pcb = tmp_path / "bare.kicad_pcb"
    pcb.write_text("(kicad_pcb)\n", encoding="utf-8")
    vias = list(d.vias)
    added, left = kicadgen.stitch_zones(d, pcb)
    assert (added, left) == (1, [["R9.2"]])
    spec = d.class_of("GND")
    assert d.vias == [*vias, ("GND", (104.5, 107.25), spec["via"], spec["via_drill"])]
    assert d.stitches == [
        {"net": "GND", "at": (104.5, 107.25), "layer": "F.Cu", "to": "B.Cu", "pads": ["J1.3"]}
    ]
    # The round that added a via wrote the board with it and had KiCad fill it; the next found none.
    assert filled == [pcb] and "(104.5, 107.25)" in pcb.read_text(encoding="utf-8")
    first, second = requests(folder)
    assert first == second  # the via is in the written board, not in the request
    r, drill = spec["via"] / 2, spec["via_drill"]
    holes = d.hole_clearances()
    assert first == {
        "contract": kicadchild.CONTRACT,
        "pcb": str(pcb),
        "copper": ["F.Cu", "B.Cu"],
        "nets": [
            {
                "net": "GND",
                "size": spec["via"],
                "drill": drill,
                "reach": {ly: d.via_reach(r, drill, ly, d.clearance, holes) for ly in ("F.Cu", "B.Cu")},
            }
        ],
        "keepouts": [
            {"name": "shell", "polygon": [list(p) for p in d.keepouts[0]["polygon"]], "copper": True}
        ],
        "segments": [[n, list(a), list(b), w, ly] for n, a, b, w, ly in d.segments],
        "boxes": [],
    }
    err = capsys.readouterr().err.splitlines()
    assert err == ["a line of the child's own", "a line of the child's own"]  # KiCad's noise is left out
    # -s: the user's own site folder never reaches KiCad's Python.
    assert [(folder / f"no-user-site-{n}").read_text() for n in (0, 1)] == ["1", "1"]


def test_stitch_zones_keeps_the_vias_of_the_rounds_before_a_child_that_cannot_load_pcbnew(
    tmp_path, monkeypatch, capsys
):
    """Round 1 adds a via; round 2's child finds no pcbnew. The via and round 1's islands stand."""
    monkeypatch.setattr(kicadgen, "fill_zones", lambda pcb, *a: {})
    stand_in(
        tmp_path,
        monkeypatch,
        [
            {
                "contract": 1,
                "stitches": [
                    {"net": "GND", "at": [104.5, 107.25], "layer": "F.Cu", "to": "B.Cu", "island": ["J1.3"]}
                ],
                "left": [["R9.2"]],
            },
            {"exit": 3, "line": "kicadchild: pcbnew does not import in /k/python3"},
        ],
    )
    d = bare_board()
    assert kicadgen.stitch_zones(d, tmp_path / "bare.kicad_pcb") == (1, [["R9.2"]])
    assert d.vias[-1][:2] == ("GND", (104.5, 107.25))
    assert capsys.readouterr().err.splitlines()[-1] == (
        "stitch: kicadchild: pcbnew does not import in /k/python3; islands are left to the DRC"
    )


def test_a_child_that_does_not_answer_in_time_stops_the_step_in_1_line(tmp_path, monkeypatch):
    stand_in(tmp_path, monkeypatch, [{"sleep": 30, "contract": 1, "stitches": [], "left": []}])
    monkeypatch.setattr(kicadchild, "TIMEOUT", 1)
    # The whole path: on macOS the venv's Python is under "Application Support" (run 46067841222).
    said = re.escape(f"KiCad's Python {sys.executable} did not answer stitch in 1 s")
    with pytest.raises(RuntimeError, match=f"^{said}$"):
        kicadgen.stitch_zones(bare_board(), tmp_path / "bare.kicad_pcb")


@pytest.mark.parametrize("raw", ["Debug: a DLL wrote here\n{}", "\xff not ascii"])
def test_an_answer_that_is_not_json_stops_the_step_in_1_line(tmp_path, monkeypatch, raw):
    """A KiCad library that writes past the child's swap of fd 1 (on Windows, through its own C
    runtime) would put its text before the answer: 1 line that shows the start of it, no traceback."""
    stand_in(tmp_path, monkeypatch, [{"raw": raw}])
    said = re.escape(f"KiCad's Python {sys.executable} answered stitch with no JSON: b'")
    with pytest.raises(RuntimeError, match=f"^{said}") as got:
        kicadgen.stitch_zones(bare_board(), tmp_path / "bare.kicad_pcb")
    assert "\n" not in str(got.value)


def test_stitch_zones_says_1_line_when_kicads_python_is_missing(tmp_path, monkeypatch, capsys):
    """macOS or Windows with no KiCad found: the board is written unstitched, and the DRC judges it."""
    monkeypatch.setattr(kicadchild, "python", lambda: None)
    d = bare_board()
    vias = list(d.vias)
    assert kicadgen.stitch_zones(d, tmp_path / "bare.kicad_pcb") == (0, [])
    assert d.vias == vias and d.stitches == []
    err = capsys.readouterr().err.splitlines()
    assert err == [
        "stitch: KiCad's Python (with its pcbnew module) is not found; `workcenter doctor` says where it "
        "looks; islands are left to the DRC"
    ]


def test_stitch_zones_says_1_line_when_pcbnew_does_not_import_in_the_child(tmp_path, monkeypatch, capsys):
    stand_in(tmp_path, monkeypatch, [{"exit": 3, "line": "kicadchild: pcbnew does not import in /k/python3"}])
    assert kicadgen.stitch_zones(bare_board(), tmp_path / "bare.kicad_pcb") == (0, [])
    assert capsys.readouterr().err.splitlines() == [
        "stitch: kicadchild: pcbnew does not import in /k/python3; islands are left to the DRC"
    ]


def test_a_child_that_fails_otherwise_stops_the_step_with_its_last_line(tmp_path, monkeypatch):
    stand_in(tmp_path, monkeypatch, [{"exit": 1, "line": "RuntimeError: LoadBoard failed"}])
    with pytest.raises(RuntimeError, match=r"failed on stitch \(exit 1\): RuntimeError: LoadBoard failed$"):
        kicadgen.stitch_zones(bare_board(), tmp_path / "bare.kicad_pcb")


def test_an_answer_of_another_contract_is_refused(tmp_path, monkeypatch):
    stand_in(tmp_path, monkeypatch, [{"contract": 2, "stitches": [], "left": []}])
    with pytest.raises(RuntimeError, match="answered contract 2, not 1"):
        kicadgen.stitch_zones(bare_board(), tmp_path / "bare.kicad_pcb")


def test_the_childs_keepout_and_distance_match_kicadgens():
    """The child keeps its own copies of kicadgen's geometry (it may import nothing of Via's): the
    same answers, bit for bit, on 3000 random cases."""
    rng = random.Random(20261127)
    d = bare_board()
    d.keepout(
        kicadgen.Design.circle(112.0, 107.0, 2.0), layers=("B.Cu",), name="open", parts=True, copper=False
    )
    d.keepout([(115.0, 101.0), (119.0, 101.5), (117.0, 104.0)], layers=("F.Cu",), name="tri")
    keepouts = kicadgen._stitch_request(d, Path("x"))["keepouts"]
    poly = [(rng.uniform(0, 10), rng.uniform(0, 10)) for _ in range(9)]
    for _ in range(3000):
        p = (rng.uniform(-1, 11), rng.uniform(-1, 11))
        a, b = (rng.uniform(0, 10), rng.uniform(0, 10)), (rng.uniform(0, 10), rng.uniform(0, 10))
        assert kicadchild._seg_dist(p, a, b) == kicadgen._seg_dist(p, a, b)
        assert kicadchild._inside_polygon(*p, [list(q) for q in poly]) == kicadgen._inside_polygon(*p, poly)
        x, y, r = rng.uniform(100, 120), rng.uniform(100, 110), rng.uniform(0.1, 0.6)
        assert kicadchild.in_keepout(keepouts, x, y, r) == d.in_keepout(x, y, r)


def test_a_via_that_just_touches_a_keepout_is_clear_of_it_in_both():
    """A via whose rim lies on the keepout's edge, to the bit: clear, as kicadgen says."""
    d = bare_board()
    d.keepout([(112.0, 101.0), (113.0, 101.0), (113.0, 102.0), (112.0, 102.0)], layers=("F.Cu",), name="sq")
    keepouts = kicadgen._stitch_request(d, Path("x"))["keepouts"]
    for r, inside in ((0.5, False), (0.5000001, True)):
        assert kicadchild.in_keepout(keepouts, 113.5, 101.5, r) is inside
        assert d.in_keepout(113.5, 101.5, r) is inside


# ------------------------------------------------- the search, on a stand-in for KiCad's geometry


class Point:
    def __init__(self, x: int, y: int):
        self.x, self.y = x, y


class Rects:
    """A stand-in for KiCad's filled polygons (SHAPE_POLY_SET): outline i is the rectangle rects[i], in
    mm, edges included. `asked` keeps every point Contains was asked about."""

    def __init__(self, *rects):
        self.rects, self.asked = rects, []

    def Contains(self, p, i):  # noqa: N802 (KiCad's name)
        self.asked.append((p.x, p.y))
        x1, y1, x2, y2 = (round(v * 1e6) for v in self.rects[i])
        return x1 <= p.x <= x2 and y1 <= p.y <= y2

    def Outline(self, i):  # noqa: N802
        x1, y1, x2, y2 = (round(v * 1e6) for v in self.rects[i])
        box = types.SimpleNamespace(
            GetLeft=lambda: x1, GetTop=lambda: y1, GetRight=lambda: x2, GetBottom=lambda: y2
        )
        return types.SimpleNamespace(BBox=lambda: box)


#: pcbnew as the search uses it: VECTOR2I_MM gives integer nanometres.
FAKE_PCBNEW = types.SimpleNamespace(VECTOR2I_MM=lambda x, y: Point(round(x * 1e6), round(y * 1e6)))


def test_inside_fill_asks_the_centre_and_16_points_round_the_rim():
    polys = Rects((0.0, 0.0, 4.0, 4.0))
    assert kicadchild._inside_fill(FAKE_PCBNEW, polys, 0, 2.0, 2.0, 0.35)
    assert len(set(polys.asked)) == 17


def test_via_spot_keeps_the_hole_spacing_from_every_other_hole():
    """0.25 mm between holes, edge to edge, on top of the 2 radii (kicadchild._via_spot)."""
    fill = Rects((0.0, 0.0, 4.0, 4.0))
    target = ("B.Cu", Rects((0.0, 0.0, 4.0, 4.0)), 0, [])
    holes = [(Point(2_000_000, 2_000_000), 0.15)]
    x, y = kicadchild._via_spot(FAKE_PCBNEW, fill, 0, [target], 0.3, 0.15, holes)
    assert ((x - 2.0) ** 2 + (y - 2.0) ** 2) ** 0.5 >= 0.15 + 0.15 + 0.25


def test_via_spot_keeps_the_via_0_05_mm_inside_both_fills():
    """A strip 0.64 mm high: only its row at y = 0.3 holds a via of radius 0.2 with 0.05 mm to spare.
    With the target's edge at y = 0.16 that row is out too, and the row at y = 0.4, 0.24 mm from the
    edge, holds the via but not the 0.05 mm: no spot."""
    strip = Rects((0.0, 0.0, 4.0, 0.64))
    whole = ("B.Cu", Rects((0.0, 0.0, 4.0, 2.0)), 0, [])
    assert kicadchild._via_spot(FAKE_PCBNEW, strip, 0, [whole], 0.2, 0.1, [])[1] == 0.3
    lower = ("B.Cu", Rects((0.0, 0.16, 4.0, 2.0)), 0, [])
    assert kicadchild._via_spot(FAKE_PCBNEW, strip, 0, [lower], 0.2, 0.1, []) is None


def test_via_blocker_lets_a_via_sit_on_its_own_nets_copper_and_not_on_anothers():
    request = {
        "segments": [["GND", [0.0, 0.0], [10.0, 0.0], 0.2, "In1.Cu"]],
        "boxes": [{"net": "GND", "layer": "In1.Cu", "x1": 4.0, "y1": 4.0, "x2": 6.0, "y2": 6.0}],
    }
    own = kicadchild.via_blocker(None, request, [], "GND", 0.3, ["In1.Cu"], {"In1.Cu": 0.5})
    assert not own(5.0, 0.1) and not own(5.0, 5.0)
    other = kicadchild.via_blocker(None, request, [], "VIN", 0.3, ["In1.Cu"], {"In1.Cu": 0.5})
    assert other(5.0, 0.1) and other(5.0, 5.0)
    # The reach is from the track's edge: 0.6 mm from a 0.2 mm track's centre is 0.5 mm from its edge.
    assert other(5.0, 0.59) and not other(5.0, 0.61)


def test_stitch_tries_every_other_component_skips_bare_islands_and_spaces_its_own_vias(monkeypatch):
    """Components, biggest first: the main pour (no B.Cu piece), island R2.2, a bare B.Cu piece, a bare
    F.Cu piece, island R3.2. Each island's via lands only in the bare B.Cu piece, the third component;
    the bare pieces are no islands; the second via's search sees the first via's hole."""
    main, island, bottom, bare, island2 = (Rects((0.0, 0.0, 1.0, 1.0)) for _ in range(5))
    pieces = [
        ("F.Cu", main, 0, ["J1.1"]),
        ("F.Cu", island, 0, ["R2.2"]),
        ("B.Cu", bottom, 0, []),
        ("F.Cu", bare, 0, []),
        ("F.Cu", island2, 0, ["R3.2"]),
    ]
    graph = {"pieces": pieces, "components": [{0}, {1}, {2}, {3}, {4}]}
    monkeypatch.setattr(kicadchild, "pour_pieces", lambda pcbnew, pcb, net: graph)
    monkeypatch.setattr(kicadchild, "_holes", lambda pcbnew, pcb: [])
    monkeypatch.setattr(kicadchild, "via_blocker", lambda *a: None)
    seen = []

    def via_spot(pcbnew, polys, i, targets, radius, hole, holes, blocked=None):
        seen.append((polys, [(p.x, p.y, r) for p, r in holes]))
        if any(t[1] is bottom for t in targets):
            return {island: (0.5, 0.5), island2: (0.8, 0.5)}.get(polys)
        return None

    monkeypatch.setattr(kicadchild, "_via_spot", via_spot)
    request = {
        "pcb": "x",
        "copper": ["F.Cu", "B.Cu"],
        "nets": [{"net": "GND", "size": 0.6, "drill": 0.3, "reach": {}}],
    }
    assert kicadchild.stitch(FAKE_PCBNEW, request) == {
        "stitches": [
            {"net": "GND", "at": [0.5, 0.5], "layer": "F.Cu", "to": "B.Cu", "island": ["R2.2"]},
            {"net": "GND", "at": [0.8, 0.5], "layer": "F.Cu", "to": "B.Cu", "island": ["R3.2"]},
        ],
        "left": [],
    }
    assert [holes for polys, holes in seen if polys is island2][-1] == [(500_000, 500_000, 0.15)]


# ----------------------------------------------------------------------------- workcenter next


def load_cli():
    cli = ROOT / "tools" / "workcenter"
    loader = importlib.machinery.SourceFileLoader("workcenter_cli_kicadchild", str(cli))
    module = types.ModuleType(loader.name)
    module.__file__ = str(cli)
    sys.modules[module.__name__] = module
    loader.exec_module(module)
    return module


def poured_project(tmp_path: Path) -> Path:
    board = tmp_path / "b"
    board.mkdir()
    (board / "design.py").write_text("# a design\n", encoding="utf-8")
    (board / "b.kicad_pro").write_text("{}\n", encoding="utf-8")
    (board / "b.kicad_pcb").write_text(
        '(kicad_pcb (version 20241229) (generator "pcbnew")\n'
        '  (zone (net 1) (net_name "GND") (layers "F.Cu"))\n)\n',
        encoding="utf-8",
    )
    return board


def test_next_names_kicads_python_for_a_poured_board_that_cannot_be_stitched(tmp_path, monkeypatch):
    cli = load_cli()
    monkeypatch.setattr(cli, "KICAD_CLI", sys.executable)  # the toolchain step is not the one asked of
    monkeypatch.setattr(kicadchild, "python", lambda: None)
    monkeypatch.setattr(guide.sys, "platform", "darwin")
    board = poured_project(tmp_path)
    step = guide.next_step(cli, str(board), run_check=False)
    assert step.next == (
        "Install KiCad 10 with its own Python: none is found. `design --route` stitches the pours with "
        "KiCad's pcbnew, run in that Python."
    )
    # The line is the toolchain step's own (tools/hostos.py installer_command), the path quoted.
    monkeypatch.setattr(cli, "SRC_DIR", Path("/Users/Jane Doe/via"))
    assert guide.next_step(cli, str(board), run_check=False).run == "'/Users/Jane Doe/via/install-macos.sh'"
    assert step.why == "b.kicad_pcb has a pour, and KiCad's Python (with its pcbnew module) is not found"
    assert step.done_when == "`workcenter doctor` shows the pcbnew row ok"
    # shutil.which reads sys.platform too: on "win32" it looks for kicad-cli.exe.
    monkeypatch.setattr(guide.shutil, "which", lambda name, *a, **k: name)
    monkeypatch.setattr(guide.sys, "platform", "win32")
    monkeypatch.setattr(cli, "SRC_DIR", "C:\\Users\\Jane Doe\\via")
    step = guide.next_step(cli, str(board), run_check=False)
    windows = 'powershell -NoProfile -ExecutionPolicy Bypass -File "C:\\Users\\Jane Doe\\via\\install.ps1"'
    assert step.run == windows


def test_next_asks_nothing_of_kicads_python_where_it_is_found_or_the_board_has_no_pour(tmp_path, monkeypatch):
    cli = load_cli()
    monkeypatch.setattr(cli, "KICAD_CLI", sys.executable)
    board = poured_project(tmp_path)
    monkeypatch.setattr(kicadchild, "python", lambda: sys.executable)
    assert "KiCad 10 with its own Python" not in guide.next_step(cli, str(board), run_check=False).next
    monkeypatch.setattr(guide.sys, "platform", "darwin")  # found off Linux: no step either
    assert "KiCad 10 with its own Python" not in guide.next_step(cli, str(board), run_check=False).next
    monkeypatch.setattr(kicadchild, "python", lambda: None)
    (board / "b.kicad_pcb").write_text(
        '(kicad_pcb (version 20241229) (generator "pcbnew"))\n', encoding="utf-8"
    )
    assert "KiCad 10 with its own Python" not in guide.next_step(cli, str(board), run_check=False).next


# ------------------------------------------------------------------ the real child, on a real board


#: The real child under KiCad's Python: what a macOS or Windows leg runs, where Via's venv has no pcbnew.
needs_kicad_python = engine(
    pytest.mark.skipif(
        engine_absent("kicad-cli") or not LIBS.is_file() or kicadchild.python() is None,
        reason="kicad-cli, KiCad's libraries or KiCad's Python are not installed",
    )
)
#: The same search in this process too: Linux alone, where the venv sees pcbnew (install.sh).
needs_pcbnew = engine(
    pytest.mark.skipif(
        engine_absent("kicad-cli")
        or not LIBS.is_file()
        or importlib.util.find_spec("pcbnew") is None
        or kicadchild.python() is None,
        reason="kicad-cli, KiCad's libraries or pcbnew in this Python are not installed",
    )
)


def walled_off_divider() -> kicadgen.Design:
    """tests/test_kicadgen.py's walled-off pad: the OUT net rings R2's ground pad on the top face, so
    the stitch step must drop a via through to the bottom pour."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_kicadgen import poured_divider

    d = poured_divider()
    d.track("VIN", [(103.0, 102.5), (107.675, 102.5)], "F.Cu")
    d.track("OUT", [(103.0, 105.04), (106.5, 105.04), (107.675, 106.5)], "F.Cu")
    d.track("OUT", [(109.325, 102.5), (109.325, 103.8), (110.3, 104.6), (110.3, 105.5)], "F.Cu")
    ring = [(107.675, 106.5), (108.4, 106.5), (108.4, 105.5), (110.3, 105.5), (110.3, 107.5), (108.4, 107.5)]
    d.track("OUT", [*ring, (108.4, 106.5)], "F.Cu")
    return d


@needs_kicad_python
def test_the_real_child_stitches_the_walled_off_pad_under_kicads_python(tmp_path, capsys):
    """The child run as `design` runs it, under kicadchild.python(): 1 GND via from the top island of
    R2.2 to the bottom pour, at the spot the child gave on Linux with KiCad 10.0. A macOS or Windows
    leg runs this test where the in-process test below skips."""
    d = walled_off_divider()
    d.write(tmp_path)
    assert [v for v in d.vias if v[0] == "GND"] == [("GND", (109.325, 106.526), 0.6, 0.3)]
    assert d.stitches == [
        {"net": "GND", "at": (109.325, 106.526), "layer": "F.Cu", "to": "B.Cu", "pads": ["R2.2"]}
    ]
    assert d.islands == []
    assert "stitch:" not in capsys.readouterr().err


@needs_pcbnew
def test_the_child_writes_the_same_bytes_as_the_same_search_in_this_process(tmp_path, monkeypatch):
    """On Linux the child runs the venv's Python, which sees the same pcbnew as this process: the board,
    its vias and its stitches are the same bytes either way (the transport adds nothing)."""
    child = walled_off_divider()
    child.write(tmp_path / "child")
    import pcbnew

    def here(op, request):
        return kicadchild.answer(op, {**request, "contract": kicadchild.CONTRACT}, pcbnew)

    monkeypatch.setattr(kicadchild, "run", here)
    inproc = walled_off_divider()
    inproc.write(tmp_path / "here")
    assert child.stitches and child.islands == []
    assert (child.vias, child.stitches, child.islands) == (inproc.vias, inproc.stitches, inproc.islands)
    for f in sorted((tmp_path / "child").iterdir()):
        if f.is_file():
            assert f.read_bytes() == (tmp_path / "here" / f.name).read_bytes(), f.name


def test_the_stand_in_types_are_what_kicadgen_stores(tmp_path, monkeypatch):
    """A spot comes back as a JSON list; the design keeps it as the tuple it always held, so the board
    writer and `design --json` see what they saw before the child."""
    monkeypatch.setattr(kicadgen, "fill_zones", lambda pcb, *a: {})
    stand_in(
        tmp_path,
        monkeypatch,
        [
            {
                "contract": 1,
                "stitches": [
                    {"net": "GND", "at": [101.0, 101.5], "layer": "B.Cu", "to": "F.Cu", "island": []}
                ],
                "left": [],
            },
            {"contract": 1, "stitches": [], "left": []},
        ],
    )
    d = bare_board()
    pcb = tmp_path / "bare.kicad_pcb"
    kicadgen.stitch_zones(d, pcb)
    assert isinstance(d.vias[-1][1], tuple) and isinstance(d.stitches[-1]["at"], tuple)
    assert types.SimpleNamespace(**d.stitches[-1]).pads == []
