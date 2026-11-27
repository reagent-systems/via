#!/usr/bin/env python3
"""kicadchild — the board step that needs KiCad's `pcbnew` module, run as a child under KiCad's Python.

`design` stitches a routed board's pours: it finds the pieces of each poured net that the tracks cut
off, and a spot for a via that joins each piece to the main pour. That reads the filled board with
KiCad's own geometry, the `pcbnew` module. On Linux Via's venv sees pcbnew (install.sh makes the venv
with --system-site-packages). On macOS and Windows pcbnew lives only in the Python KiCad bundles, which
cannot hold Via's packages (numpy 2.5.4 needs Python 3.12). So tools/kicadgen.py runs this file as a
child process, under the Python `hostos.kicad_python()` names, on every platform:

    <KiCad's Python> -s kicadchild.py stitch < request.json > answer.json

The request and the answer are JSON objects, each with "contract": CONTRACT. kicadgen sends what the
search needs of the design (the poured nets with their via size and reach, the copper layers, the
keepouts, the other nets' tracks and pads); the answer is the vias found, in order, and the islands
left. kicadgen adds the vias, writes the board, has KiCad fill it, and asks again (stitch_zones).

The child's half is standard library and pcbnew only, and valid Python 3.9: KiCad 10's macOS build
recipe bundles 3.9.13 and its Windows vcpkg.json 3.11.5 (tools/hostos.py, kicad_python). Neither is
confirmed in a run. Only `python()` and `run()`, the parent's half, import Via's own modules.

Exit codes: 0 the answer is on stdout; 2 the request is refused; 3 pcbnew does not import in this
Python. A refusal is 1 line on stderr. KiCad's own messages on loading go to stderr too: stdout holds
the answer alone.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

CONTRACT = 1
OPS = ("stitch",)
EXIT_REFUSED = 2
EXIT_NO_PCBNEW = 3
HERE = Path(__file__).resolve().parent
CHILD = Path(__file__).resolve()
# KiCad's Python module writes these to stderr on every load; they say nothing about the board
# (tools/workcenter KICAD_NOISE).
NOT_FOUND = "KiCad's Python (with its pcbnew module) is not found"
KICAD_NOISE = re.compile(r"Debug: Adding duplicate image handler|property\.h\(\d+\): assert")


class Missing(Exception):
    """KiCad's Python is not found, or pcbnew does not import in it: the step cannot run here."""


# ------------------------------------------------------------------ the parent's half (Via's venv)


def python() -> str | None:
    """The Python that imports KiCad's pcbnew: tools/hostos.py kicad_python(). None where no KiCad is
    found (macOS and Windows); on Linux the venv's Python, else this one."""
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import hostos

    return hostos.kicad_python()


def run(op: str, request: dict) -> dict:
    """Run `op` in the child under KiCad's Python: the request in on stdin, the answer out on stdout.

    Raises Missing (1 line) when KiCad's Python is not found or pcbnew does not import in it, and
    RuntimeError (1 line) when the child fails another way. The child's stderr, less KiCad's noise on
    loading, goes to this process's stderr."""
    py = python()
    if py is None:
        raise Missing(f"{NOT_FOUND}; `workcenter doctor` says where it looks")
    # -s: the user's own site folder stays out; KiCad's Python sees its own packages only.
    proc = subprocess.run(
        [py, "-s", str(CHILD), op],
        input=json.dumps({**request, "contract": CONTRACT}).encode("ascii"),
        capture_output=True,
        check=False,
    )
    said = [
        ln
        for ln in proc.stderr.decode("utf-8", "replace").splitlines()
        if ln.strip() and not KICAD_NOISE.search(ln)
    ]
    if proc.returncode == EXIT_NO_PCBNEW:
        raise Missing(said[-1] if said else f"pcbnew does not import in {py}")
    if proc.returncode != 0:
        last = said[-1] if said else "no message"
        raise RuntimeError(f"KiCad's Python {py} failed on {op} (exit {proc.returncode}): {last}")
    for ln in said:
        print(ln, file=sys.stderr)
    answer = json.loads(proc.stdout.decode("ascii"))
    got = answer.get("contract")
    if got != CONTRACT:
        raise RuntimeError(f"KiCad's Python {py} answered contract {got!r}, not {CONTRACT}")
    return answer


