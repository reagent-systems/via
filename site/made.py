"""Made with Via: the boards made with Via, served at made.via.computer.

    python3 site/made.py          # write site/made.html
    python3 site/made.py --check  # exit 1 when site/made.html is not what this writes

The owner asked for it on 2026-11-26: "build the route for the thingiverse of via.computer,
made.via.computer", then for Thingiverse's layout in Via's own styling: a bar with the brand, 2
menus, a pill, a button, the search and the way out; a row of orders with a dropdown and filters;
and a grid of cards, each a picture with its dots, the name, a count, a menu, the maker and a state.
Every control does what it says with the boards' own facts (site/made.js): the orders are by parts,
layers, size and boards, the dropdown and the filters pick by layers, category and boards. There
are no likes, no accounts and no uploads (roadmap item 18's scope guard), so none is drawn.

The host serves this page at made.via.computer's root (site/middleware.js) from the same build as
via.computer, so the page loads its files from where it is and links the rest of the site at
via.computer. Its canonical link is %MADE%, which site/build.sh fills with the gallery's address. A
board is listed when its gates report says GREEN. Today the boards are the repository's own
examples, read by site/examples.py. The words follow ee-agent-kit/docs/WEBSITE-WRITING.md.
"""

# ruff: noqa: E501 - the page's templates are HTML, with its lines as long as the site's pages'.
from __future__ import annotations

import argparse
import html
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
sys.path.insert(0, str(SITE))

from frame import LOGO, REPO, shell  # noqa: E402

from examples import OUT, Example, draw_board, examples, pictures_size  # noqa: E402

MADE = SITE / "made.html"
HOME = "https://via.computer/"  # the rest of the site, from the gallery's own address
GALLERY = "https://made.via.computer/"  # the gallery's own address, its brand's link
DISCORD = "https://discord.reagent-systems.com"
SCRIPTS = ["site.js", "made.js"]
MAKER = "Team Reagent"  # the examples' makers: the team that wrote them in this repository
# Each example's category, by its page's name: what the board is, as its README says.
CATEGORY = {
    "hush": "Audio",
    "lark": "Lighting",
    "herald": "Alarms",
    "signet": "Wearables",
    "wyvern": "Dev boards",
    "basalt": "Motherboards",
    "rosetta": "Controllers",
}
# A card's pictures, as --pictures writes them: the first is shown, the dots pick the others.
PICTURES = (("card.png", "In 3D"), ("top.png", "The front"), ("bottom.png", "The back"))


def icon(body: str) -> str:
    return f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{body}</svg>'


CHEVRON = icon('<path d="M6 9l6 6 6-6"/>')
SEARCH = icon('<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>')
GRID = icon(
    '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>'
)
CHIP = icon(
    '<rect x="7" y="7" width="10" height="10" rx="1.5"/><path d="M10 7V4M14 7V4M10 20v-3M14 20v-3M7 10H4M7 14H4M20 10h-3M20 14h-3"/>'
)
LAYERS = icon('<path d="M12 4l8 4-8 4-8-4 8-4z"/><path d="M4 12l8 4 8-4"/><path d="M4 16l8 4 8-4"/>')
SIZE = icon('<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>')
BOARDS = icon(
    '<rect x="3" y="8" width="13" height="12" rx="2"/><path d="M8 8V6a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-3"/>'
)
FUNNEL = icon('<path d="M4 5h16l-6 7.5V19l-4-2v-4.5L4 5z"/>')
KEBAB = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="12" cy="5" r="1.7"/><circle cx="12" cy="12" r="1.7"/><circle cx="12" cy="19" r="1.7"/></svg>'
MOON = icon('<path d="M20.2 14.6A8.4 8.4 0 1 1 9.4 3.8a6.6 6.6 0 0 0 10.8 10.8Z"/>').replace(
    "<svg ", '<svg class="moon" ', 1
)
SUN = icon(
    '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>'
).replace("<svg ", '<svg class="sun" ', 1)
ORDERS = (
    ("all", GRID, "All Boards"),
    ("parts", CHIP, "Most Parts"),
    ("layers", LAYERS, "Most Layers"),
    ("area", SIZE, "Biggest"),
    ("boards", BOARDS, "Most Boards"),
)


@dataclass
class Thing:
    """A listed board, with the facts the gallery orders and picks it by."""

    ex: Example
    category: str
    parts: int
    layers: int
    area: float  # mm², every board of it
    boards: int

    @property
    def page(self) -> str:
        return f"{HOME}examples/{self.ex.slug}"


