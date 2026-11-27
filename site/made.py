"""Made with Via: the boards made with Via, served at made.via.computer.

    python3 site/made.py          # write site/made.html
    python3 site/made.py --check  # exit 1 when site/made.html is not what this writes

The owner asked for it on 2026-11-26: "build the route for the thingiverse of via.computer,
made.via.computer", then for Thingiverse's layout in Via's own styling: a bar with the brand, 2
menus, a pill, a button, the search and the way out; a row of orders with a dropdown and filters;
and a grid of cards, each a picture with its dots, the name, a count, a menu, the maker and a state.
Every control does what it says with the boards' own facts (site/made.js): the orders are by likes,
age, parts, layers and size, the dropdown and the filters pick by layers, category and boards.

Then, at the owner's word ("im asking you already to implement it"): a person logs in with Google,
Microsoft or GitHub (the owner's word, 2026-11-27),
likes boards, adds a board from 1 of their own public repositories and manages theirs under "My
boards" (site/api/_made.js). A board added there is listed once Via's checks say GREEN and an admin
has looked at it; made.js draws its card from /api/made like the examples' cards here. This script
also writes site/api/_examples.js, the examples' ids a like may name.

Each board has a page of its own, at made.via.computer/b/<name> (site/middleware.js): Thingiverse's
page of a thing, at the owner's word ("the boards on the made.via.computer should have their own
pages. like a thingiverse page. This is where the order from jlcpcb button/dropdown would go"). An
example's page is written here, site/made/<name>.html; a board someone added has 1 page,
site/made/board.html, that made.js fills from /api/made. The Order menu names each fab as its own
pages say it takes a board, read on 2026-11-26: OSH Park takes the .kicad_pcb as it is from a link
(docs.oshpark.com/tips+tricks/api/ and /design-tools/kicad/), and JLCPCB and PCBWay take a zip of the
Gerbers on their own upload page, which Via's check workflow makes (.github/workflows/made-check.yml).

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
import json
import re
import sys
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
sys.path.insert(0, str(SITE))

from frame import GH_PATH, LOGO, REPO, shell  # noqa: E402

from examples import GATES, OUT, Example, draw_board, examples, inline, mm, pictures_size  # noqa: E402

MADE = SITE / "made.html"
PAGES = SITE / "made"  # each example's page, and the 1 page of the boards people add
LIKEABLE = SITE / "api" / "_examples.js"
RAW = "https://raw.githubusercontent.com/reagent-systems/via/main/"
OSHPARK = "https://oshpark.com/import?url="  # docs.oshpark.com/tips+tricks/api/, read 2026-11-26
# The fabs that take a zip of the Gerbers on their own page: their upload page and what it takes, as
# each says (jlcpcb.com/help/article/how-to-generate-gerber-and-drill-files-in-kicad-9 and
# pcbway.com/QuickOrderOnline.aspx, read 2026-11-26).
FABS = (
    ("JLCPCB", "https://cart.jlcpcb.com/quote", "Takes 1 zip of the Gerbers and both drill files."),
    (
        "PCBWay",
        "https://www.pcbway.com/QuickOrderOnline.aspx",
        "Takes a .zip, .rar or .7z of the Gerbers, up to 50 MB.",
    ),
)
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
CHIP = icon(
    '<rect x="7" y="7" width="10" height="10" rx="1.5"/><path d="M10 7V4M14 7V4M10 20v-3M14 20v-3M7 10H4M7 14H4M20 10h-3M20 14h-3"/>'
)
LAYERS = icon('<path d="M12 4l8 4-8 4-8-4 8-4z"/><path d="M4 12l8 4 8-4"/><path d="M4 16l8 4 8-4"/>')
SIZE = icon('<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>')
HEART = icon(
    '<path d="M12 20s-7.5-4.6-7.5-10.1A4.4 4.4 0 0 1 12 7.4a4.4 4.4 0 0 1 7.5 2.5C19.5 15.4 12 20 12 20z"/>'
)
FIRE = icon(
    '<path d="M12 21c-3.9 0-7-2.8-7-6.6 0-4.2 4-6.4 4.5-10.4 2.6 1.7 4.2 4 4.4 6.4.8-.6 1.4-1.6 1.6-2.7 1.6 1.5 2.5 3.9 2.5 6.4 0 3.9-2.6 6.9-6 6.9z"/>'
)
SPROUT = icon(
    '<path d="M12 21v-9"/><path d="M12 12c0-4 3-6.5 7.5-6.5 0 4-3 6.5-7.5 6.5z"/><path d="M12 14.5c0-3.3-2.5-5.5-6.5-5.5 0 3.3 2.5 5.5 6.5 5.5z"/>'
)
BACK = icon('<path d="M15 5l-7 7 7 7"/>')
FORWARD = icon('<path d="M9 5l7 7-7 7"/>')
DOWNLOAD = icon('<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>')
SHARE = icon(
    '<circle cx="18" cy="5" r="2.5"/><circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="19" r="2.5"/><path d="M8.2 10.8l7.6-4.4M8.2 13.2l7.6 4.4"/>'
)
OUTSIDE = icon('<path d="M14 5h5v5M19 5l-8 8M17 14v5H5V7h5"/>')
# The 3 ways in, each with its own mark, in the owner's order: Google, Microsoft, GitHub.
WAYS_IN = (
    (
        "google",
        "Google",
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.5h6.5a5.6 5.6 0 0 1-2.4 3.6v3h3.9c2.3-2.1 3.5-5.2 3.5-8.8z"/>'
        '<path fill="#34A853" d="M12 24c3.2 0 6-1.1 8-2.9l-3.9-3c-1.1.7-2.5 1.2-4.1 1.2-3.1 0-5.8-2.1-6.7-5H1.3v3.1A12 12 0 0 0 12 24z"/>'
        '<path fill="#FBBC05" d="M5.3 14.3a7.2 7.2 0 0 1 0-4.6V6.6h-4a12 12 0 0 0 0 10.8l4-3.1z"/>'
        '<path fill="#EA4335" d="M12 4.8c1.8 0 3.3.6 4.6 1.8l3.4-3.4A11.6 11.6 0 0 0 12 0 12 12 0 0 0 1.3 6.6l4 3.1c.9-2.9 3.6-4.9 6.7-4.9z"/></svg>',
    ),
    (
        "microsoft",
        "Microsoft",
        '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#F25022" d="M1 1h10.5v10.5H1z"/><path fill="#7FBA00" d="M12.5 1H23v10.5H12.5z"/>'
        '<path fill="#00A4EF" d="M1 12.5h10.5V23H1z"/><path fill="#FFB900" d="M12.5 12.5H23V23H12.5z"/></svg>',
    ),
    (
        "github",
        "GitHub",
        f'<svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="{GH_PATH}"/></svg>',
    ),
)
# The profile mark in the bar, at the owner's word (2026-11-27: "I need a little profile icon in the
# header"): a person in a circle, which opens Log In; once logged in, the person's picture takes its place.
PERSON = icon(
    '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="10" r="3.2"/><path d="M6.6 19.2a6.5 6.5 0 0 1 10.8 0"/>'
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
    ("likes", FIRE, "Popular Boards"),
    ("fresh", SPROUT, "Fresh Boards"),
    ("parts", CHIP, "Most Parts"),
    ("layers", LAYERS, "Most Layers"),
    ("area", SIZE, "Biggest"),
)
# The categories a person picks from when they add a board: site/api/_made.js holds the same list.
CATEGORIES = (
    "Audio",
    "Lighting",
    "Wearables",
    "Dev boards",
    "Motherboards",
    "Alarms",
    "Controllers",
    "Power",
    "Sensors",
    "Radio",
    "Other",
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

    drawn: list = None  # each board's drawing: its size, layers, parts, tracks and vias

    @property
    def page(self) -> str:
        """The board's page here."""
        return f"/b/{self.ex.slug}"

    @property
    def story(self) -> str:
        """The board's whole page on via.computer: the 3D view, every track and how it came together."""
        return f"{HOME}examples/{self.ex.slug}"

    @property
    def files(self) -> list[tuple[str, Path]]:
        """Each board's name and its .kicad_pcb: 1 for a board alone, 1 for each of several."""
        return list(self.ex.boards) or ([(self.ex.name, self.ex.board)] if self.ex.board else [])