# ------------------------------------------------------- the child's half (KiCad's Python, 3.9 on)


def _inside_polygon(x: float, y: float, poly) -> bool:
    """Even-odd point-in-polygon test: kicadgen._inside_polygon, line for line."""
    inside = False
    # No strict=: Python 3.9 has none, and the 2 lists are 1 length.
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):  # noqa: B905
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _seg_dist(p, a, b) -> float:
    """Distance from point p to segment ab: kicadgen._seg_dist, line for line."""
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    if dx == dy == 0:
        return math.hypot(px - ax, py - ay)
    u = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + u * dx), py - (ay + u * dy))


def in_keepout(keepouts: list, x: float, y: float, r: float) -> bool:
    """kicadgen.Design.in_keepout on the request's keepouts: a via of radius `r` at (x, y) touches one.
    An area with "copper": false lets vias through."""
    for k in keepouts:
        if not k.get("copper", True):
            continue
        poly = k["polygon"]
        edges = zip(poly, poly[1:] + poly[:1])  # noqa: B905  (Python 3.9 has no strict=)
        if _inside_polygon(x, y, poly) or min(_seg_dist((x, y), a, b) for a, b in edges) < r:
            return True
    return False


def pour_pieces(pcbnew, pcb: str, net: str) -> dict:
    """How the filled pours of `net` hang together, read with KiCad's own geometry (pcbnew).

    Returns {"pieces": [(layer, polys, index, items)], "components": [set of piece ids]}: one piece per
    filled polygon, `items` the pads and vias of the net it touches, and components joined by the
    through-hole pads and vias shared between layers. Every piece that holds an item should end up in
    one component; the rest are the islands the DRC reports as unconnected zone-to-zone.
    """
    board = pcbnew.LoadBoard(str(pcb))
    code = board.GetNetcodeFromNetname(net)
    pieces: list = []
    for zone in board.Zones():
        if zone.GetNetCode() != code:
            continue
        for layer in zone.GetLayerSet().CuStack():
            polys = zone.GetFilledPolysList(layer)
            for i in range(polys.OutlineCount()):
                pieces.append((pcbnew.LayerName(layer), polys, i, []))
    items = []  # (position, layers, drill)
    copper = {pcbnew.LayerName(ly) for ly in board.GetEnabledLayers().CuStack()}  # a via spans them all
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetCode() == code:
                layers = {pcbnew.LayerName(ly) for ly in pad.GetLayerSet().CuStack()}
                items.append((pad.GetPosition(), layers, f"{fp.GetReference()}.{pad.GetNumber()}"))
    for track in board.GetTracks():
        if track.GetClass() == "PCB_VIA" and track.GetNetCode() == code:
            items.append(
                (
                    track.GetPosition(),
                    copper,
                    f"via@{track.GetPosition().x / 1e6:.2f},{track.GetPosition().y / 1e6:.2f}",
                )
            )
    parent = list(range(len(pieces)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for pos, layers, name in items:
        touched = [
            k for k, (layer, polys, i, _) in enumerate(pieces) if layer in layers and polys.Contains(pos, i)
        ]
        for k in touched:
            pieces[k][3].append(name)
        for k in touched[1:]:
            parent[find(k)] = find(touched[0])
    groups: dict = {}
    for k in range(len(pieces)):
        groups.setdefault(find(k), set()).add(k)

    def area(group: set) -> float:
        return sum(pieces[k][1].Outline(pieces[k][2]).Area() for k in group)

    return {"pieces": pieces, "components": sorted(groups.values(), key=area, reverse=True)}


def stitch(pcbnew, request: dict) -> dict:
    """1 round of kicadgen.stitch_zones on the filled board `request["pcb"]`: for each poured net in
    turn, each island that holds a pad or a via gets a via into another component of the pour, the
    biggest first, on another layer. Returns {"stitches": [{net, at, layer, to, island}], "left":
    [island]}, in the order found; an island is the sorted names of the pads and vias it holds."""
    pcb = request["pcb"]
    copper = list(request["copper"])
    stitches: list = []
    left: list = []
    for job in request["nets"]:
        net, size, drill = job["net"], job["size"], job["drill"]
        graph = pour_pieces(pcbnew, pcb, net)
        pieces, components = graph["pieces"], graph["components"]
        if not components:
            continue
        holes = _holes(pcbnew, pcb)
        for n, comp in enumerate(components[1:], start=1):
            if not any(pieces[k][3] for k in comp):
                continue  # a bare island: KiCad drops it
            spot = None
            # Land the via in the biggest other component first; any merge is progress.
            for m_comp in components[:n] + components[n + 1 :]:
                for k in comp:
                    layer, polys, i, names = pieces[k]
                    for other in (ly for ly in copper if ly != layer):
                        targets = [pieces[m] for m in m_comp if pieces[m][0] == other]
                        # The via passes every other layer too: there it sits in the net's own
                        # pour or keeps clear of the other nets' copper (P17).
                        rest = [ly for ly in copper if ly not in (layer, other)]
                        spot = _via_spot(
                            pcbnew,
                            polys,
                            i,
                            targets,
                            size / 2,
                            drill / 2,
                            holes,
                            blocked=via_blocker(pcbnew, request, pieces, net, size / 2, rest, job["reach"]),
                        )
                        if spot:
                            break
                    if spot:
                        break
                if spot:
                    break
            island = sorted({n for k in comp for n in pieces[k][3]})
            if spot is None:
                left.append(island)
                continue
            stitches.append({"net": net, "at": list(spot), "layer": layer, "to": other, "island": island})
            holes.append((pcbnew.VECTOR2I_MM(*spot), drill / 2))
    return {"stitches": stitches, "left": left}


def via_blocker(pcbnew, request: dict, pieces: list, net: str, r: float, rest: list, reach: dict):
    """The `blocked` test for a stitching via of `net` and radius `r`: True where a keepout refuses it,
    or where on one of the `rest` layers (those it passes without joining) it is neither inside the
    net's own fill nor clear of the other nets' tracks and pads by `reach[layer]`, the copper clearance
    or the layer's hole clearance, whichever is further (kicadgen.Design.via_reach, M79)."""
    keepouts = request.get("keepouts", [])
    segments = request.get("segments", [])
    boxes = request.get("boxes", [])

    def clear_on(layer: str, x: float, y: float) -> bool:
        if any(_inside_fill(pcbnew, polys, i, x, y, r + 0.05) for ly, polys, i, _ in pieces if ly == layer):
            return True
        far = reach[layer]
        for n, a, b, w, ly in segments:
            if ly == layer and n != net and _seg_dist((x, y), a, b) < far + w / 2:
                return False
        for pad in boxes:
            if pad["layer"] == layer and pad["net"] != net:
                dx = max(pad["x1"] - x, 0.0, x - pad["x2"])
                dy = max(pad["y1"] - y, 0.0, y - pad["y2"])
                if math.hypot(dx, dy) < far:
                    return False
        return True

    def blocked(x: float, y: float) -> bool:
        return in_keepout(keepouts, x, y, r) or not all(clear_on(ly, x, y) for ly in rest)

    return blocked


def _inside_fill(pcbnew, polys, index: int, x: float, y: float, margin: float) -> bool:
    """Is a disc of radius `margin` at (x, y) inside filled polygon `index` of `polys`? Tested at its
    centre and at 16 points round its rim."""
    if not polys.Contains(pcbnew.VECTOR2I_MM(x, y), index):
        return False
    return all(
        polys.Contains(
            pcbnew.VECTOR2I_MM(
                x + margin * math.cos(k * math.pi / 8), y + margin * math.sin(k * math.pi / 8)
            ),
            index,
        )
        for k in range(16)
    )


def _holes(pcbnew, pcb: str) -> list:
    """(position, radius) of every drilled hole on the board: pads, mounting holes, vias."""
    board = pcbnew.LoadBoard(str(pcb))
    holes = []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetDrillSizeX() > 0:
                holes.append((pad.GetPosition(), max(pad.GetDrillSizeX(), pad.GetDrillSizeY()) / 2e6))
    for track in board.GetTracks():
        if track.GetClass() == "PCB_VIA":
            holes.append((track.GetPosition(), track.GetDrillValue() / 2e6))
    return holes


def _via_spot(
    pcbnew, polys, index: int, targets: list, radius: float, hole: float, holes: list, blocked=None
):
    """A point where a via of `radius` sits inside filled polygon `index` of `polys` and inside one of
    the target polygons on the other layer, clear of every other hole and of every point `blocked`
    refuses (a keepout: the pour may fill one, a via may not sit in it). Scans a 0.1 mm grid from the
    polygon's centre outwards; None when nothing fits."""
    if not targets:
        return None
    bb = polys.Outline(index).BBox()
    cx, cy = (bb.GetLeft() + bb.GetRight()) / 2e6, (bb.GetTop() + bb.GetBottom()) / 2e6
    step = 0.1
    nx = int((bb.GetRight() - bb.GetLeft()) / 1e6 / step) + 1
    ny = int((bb.GetBottom() - bb.GetTop()) / 1e6 / step) + 1
    candidates = [
        (bb.GetLeft() / 1e6 + ix * step, bb.GetTop() / 1e6 + iy * step)
        for ix in range(nx)
        for iy in range(ny)
    ]
    candidates.sort(key=lambda c: (c[0] - cx) ** 2 + (c[1] - cy) ** 2)
    margin = radius + 0.05

    def inside(poly, i, x, y) -> bool:
        return _inside_fill(pcbnew, poly, i, x, y, margin)

    for x, y in candidates:
        if not inside(polys, index, x, y):
            continue
        if not any(inside(tp, ti, x, y) for _, tp, ti, _ in targets):
            continue
        if blocked is not None and blocked(x, y):
            continue
        p = pcbnew.VECTOR2I_MM(x, y)
        if any(math.hypot((p.x - hp.x) / 1e6, (p.y - hp.y) / 1e6) < hole + hr + 0.25 for hp, hr in holes):
            continue
        return (round(x, 3), round(y, 3))
    return None


def answer(op: str, request: dict, pcbnew=None) -> dict:
    """The answer to `op`, with pcbnew imported here unless given. The child's main calls it; a test
    calls it in the parent's process to hold the 2 to the same bytes."""
    if pcbnew is None:
        import pcbnew  # KiCad's own Python module
    if op == "stitch":
        return {**stitch(pcbnew, request), "contract": CONTRACT}
    raise ValueError(f"no op {op!r}")


def refuse(code: int, line: str) -> int:
    print(f"kicadchild: {line}", file=sys.stderr)
    return code


def main(argv: list) -> int:
    if len(argv) != 2 or argv[1] not in OPS:
        return refuse(EXIT_REFUSED, f"usage: kicadchild.py {{{','.join(OPS)}}} < request.json")
    try:
        request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except ValueError as exc:
        return refuse(EXIT_REFUSED, f"the request is not JSON: {exc}")
    if not isinstance(request, dict) or request.get("contract") != CONTRACT:
        got = request.get("contract") if isinstance(request, dict) else None
        return refuse(EXIT_REFUSED, f"the request's contract is {got!r}; this child answers {CONTRACT}")
    # stdout carries the answer alone: whatever KiCad's libraries print while they load goes to stderr.
    out = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)
    try:
        import pcbnew  # KiCad's own Python module
    except ImportError as exc:
        version = ".".join(map(str, sys.version_info[:3]))
        return refuse(EXIT_NO_PCBNEW, f"pcbnew does not import in {sys.executable} (Python {version}): {exc}")
    said = answer(argv[1], request, pcbnew)
    out.write(json.dumps(said).encode("ascii"))
    out.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