def thing(ex: Example) -> Thing:
    drawn = [draw_board(path) for _, path in ex.boards] or ([draw_board(ex.board)] if ex.board else [])
    return Thing(
        ex=ex,
        category=CATEGORY.get(ex.slug, "Other"),
        parts=sum(b.parts for b in drawn),
        layers=max((b.layers for b in drawn), default=0),
        area=round(sum(b.width * b.height for b in drawn), 1),
        boards=len(drawn),
    )


def listed(found: list[Example]) -> tuple[list[Example], list[Example]]:
    """The boards the gallery lists, those whose gates report says GREEN, and the rest."""
    green = [ex for ex in found if ex.verdict.startswith("GREEN")]
    return green, [ex for ex in found if ex not in green]


def names(items: list[str]) -> str:
    """Names as a sentence lists them: A, A and B, A, B and C."""
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def card(t: Thing, order: int) -> str:
    """A board's card: its pictures with a dot for each, its name, its count of parts, its menu, its
    maker and its state. The picture and the name lead to the board's page on via.computer."""
    ex = t.ex
    name = html.escape(ex.name)
    shots = [(file, label) for file, label in PICTURES if (OUT / ex.slug / file).is_file()]
    images, dots = [], []
    for i, (file, label) in enumerate(shots):
        w, h = pictures_size(ex, file)
        lazy = ' loading="lazy"' if i else ""
        hide = " hidden" if i else ""
        images.append(f'<img src="examples/{ex.slug}/{file}" width="{w}" height="{h}" alt=""{lazy}{hide}>')
        dots.append(
            f'<button type="button" aria-pressed="{"true" if i == 0 else "false"}" aria-label="{label}"></button>'
        )
    words = " ".join((ex.name, ex.tagline, t.category, MAKER)).lower()
    on = f" on {t.boards} boards" if t.boards > 1 else ""
    verdict = html.escape(ex.verdict)
    short = html.escape(re.sub(r"\s*\(.*?\)", "", ex.verdict).split(" ")[0])
    data = (
        f'data-order="{order}" data-text="{html.escape(words)}" data-category="{html.escape(t.category)}" '
        f'data-parts="{t.parts}" data-layers="{t.layers}" data-area="{t.area}" data-boards="{t.boards}"'
    )
    return f"""            <article class="thing" {data}>
              <div class="thing-pic">
                <a href="{t.page}" tabindex="-1" aria-hidden="true">{"".join(images)}</a>
                <span class="thing-ok" title="{verdict}"></span>
                <div class="thing-dots" role="group" aria-label="Pictures of {name}">{"".join(dots)}</div>
              </div>
              <div class="thing-head">
                <h2><a href="{t.page}">{name}</a></h2>
                <span class="thing-count" title="{t.parts} parts{on}">{t.parts}{CHIP}</span>
                <details class="thing-more">
                  <summary aria-label="More about {name}">{KEBAB}</summary>
                  <ul>
                    <li><a href="{t.page}">Its page</a></li>
                    <li><a href="{REPO}/tree/main/{ex.rel}">Its files on GitHub</a></li>
                    <li><button type="button" data-copy-link="{t.page}">Copy its link</button></li>
                  </ul>
                </details>
              </div>
              <div class="thing-by">
                <span class="thing-face" aria-hidden="true">TR</span>
                <span class="thing-maker">{MAKER}</span>
                <span class="thing-state" title="{verdict}">{html.escape(ex.version)} · <b>{short}</b></span>
              </div>
            </article>"""


