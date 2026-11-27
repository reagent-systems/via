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
import shutil
import subprocess
import sys
import types
import uuid
from pathlib import Path

import pytest
from conftest import engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import guide  # noqa: E402
import kicadchild  # noqa: E402
import kicadgen  # noqa: E402

CHILD = ROOT / "tools" / "kicadchild.py"
LIBS = kicadgen.SYMBOL_DIR / "Device.kicad_sym"

# The stand-in: writes each request it gets to request-<n>.json beside itself, and answers with the
# n-th entry of answers.json there; an entry {"exit": code, "line": text} exits with that code instead.
STAND_IN = """\
import json, sys
from pathlib import Path
here = Path(__file__).resolve().parent
n = len(list(here.glob("request-*.json")))
(here / f"request-{n}.json").write_text(sys.stdin.read())
said = json.loads((here / "answers.json").read_text())[n]
if "exit" in said:
    print("Debug: Adding duplicate image handler for 'Windows bitmap file'", file=sys.stderr)
    print(said["line"], file=sys.stderr)
    sys.exit(said["exit"])
print("a line of the child's own", file=sys.stderr)
print(json.dumps(said))
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
        "Install KiCad 10 with its own Python: `design --route` stitches the pours with KiCad's pcbnew, "
        "run in that Python, and none is found."
    )
    assert step.run == f"{cli.SRC_DIR / 'install-macos.sh'}"
    assert step.why == "b.kicad_pcb has a pour, and KiCad's Python (with its pcbnew module) is not found"
    assert step.done_when == "`workcenter doctor` shows the pcbnew row ok"
    # shutil.which reads sys.platform too: on "win32" it looks for kicad-cli.exe.
    monkeypatch.setattr(guide.shutil, "which", lambda name, *a, **k: name)
    monkeypatch.setattr(guide.sys, "platform", "win32")
    step = guide.next_step(cli, str(board), run_check=False)
    assert step.run == f"powershell -ExecutionPolicy Bypass -File {cli.SRC_DIR / 'install.ps1'}"


def test_next_asks_nothing_of_kicads_python_where_it_is_found_or_the_board_has_no_pour(tmp_path, monkeypatch):
    cli = load_cli()
    monkeypatch.setattr(cli, "KICAD_CLI", sys.executable)
    board = poured_project(tmp_path)
    monkeypatch.setattr(kicadchild, "python", lambda: sys.executable)
    assert "KiCad 10 with its own Python" not in guide.next_step(cli, str(board), run_check=False).next
    monkeypatch.setattr(kicadchild, "python", lambda: None)
    (board / "b.kicad_pcb").write_text(
        '(kicad_pcb (version 20241229) (generator "pcbnew"))\n', encoding="utf-8"
    )
    assert "KiCad 10 with its own Python" not in guide.next_step(cli, str(board), run_check=False).next


# ------------------------------------------------------------------ the real child, on a real board


needs_pcbnew = engine(
    pytest.mark.skipif(
        shutil.which("kicad-cli") is None
        or not LIBS.is_file()
        or importlib.util.find_spec("pcbnew") is None
        or kicadchild.python() is None,
        reason="kicad-cli, KiCad's libraries or pcbnew are not installed",
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