def thing(ex: Example) -> Thing:
    drawn = [draw_board(path) for _, path in ex.boards] or ([draw_board(ex.board)] if ex.board else [])
    return Thing(
        ex=ex,
        category=CATEGORY.get(ex.slug, "Other"),
        parts=sum(b.parts for b in drawn),
        layers=max((b.layers for b in drawn), default=0),
        area=round(sum(b.width * b.height for b in drawn), 1),
        boards=len(drawn),
        drawn=drawn,
    )


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


def card(t: Thing, order: int, up: str = "") -> str:
    """A board's card: its pictures with a dot for each, its name, its likes, its menu, its maker and
    its state. The picture and the name lead to the board's page here. `up` leads to the site's root
    from the page the card is on."""
    ex = t.ex
    name = html.escape(ex.name)
    shots = [(file, label) for file, label in PICTURES if (OUT / ex.slug / file).is_file()]
    images, dots = [], []
    for i, (file, label) in enumerate(shots):
        w, h = pictures_size(ex, file)
        lazy = ' loading="lazy"' if i else ""
        hide = " hidden" if i else ""
        images.append(
            f'<img src="{up}examples/{ex.slug}/{file}" width="{w}" height="{h}" alt=""{lazy}{hide}>'
        )
        dots.append(
            f'<button type="button" aria-pressed="{"true" if i == 0 else "false"}" aria-label="{label}"></button>'
        )
    words = " ".join((ex.name, ex.tagline, t.category, MAKER)).lower()
    on = f" on {t.boards} boards" if t.boards > 1 else ""
    verdict = html.escape(ex.verdict)
    short = html.escape(re.sub(r"\s*\(.*?\)", "", ex.verdict).split(" ")[0])
    data = (
        f'data-id="ex-{ex.slug}" data-order="{order}" data-text="{html.escape(words)}" data-category="{html.escape(t.category)}" '
        f'data-parts="{t.parts}" data-layers="{t.layers}" data-area="{t.area}" data-boards="{t.boards}" data-likes="0" data-fresh="0"'
    )
    return f"""            <article class="thing" {data}>
              <div class="thing-pic">
                <a href="{t.page}" tabindex="-1" aria-hidden="true">{"".join(images)}</a>
                <span class="thing-ok" title="{verdict}"></span>
                <div class="thing-dots" role="group" aria-label="Pictures of {name}">{"".join(dots)}</div>
              </div>
              <div class="thing-head">
                <h2><a href="{t.page}">{name}</a></h2>
                <button class="thing-like" type="button" data-like="ex-{ex.slug}" aria-pressed="false" aria-label="Like {name}" title="{t.parts} parts{on}"><span data-count>0</span>{HEART}</button>
                <details class="thing-more">
                  <summary aria-label="More about {name}">{KEBAB}</summary>
                  <ul>
                    <li><a href="{t.page}">Its page</a></li>
                    <li><a href="{t.story}">Its story on via.computer</a></li>
                    <li><a href="{REPO}/tree/main/{ex.rel}">Its files on GitHub</a></li>
                    <li><button type="button" data-copy-link="{GALLERY}b/{ex.slug}">Copy its link</button></li>
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
    options = "".join(f'<option value="{c}">{c}</option>' for c in CATEGORIES)
    ways = "\n".join(
        f'            <a class="made-login-with" href="/api/auth?do=login&amp;with={key}" data-with="{key}" hidden>{mark}Log in with {name}</a>'
        for key, name, mark in WAYS_IN
    )
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
          <button class="made-login" type="button" data-login aria-label="Log in" title="Log in" hidden>{PERSON}</button>
          <details class="made-drop made-me" data-me hidden>
            <summary aria-label="Your account"><img data-avatar alt="" width="32" height="32"></summary>
            <ul>
              <li><a href="/" data-my-profile>My profile</a></li>
              <li><button type="button" data-open-mine>My boards</button></li>
              <li><button type="button" data-open-add>Add a board</button></li>
              <li><button type="button" data-logout>Log out</button></li>
            </ul>
          </details>
          <button class="icon-btn" type="button" data-theme-toggle aria-pressed="false" aria-label="Dark theme">
            {MOON}
            {SUN}
          </button>
        </div>
      </div>
      <dialog class="made-dialog made-login-dialog" id="made-login" aria-labelledby="made-login-title">
        <div class="made-dialog-head">
          <h2 id="made-login-title">Log in</h2>
          <button type="button" class="made-quiet" data-close>Close</button>
        </div>
        <div class="made-login-list">
{ways}
        </div>
      </dialog>
      <dialog class="made-dialog" id="made-add" aria-labelledby="made-add-title">
        <form class="made-form" data-add-form novalidate>
          <h2 id="made-add-title" data-add-title>Add your board</h2>
          <label data-source>Repository<input name="repo" placeholder="you/your-board" autocomplete="off" spellcheck="false"></label>
          <div class="made-form-row" data-source>
            <label>Folder <small>if it isn't at the top</small><input name="path" placeholder="boards/my-board" autocomplete="off" spellcheck="false"></label>
            <label>Branch <small>if it isn't the default</small><input name="ref" placeholder="main" autocomplete="off" spellcheck="false"></label>
          </div>
          <label>Name<input name="name" maxlength="60" autocomplete="off"></label>
          <label>What it is<textarea name="summary" maxlength="280" rows="3"></textarea></label>
          <div class="made-form-row">
            <label>Category<select name="category">{options}</select></label>
            <label>License <small>if it isn't the repository's</small><input name="licence" maxlength="60" autocomplete="off"></label>
          </div>
          <p class="made-error" data-error role="alert" hidden></p>
          <div class="made-form-end">
            <button type="button" class="made-quiet" data-close>Cancel</button>
            <button type="submit" class="made-go" data-add-go>Add it</button>
          </div>
        </form>
      </dialog>

      <dialog class="made-dialog made-dialog-wide" id="made-mine" aria-labelledby="made-mine-title">
        <div class="made-dialog-head">
          <h2 id="made-mine-title">My boards</h2>
          <button type="button" class="made-quiet" data-close>Close</button>
        </div>
        <div class="made-mine" data-mine-list></div>
        <div data-review hidden>
          <h3>Waiting for your review</h3>
          <div class="made-mine" data-review-list></div>
        </div>
      </dialog>
    </header>
"""