def bar(things: list[Thing]) -> str:
    """The gallery's bar: the brand, the 2 menus, the pill, the button, the search and the way out."""
    counts: dict[str, int] = {}
    for t in things:
        counts[t.category] = counts.get(t.category, 0) + 1
    categories = "\n".join(
        f'                <li><button type="button" data-category="{html.escape(c)}" aria-pressed="false">{html.escape(c)} <span>{n}</span></button></li>'
        for c, n in sorted(counts.items())
    )
    logo = LOGO.replace(" data-logo", "")
    return f"""    <header class="made-bar">
      <div class="made-bar-in">
        <a class="made-brand" href="{GALLERY}" aria-label="Made with Via, all the boards">
          {logo}
        </a>
        <nav class="made-nav" aria-label="Made with Via">
          <details class="made-drop">
            <summary>Community{CHEVRON}</summary>
            <ul>
              <li><a href="{DISCORD}">Our Discord</a></li>
              <li><a href="{HOME}blog">Blog</a></li>
              <li><a href="{HOME}feedback">Feedback</a></li>
              <li><a href="{REPO}">GitHub</a></li>
            </ul>
          </details>
          <details class="made-drop">
            <summary>Categories{CHEVRON}</summary>
            <ul>
                <li><button type="button" data-category="" aria-pressed="true">Every category <span>{len(things)}</span></button></li>
{categories}
            </ul>
          </details>
          <button class="made-pill" type="button" data-multi aria-pressed="false">Multi-board <span class="made-new">New</span></button>
          <a class="made-cta" href="#add">Add your board</a>
        </nav>
        <form class="made-search" role="search" data-search>
          <input type="search" name="q" placeholder="Search" aria-label="Search the boards" autocomplete="off">
          <button type="submit" aria-label="Search">{SEARCH}</button>
        </form>
        <div class="made-end">
          <a class="made-out" href="{HOME}guide">Get Via</a>
          <a class="made-home" href="{HOME}">via.computer</a>
          <button class="icon-btn" type="button" data-theme-toggle aria-pressed="false" aria-label="Dark theme">
            {MOON}
            {SUN}
          </button>
        </div>
      </div>
    </header>
"""


def made_page() -> str:
    green, waiting = listed(examples())
    things = [thing(ex) for ex in green]
    orders = "\n".join(
        f'            <button type="button" data-sort="{key}" aria-pressed="{"true" if key == "all" else "false"}">{svg}{label}</button>'
        for key, svg, label in ORDERS
    )
    layers = "".join(f'<option value="{n}">{n} layers</option>' for n in sorted({t.layers for t in things}))
    counts: dict[str, int] = {}
    for t in things:
        counts[t.category] = counts.get(t.category, 0) + 1
    chips = "".join(
        f'<button type="button" data-category="{html.escape(c)}" aria-pressed="false">{html.escape(c)}</button>'
        for c in sorted(counts)
    )
    later = ""
    if len(waiting) == 1:
        later = f" {waiting[0].name} isn't here yet, because we haven't seen it pass every check. It'll show up when it does."
    elif waiting:
        later = f" {names([ex.name for ex in waiting])} aren't here yet, because we haven't seen them pass every check. They'll show up when they do."
    body = f"""      <h1 class="sr-only">Made with Via</h1>
      <div class="made-tabs">
        <div class="made-tabs-in">
          <div class="made-sorts" role="group" aria-label="Order">
{orders}
          </div>
          <span class="made-rule" aria-hidden="true"></span>
          <label class="made-select">
            <span class="sr-only">Layers</span>
            <select data-layers><option value="">Any layers</option>{layers}</select>{CHEVRON}
          </label>
          <button class="made-filters" type="button" aria-expanded="false" aria-controls="made-panel">Filters{FUNNEL}</button>
        </div>
        <div class="made-panel" id="made-panel" hidden>
          <div class="made-panel-in" role="group" aria-label="Categories">
            <button type="button" data-category="" aria-pressed="true">Every category</button>{chips}
            <button type="button" data-multi aria-pressed="false">Multi-board</button>
          </div>
        </div>
      </div>

      <div class="made-wrap">
        <div class="made-grid" data-grid>
{chr(10).join(card(t, i) for i, t in enumerate(things))}
        </div>
        <div class="made-none" data-none hidden>
          <p>No board here matches that.</p>
          <button type="button" data-reset>Show every board</button>
        </div>
      </div>

      <section class="made-add" id="add" aria-labelledby="add-title">
        <div class="made-wrap">
          <h2 id="add-title">Adding your board</h2>
          <p>We're working on opening this page to everyone's boards. The plan is that you'll add one with a pull request that names your repository, Via's checks run on it, and it shows up here once it passes. It's item 18 on <a class="link" href="{REPO}/blob/main/ee-agent-kit/ROADMAP.md">our roadmap</a>. Until then, we'd like to see what you're making in <a class="link" href="{DISCORD}">our Discord</a>.</p>
          <p>Every board here so far is one of ours.{later}</p>
          <p>A board here passed Via's checks on its design files. That doesn't mean anyone has built it or tested it.</p>
        </div>
      </section>"""
    return shell(
        "Made with Via",
        "Boards made with Via that pass its checks: search them, sort them by parts, layers and size, and open each one in 3D.",
        "",
        "",
        body,
        SCRIPTS,
        home=HOME,
        address="%MADE%/",
        header=bar(things),
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
