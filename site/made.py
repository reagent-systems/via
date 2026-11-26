"""The gallery of boards made with Via, served at made.via.computer.

    python3 site/made.py          # write site/made.html
    python3 site/made.py --check  # exit 1 when site/made.html is not what this writes

The owner asked for it on 2026-11-26: "build the route for the thingiverse of via.computer,
made.via.computer". It is the start of roadmap item 18. The host serves this page at
made.via.computer's root (site/vercel.json), from the same build as via.computer, so the page loads
its files from where it is and links the rest of the site at via.computer. Its canonical link is
%MADE%, which site/build.sh fills with the gallery's address. A board is listed when its gates
report says GREEN (item 18's scope guard). Today the boards are the repository's own examples, read
by site/examples.py; boards from other repositories come with the rest of item 18. The words follow
ee-agent-kit/docs/WEBSITE-WRITING.md.
"""

# ruff: noqa: E501 - the page's templates are HTML, with its lines as long as the site's pages'.
from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
sys.path.insert(0, str(SITE))

from frame import REPO, shell  # noqa: E402

from examples import OUT, Example, draw_board, examples, pictures_size, stats  # noqa: E402

MADE = SITE / "made.html"
HOME = "https://via.computer/"  # the rest of the site, from the gallery's own address
SCRIPTS = ["vendor/motion-14.6.0.js", "site.js", "effects.js"]
MAKER = "Team Reagent"  # the examples' makers: the team that wrote them in this repository


def licence() -> str:
    """The examples' licence: the repository's, as the first line of LICENSE names it."""
    return (ROOT / "LICENSE").read_text(encoding="utf-8").splitlines()[0].strip()


def listed(found: list[Example]) -> tuple[list[Example], list[Example]]:
    """The boards the gallery lists, those whose gates report says GREEN, and the rest."""
    green = [ex for ex in found if ex.verdict.startswith("GREEN")]
    return green, [ex for ex in found if ex not in green]


def names(items: list[str]) -> str:
    """Names as a sentence lists them: A, A and B, A, B and C."""
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def card(ex: Example) -> str:
    """A board's card: its picture, its name, its line, who made it under which licence, and its
    verdict. It leads to the board's page on via.computer."""
    board = draw_board(ex.board) if ex.board else None
    picture = OUT / ex.slug / "card.png"
    shot = ""
    if picture.is_file():
        w, h = pictures_size(ex, "card.png")
        shot = f'<div class="shot3d"><img src="examples/{ex.slug}/card.png" width="{w}" height="{h}" loading="lazy" alt="{html.escape(ex.name)} in 3D"></div>'
    facts = stats(ex, board)
    spec = " · ".join(html.escape(s) for s in (facts[0], f"By {MAKER}", licence(), facts[-1]))
    line = ex.tagline[:1].upper() + ex.tagline[1:]
    return (
        f'<a class="proj" href="{HOME}examples/{ex.slug}">{shot}<div><h3>{html.escape(ex.name)}</h3>'
        f'<p>{html.escape(line)}.</p><p class="spec">{spec}</p></div></a>'
    )


def made_page() -> str:
    green, waiting = listed(examples())
    later = ""
    if len(waiting) == 1:
        later = f" {waiting[0].name} isn't here yet, because we haven't seen it pass every check. It'll show up when it does."
    elif waiting:
        later = f" {names([ex.name for ex in waiting])} aren't here yet, because we haven't seen them pass every check. They'll show up when they do."
    body = f"""      <section class="section" aria-labelledby="made-title">
        <div class="wrap">
          <div class="head" data-reveal data-stagger>
            <p class="eyebrow">Gallery</p>
            <h1 class="title" id="made-title">Made with Via</h1>
            <p class="lede">Here are the boards made with Via! Each one passes Via's checks, and its page lets you turn it in 3D, follow every track and read how it came together. The first boards are our own.{later}</p>
          </div>
          <div class="built" data-reveal data-stagger>
            {"".join(card(ex) for ex in green)}
          </div>
        </div>
      </section>

      <section class="section" aria-labelledby="yours-title">
        <div class="wrap">
          <div class="head" data-reveal data-stagger>
            <h2 class="title" id="yours-title">Your board here</h2>
            <p class="lede">We're working on opening this page to everyone's boards. The plan is that you'll add one with a pull request that names your repository, Via's checks run on it, and it shows up here once it passes. It's item 18 on <a class="link" href="{REPO}/blob/main/ee-agent-kit/ROADMAP.md">our roadmap</a>. Until then, we'd like to see what you're making in <a class="link" href="https://discord.reagent-systems.com">our Discord</a>.</p>
            <p class="lede">A board here passed Via's checks on its design files. That doesn't mean anyone has built it or tested it.</p>
          </div>
        </div>
      </section>"""
    return shell(
        "Made with Via",
        "Boards made with Via that pass its checks, each with its board in 3D, every track and how it came together.",
        "",
        "",
        body,
        SCRIPTS,
        home=HOME,
        address="%MADE%/",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="exit 1 when made.html differs from what this writes"
    )
    args = parser.parse_args()
    text = made_page()
    if args.check:
        if MADE.is_file() and MADE.read_text(encoding="utf-8") == text:
            return 0
        print(f"{MADE.relative_to(ROOT)}: not what site/made.py writes; run it again", file=sys.stderr)
        return 1
    MADE.write_text(text, encoding="utf-8")
    print(f"{MADE.relative_to(ROOT)}: {len(text) // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