def made_page(green: list[Example], waiting: list[Example], things: list[Thing]) -> str:
    orders = "\n".join(
        f'            <button type="button" data-sort="{key}" aria-pressed="{"true" if key == "likes" else "false"}">{svg}{label}</button>'
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
          <p>You log in with GitHub and add a board from one of your public repositories. Logging in with Google or Microsoft lets you like boards. Via's checks run on it in GitHub Actions, and once it passes and we've had a look, it shows up here with the others. You can hide it, check it again or take it down from "My boards". We'd also like to see what you're making in <a class="link" href="{DISCORD}">our Discord</a>.</p>
          <p>The first boards here are ours.{later}</p>
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


# ---------------------------------------------------------------- a board's own page


def order_menu(board_id: str, kicad: list[tuple[str, str]]) -> str:
    """The Order menu: each fab as its own pages say it takes a board. `kicad` is each board's name
    and its .kicad_pcb's address, for OSH Park's link; the Gerbers' link shows once made.js finds the
    zip the check workflow made."""
    if len(kicad) == 1:
        osh = f'<a class="made-go" href="{html.escape(OSHPARK + urllib.parse.quote(kicad[0][1], safe=""))}" target="_blank" rel="noopener" data-osh>Order at OSH Park{OUTSIDE}</a>'
    else:
        osh = "".join(
            f'<a class="made-quiet" href="{html.escape(OSHPARK + urllib.parse.quote(url, safe=""))}" target="_blank" rel="noopener" data-osh>{html.escape(name)}{OUTSIDE}</a>'
            for name, url in kicad
        )
    several = f" This is {len(kicad)} boards, so each is its own order." if len(kicad) > 1 else ""
    fabs = "".join(
        f"""
              <div class="made-fab">
                <div class="made-fab-name"><b>{name}</b><small>{says}</small></div>
                <div class="made-fab-do">
                  <a class="made-quiet" href="/api/made?do=file&amp;id={html.escape(board_id)}&amp;kind=gerbers" data-gerbers hidden>{DOWNLOAD}Gerbers</a>
                  <a class="made-go" href="{url}" target="_blank" rel="noopener">Open {name}{OUTSIDE}</a>
                </div>
              </div>"""
        for name, url, says in FABS
    )
    return f"""<details class="made-order" data-order>
            <summary class="made-order-go">Order this board{CHEVRON}</summary>
            <div class="made-order-menu">
              <div class="made-fab">
                <div class="made-fab-name"><b>OSH Park</b><small>Takes the KiCad board file as it is, so its order page opens with this board in it.{several}</small></div>
                <div class="made-fab-do" data-osh-list>{osh}</div>
              </div>{fabs}
            </div>
          </details>"""


def viewer(name: str, shots: list[tuple[str, int, int, str]]) -> str:
    """The big picture with arrows and a download, and a column of thumbnails that pick it."""
    if not shots:
        return f'<div class="made-viewer" data-viewer><div class="made-stage"><span class="thing-blank">{CHIP}</span></div></div>'
    src, w, h, label = shots[0]
    thumbs = "".join(
        f'<button type="button" aria-pressed="{"true" if i == 0 else "false"}" aria-label="{html.escape(lab)}" data-src="{html.escape(s)}" data-alt="{html.escape(f"{name}: {lab}")}"><img src="{html.escape(s)}" width="{ww}" height="{hh}" alt="" loading="lazy"></button>'
        for i, (s, ww, hh, lab) in enumerate(shots)
    )
    arrows = (
        f'<button class="made-stage-go made-stage-prev" type="button" data-step="-1" aria-label="The picture before">{BACK}</button>'
        f'<button class="made-stage-go made-stage-next" type="button" data-step="1" aria-label="The next picture">{FORWARD}</button>'
        if len(shots) > 1
        else ""
    )
    return f"""<div class="made-viewer" data-viewer>
            <div class="made-stage">
              <img src="{html.escape(src)}" width="{w}" height="{h}" alt="{html.escape(f"{name}: {label}")}" data-stage>
              {arrows}
              <a class="made-stage-tool" href="{html.escape(src)}" download data-stage-download aria-label="Download this picture">{DOWNLOAD}</a>
            </div>
            <div class="made-thumbs" role="group" aria-label="Pictures of {html.escape(name)}">{thumbs}</div>
          </div>"""


def tabs(name: str, files: int, checks: int) -> str:
    items = (("details", "Details", None), ("files", "Files", files), ("checks", "Checks", checks))
    return "".join(
        f'<button type="button" role="tab" id="tab-{key}" aria-selected="{"true" if i == 0 else "false"}" aria-controls="panel-{key}"{"" if i == 0 else ' tabindex="-1"'}>{label}{"" if n is None else f" <span>{n}</span>"}</button>'
        for i, (key, label, n) in enumerate(items)
    )


def files_rows(ex: Example) -> list[tuple[str, str, str, str]]:
    """Each file a person would take: its name, what it is, its page on GitHub and its download."""
    folder = ROOT / ex.rel
    rows = []
    kinds = (
        ("*.kicad_pcb", "The board, for KiCad and for OSH Park"),
        ("*.kicad_sch", "The schematic"),
        ("*.kicad_pro", "The KiCad project"),
    )
    places = [folder] + [path.parent for _, path in ex.boards]
    for place in places:
        for pattern, what in kinds:
            for f in sorted(place.glob(pattern)):
                rel = f.relative_to(ROOT).as_posix()
                rows.append((f.relative_to(folder).as_posix(), what, f"{REPO}/blob/main/{rel}", RAW + rel))
    for extra, what in (
        ("design.py", "The design file Via builds the board from"),
        ("README.md", "How it came together"),
    ):
        f = folder / extra
        if f.is_file():
            rel = f.relative_to(ROOT).as_posix()
            rows.append((extra, what, f"{REPO}/blob/main/{rel}", RAW + rel))
    return rows


def board_page(t: Thing, others: list[Thing], top: str) -> str:
    """An example's page here: Thingiverse's page of a thing, in the site's styling."""
    ex = t.ex
    name = html.escape(ex.name)
    shots = []
    for file, label in PICTURES:
        if (OUT / ex.slug / file).is_file():
            w, h = pictures_size(ex, file)
            shots.append((f"../examples/{ex.slug}/{file}", w, h, label))
    kicad = [
        (folder if len(t.files) > 1 else ex.name, RAW + path.relative_to(ROOT).as_posix())
        for folder, path in t.files
    ]
    rows = files_rows(ex)
    files = "".join(
        f'<tr><td><code>{html.escape(n)}</code></td><td>{html.escape(what)}</td><td class="made-file-do"><a class="made-quiet" href="{html.escape(view)}">View</a><a class="made-quiet" href="{html.escape(raw)}" download>{DOWNLOAD}Download</a></td></tr>'
        for n, what, view, raw in rows
    )
    gerbers = f'<tr data-gerbers-row hidden><td><code>{html.escape(ex.slug)}-gerbers.zip</code></td><td>The Gerbers and drill files, made by Via\'s check, for JLCPCB and PCBWay</td><td class="made-file-do"><a class="made-quiet" href="/api/made?do=file&amp;id=ex-{ex.slug}&amp;kind=gerbers" download>{DOWNLOAD}Download</a></td></tr>'
    if ex.checks:
        checks = "".join(
            f'<tr><td>{html.escape(GATES.get(g, g))}</td><td class="made-check-{html.escape(s)}">{html.escape(s)}</td><td>{html.escape(summary)}</td></tr>'
            for g, s, summary in ex.checks
        )
        checks_table = f'<table class="made-table"><thead><tr><th>Check</th><th>Result</th><th>What it found</th></tr></thead><tbody>{checks}</tbody></table>'
        count = len(ex.checks)
    else:
        rows_b = "".join(
            f'<tr><td><code>{html.escape(b)}</code></td><td class="made-check-{"pass" if v.startswith("GREEN") else "fail"}">{html.escape(v)}</td></tr>'
            for b, v in ex.per_board
        )
        checks_table = f'<table class="made-table"><thead><tr><th>Board</th><th>Verdict</th></tr></thead><tbody>{rows_b}</tbody></table>'
        count = len(ex.per_board)
    facts_rows = "".join(
        f"<tr><td><code>{html.escape(folder)}</code></td><td>{mm(b.width)} × {mm(b.height)} mm</td><td>{b.layers}</td><td>{b.parts}</td><td>{b.segments:,}</td><td>{b.vias:,}</td></tr>"
        for (folder, _), b in zip(t.files, t.drawn, strict=False)
    )
    facts = f'<table class="made-table"><thead><tr><th>Board</th><th>Size</th><th>Layers</th><th>Parts</th><th>Track segments</th><th>Vias</th></tr></thead><tbody>{facts_rows}</tbody></table>'
    line = ex.tagline[:1].upper() + ex.tagline[1:]
    more = "\n".join(card(o, i, "../") for i, o in enumerate(others))
    body = f"""      <div class="made-thing-wrap" data-thing="ex-{ex.slug}">
        <article class="made-thing">
          <header class="made-thing-top">
            <a class="made-back" href="/" aria-label="All the boards">{BACK}</a>
            <span class="thing-face" aria-hidden="true">TR</span>
            <div class="made-thing-title">
              <h1>{name}</h1>
              <p><span>{MAKER}</span><span>{html.escape(ex.version)}</span><span>{html.escape(licence())}</span><span class="made-thing-ok">{html.escape(ex.verdict)}</span></p>
            </div>
            {order_menu(f"ex-{ex.slug}", kicad)}
          </header>
          {viewer(ex.name, shots)}
        </article>
        <aside class="made-rail" aria-label="{name}">
          <button class="made-rail-btn" type="button" data-like="ex-{ex.slug}" aria-pressed="false" aria-label="Like {name}">{HEART}<span class="made-badge" data-count>0</span></button>
          <button class="made-rail-btn" type="button" data-share="{GALLERY}b/{ex.slug}" data-title="{name}" aria-label="Share {name}">{SHARE}</button>
        </aside>
      </div>

      <div class="made-thing-body">
        <div class="made-tabs-bar" role="tablist" aria-label="About {name}">{tabs(ex.name, len(rows), count)}</div>
        <section class="made-tab" id="panel-details" role="tabpanel" aria-labelledby="tab-details">
          <nav class="made-tab-side" aria-label="Details"><a href="#summary">Summary</a><a href="#the-board">The board</a><a href="#its-story">Its story</a></nav>
          <div class="made-tab-main">
            <h2 id="summary">Summary</h2>
            <p>{html.escape(line)}.</p>
            <p>{inline(ex.intro, ex.rel)}</p>
            <h2 id="the-board">The board</h2>
            {facts}
            <h2 id="its-story">Its story</h2>
            <p>Its page on via.computer lets you turn it in 3D, follow every track and read how it came together, step by step. <a class="link" href="{t.story}">{name} on via.computer</a></p>
          </div>
        </section>
        <section class="made-tab" id="panel-files" role="tabpanel" aria-labelledby="tab-files" hidden>
          <div class="made-tab-main made-tab-wide">
            <table class="made-table made-files"><thead><tr><th>File</th><th>What it is</th><th></th></tr></thead><tbody>{gerbers}{files}</tbody></table>
          </div>
        </section>
        <section class="made-tab" id="panel-checks" role="tabpanel" aria-labelledby="tab-checks" hidden>
          <div class="made-tab-main made-tab-wide">
            <p>Via's checks on version {html.escape(ex.version)}: <b class="made-thing-ok">{html.escape(ex.verdict)}</b>.</p>
            {checks_table}
          </div>
        </section>
      </div>

      <section class="made-more" aria-labelledby="more-title">
        <div class="made-wrap">
          <h2 id="more-title">More boards</h2>
          <div class="made-grid" data-grid>
{more}
          </div>
        </div>
      </section>"""
    return shell(
        f"{ex.name} · Made with Via",
        f"{line}. {ex.name} is made with Via, and its files pass Via's checks.",
        "",
        "../",
        body,
        SCRIPTS,
        home=HOME,
        address=f"%MADE%/b/{ex.slug}",
        header=top,
    )


def added_page(things: list[Thing], top: str) -> str:
    """The page of a board someone added: 1 page for all of them, which made.js fills from /api/made
    by the name in its address (made.via.computer/b/<id>)."""
    more = "\n".join(card(o, i, "../") for i, o in enumerate(things))
    body = f"""      <div class="made-thing-wrap" data-thing="" data-added hidden>
        <article class="made-thing">
          <header class="made-thing-top">
            <a class="made-back" href="/" aria-label="All the boards">{BACK}</a>
            <img class="thing-face" data-avatar alt="" width="40" height="40">
            <div class="made-thing-title">
              <h1 data-name></h1>
              <p><span data-maker></span><span data-licence></span><span class="made-thing-ok" data-verdict></span></p>
            </div>
            {order_menu("", [])}
          </header>
          <div class="made-viewer" data-viewer><div class="made-stage" data-stage-box></div></div>
        </article>
        <aside class="made-rail">
          <button class="made-rail-btn" type="button" data-like="" aria-pressed="false" aria-label="Like this board">{HEART}<span class="made-badge" data-count>0</span></button>
          <button class="made-rail-btn" type="button" data-share="" aria-label="Share this board">{SHARE}</button>
        </aside>
      </div>
      <div class="made-thing-body" data-added hidden>
        <div class="made-tabs-bar" role="tablist" aria-label="About this board">{tabs("", 0, 0)}</div>
        <section class="made-tab" id="panel-details" role="tabpanel" aria-labelledby="tab-details">
          <nav class="made-tab-side" aria-label="Details"><a href="#summary">Summary</a><a href="#the-board">The board</a></nav>
          <div class="made-tab-main">
            <h2 id="summary">Summary</h2>
            <p data-summary></p>
            <h2 id="the-board">The board</h2>
            <table class="made-table"><tbody data-facts></tbody></table>
          </div>
        </section>
        <section class="made-tab" id="panel-files" role="tabpanel" aria-labelledby="tab-files" hidden>
          <div class="made-tab-main made-tab-wide"><table class="made-table made-files"><tbody data-files></tbody></table></div>
        </section>
        <section class="made-tab" id="panel-checks" role="tabpanel" aria-labelledby="tab-checks" hidden>
          <div class="made-tab-main made-tab-wide"><p data-check-line></p><pre class="made-report-text" data-report></pre></div>
        </section>
      </div>
      <div class="made-wrap made-missing" data-missing hidden>
        <h1>We couldn't find that board</h1>
        <p>It may have been taken down, or it isn't listed yet. <a class="link" href="/">All the boards</a></p>
      </div>

      <section class="made-more" aria-labelledby="more-title">
        <div class="made-wrap">
          <h2 id="more-title">More boards</h2>
          <div class="made-grid" data-grid>
{more}
          </div>
        </div>
      </section>"""
    return shell(
        "A board · Made with Via",
        "A board made with Via, checked by Via's gates.",
        "",
        "../",
        body,
        SCRIPTS,
        home=HOME,
        address="%MADE%/",
        header=top,
    )


def profile_page(things: list[Thing], top: str) -> str:
    """A person's profile, at made.via.computer/u/<id> (the owner's word, 2026-11-27: "there needs to
    be a profile page"): their picture, name, GitHub login, when they joined and a line about them;
    their boards and the boards they like. 1 page for everyone, which made.js fills from
    /api/made?do=profile. The examples' cards wait in a template for the likes that name them."""
    cards = "\n".join(card(t, i, "../") for i, t in enumerate(things))
    body = f"""      <div class="made-profile-page">
        <div class="made-wrap made-missing" data-missing hidden>
          <h1>We couldn't find that person</h1>
          <p>Nobody here has that address yet. <a class="link" href="/">All the boards</a></p>
        </div>
        <div class="made-profile" data-profile hidden>
          <div class="made-profile-head">
            <img class="made-profile-face" data-face alt="" width="128" height="128" hidden>
            <span class="made-profile-face made-profile-initials" data-initials hidden></span>
            <div class="made-profile-who">
              <h1 data-name></h1>
              <p class="made-profile-meta"><a class="link" data-github hidden></a><span data-joined></span></p>
              <p class="made-profile-bio" data-bio></p>
            </div>
            <div class="made-profile-do" data-own hidden>
              <button type="button" class="made-quiet" data-edit-profile>Edit profile</button>
              <button type="button" class="made-go" data-open-mine>My boards</button>
            </div>
          </div>
          <dl class="made-profile-counts">
            <div><dt>Boards</dt><dd data-count-boards>0</dd></div>
            <div><dt>Likes given</dt><dd data-count-likes>0</dd></div>
            <div><dt>Likes on their boards</dt><dd data-count-received>0</dd></div>
          </dl>
        </div>
        <div class="made-thing-body made-profile-body" data-profile-body hidden>
          <div class="made-tabs-bar" role="tablist" aria-label="Their boards and likes"><button type="button" role="tab" id="tab-boards" aria-selected="true" aria-controls="panel-boards">Boards <span data-tab-boards>0</span></button><button type="button" role="tab" id="tab-likes" aria-selected="false" aria-controls="panel-likes" tabindex="-1">Likes <span data-tab-likes>0</span></button></div>
          <section class="made-tab made-profile-tab" id="panel-boards" role="tabpanel" aria-labelledby="tab-boards">
            <div class="made-grid" data-profile-boards></div>
            <p class="made-hint" data-empty-boards hidden>No boards here yet.</p>
          </section>
          <section class="made-tab made-profile-tab" id="panel-likes" role="tabpanel" aria-labelledby="tab-likes" hidden>
            <div class="made-grid" data-profile-likes></div>
            <p class="made-hint" data-empty-likes hidden>No likes yet.</p>
          </section>
        </div>
        <template data-example-cards>
{cards}
        </template>
      </div>

      <dialog class="made-dialog" id="made-profile-edit" aria-labelledby="made-profile-edit-title">
        <form class="made-form" data-profile-form novalidate>
          <h2 id="made-profile-edit-title">Edit profile</h2>
          <label>Name<input name="name" maxlength="60" autocomplete="off"></label>
          <label>About you <small>a line or two</small><textarea name="bio" maxlength="280" rows="3"></textarea></label>
          <p class="made-error" data-error role="alert" hidden></p>
          <div class="made-form-end">
            <button type="button" class="made-quiet" data-close>Cancel</button>
            <button type="submit" class="made-go">Save it</button>
          </div>
        </form>
      </dialog>"""
    return shell(
        "A profile · Made with Via",
        "A person's boards on Made with Via, and the boards they like.",
        "",
        "../",
        body,
        SCRIPTS,
        home=HOME,
        address="%MADE%/",
        header=top,
    )


def pages() -> dict[Path, str]:
    """Every file this script writes, with its text."""
    green, waiting = listed(examples())
    things = [thing(ex) for ex in green]
    # A board's page leads its bar's links to the gallery's own page.
    top = bar(things).replace('href="#add"', 'href="/#add"')
    written = {
        MADE: made_page(green, waiting, things),
        LIKEABLE: likeable(green),
        PAGES / "board.html": added_page(things, top),
        PAGES / "profile.html": profile_page(things, top),
    }
    for t in things:
        others = [o for o in things if o is not t]
        written[PAGES / f"{t.ex.slug}.html"] = board_page(t, others, top)
    return written


def likeable(green: list[Example]) -> str:
    """The ids a like may name besides the boards people add: each listed example's."""
    ids = ", ".join(f'"ex-{ex.slug}"' for ex in green)
    sources = {f"ex-{ex.slug}": {"path": ex.rel, "version": ex.version, "name": ex.name} for ex in green}
    return (
        "// The examples on made.via.computer, as site/made.py lists them: the ids a like may name, and\n"
        "// each one's folder, for the Gerbers the check workflow makes and for its page's address.\n"
        "// Written by site/made.py; do not edit it by hand.\n"
        f"export const EXAMPLES = [{ids}];\n"
        f"export const SOURCES = {json.dumps(sources, indent=2)};\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="exit 1 when made.html differs from what this writes"
    )
    args = parser.parse_args()
    written = pages()
    if args.check:
        stale = [p for p, text in written.items() if not p.is_file() or p.read_text(encoding="utf-8") != text]
        for p in stale:
            print(f"{p.relative_to(ROOT)}: not what site/made.py writes; run it again", file=sys.stderr)
        return 1 if stale else 0
    for path, text in written.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"{path.relative_to(ROOT)}: {max(1, len(text) // 1024)} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
