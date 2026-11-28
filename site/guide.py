"""The guide: how to use Via, step by step, in plain English, at /guide, and its install pages.

    python3 site/guide.py          # write site/guide.html, site/guide/macos.html and site/guide/windows.html
    python3 site/guide.py --check  # exit 1 when a page is not what this writes

The home page's left card leads here (the owner's ask, 2026-11-19: "a card directly opposite that
links to how to use VIA step-by-step in simple plain English"). Every command and every claim is
the repository's own: README.md ("Install", "Quick start", "Where it runs"), environment/README.md and
tests/boards/README.md. The words follow ee-agent-kit/docs/WEBSITE-WRITING.md.

The install pages, /guide/macos and /guide/windows (the owner's ask, 2026-11-28: "make a macos and
windows installation guide on the site please in the docs"), are written from the files a person's
install runs: INSTALL.md's routes M, N and W (each command, each check, the state of each route),
README.md's prompt for a coding agent, install-macos.sh's and install.ps1's folders and toolchain/
desktop.json's versions and sizes. A command the page shows is a line those files hold: when one of
them changes, this script stops and names what it no longer finds.
"""

# ruff: noqa: E501 - the page's templates are HTML, with its lines as long as the site's pages'.
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
sys.path.insert(0, str(SITE))

from frame import REPO, shell  # noqa: E402

SCRIPTS = ["vendor/motion-14.6.0.js", "site.js", "effects.js"]
GUIDE = SITE / "guide.html"
MACOS = SITE / "guide" / "macos.html"
WINDOWS = SITE / "guide" / "windows.html"
COPY = """<button class="copy" type="button" data-copy aria-label="Copy the commands">
                <svg class="todo" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h8"/></svg>
                <svg class="done" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>
              </button>"""
# The prompt before a line of a POSIX shell, and before a line of PowerShell. site.js copies the lines
# without either.
SH, PS = "$ ", "PS> "


def commands(*lines: str, prompt: str = SH) -> str:
    """A box of commands with the home page's copy button: it copies them without their prompts."""
    text = "\n".join(
        f'<span class="prompt">{html.escape(prompt)}</span>{html.escape(line, quote=False)}' for line in lines
    )
    return f"""<div class="guide-cmd" data-copyable>
              <pre>{text}</pre>
              {COPY}
            </div>"""


def text_box(text: str) -> str:
    """A box of text to paste, with the copy button."""
    return f"""<div class="guide-cmd" data-copyable>
              <pre>{html.escape(text, quote=False)}</pre>
              {COPY.replace("Copy the commands", "Copy the text")}
            </div>"""


# ---------------------------------------------------------------- the facts, from the repository's files


class Missing(Exception):
    """A line this script reads from a file is not in it: the file changed, and the page with it."""


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def found(pattern: str, text: str, where: str, flags: int = 0) -> re.Match:
    match = re.search(pattern, text, flags)
    if not match:
        raise Missing(f"{where}: no longer holds {pattern!r}")
    return match


def section(text: str, heading: str, where: str) -> str:
    """The text of the `## <heading>` section, up to the next heading of its level."""
    start = found(rf"^## {re.escape(heading)}\n", text, where, re.M).end()
    end = re.search(r"^## ", text[start:], re.M)
    return text[start : start + end.start()] if end else text[start:]


def run_line(route: str, part: str, where: str) -> str:
    """The 1 `- Run:` command of a route that holds `part`."""
    runs = [r for r in re.findall(r"- Run: `([^`]+)`", route) if part in r]
    if len(runs) != 1:
        raise Missing(f"{where}: {len(runs)} `- Run:` commands hold {part!r}, not 1")
    return runs[0]


def facts() -> dict:
    """Every fact the install pages state, each read from the file that holds it."""
    install = read("INSTALL.md")
    readme = read("README.md")
    pins = json.loads(read("toolchain/desktop.json"))
    mac_sh, ps1 = read("install-macos.sh"), read("install.ps1")
    m = section(install, "Route M: macOS", "INSTALL.md")
    n = section(install, "Route N: Windows, native", "INSTALL.md")
    w = section(install, "Route W: Windows, through WSL2", "INSTALL.md")
    done = section(install, "Done when", "INSTALL.md")
    gates = re.findall(r"`(workcenter gates tests/boards/[a-z-]+)`", done)
    if len(gates) != 2:
        raise Missing("INSTALL.md, Done when: not the 2 gates checks")
    mac_root = found(r'ROOT="\$\{WORKCENTER_ROOT:-\$\{HOME\}/([^}]+)\}"', mac_sh, "install-macos.sh").group(1)
    mac_link = found(r'LINK="\$\{WORKCENTER_LINK:-\$\{HOME\}/([^}]+)\}"', mac_sh, "install-macos.sh").group(1)
    kicad_dir = found(r'KICAD_DIR="\$\{KICAD_DIR:-([^}]+)\}"', mac_sh, "install-macos.sh").group(1)
    win_root = found(r"Default: (%LOCALAPPDATA%\\[A-Za-z]+) ", ps1, "install.ps1").group(1)
    found(r"\$bin = Join-Path \$Root 'bin'", ps1, "install.ps1")
    found(r"-WhatIf does the same", ps1, "install.ps1")
    found(
        r"Each step skips work already done, so the script is safe to run again", mac_sh, "install-macos.sh"
    )
    rows = {row.split(" | ")[0].lstrip("| "): row for row in install.splitlines() if row.startswith("| ")}
    mac_row = rows["macOS 12 or later, Apple Silicon (`Darwin arm64`)"]
    win_row = rows["Windows 10 or 11, x64"]
    mac_run = found(
        r"again by run (\d+) \(([\d-]+)\), (\d+) of (\d+), none failed", mac_row, "INSTALL.md, macOS"
    )
    win_run = found(
        r"N by run (\d+) \(([\d-]+)\): it installed and the smoke passed all (\d+) steps",
        win_row,
        "INSTALL.md, Windows",
    )
    unjudged = found(
        r"(\d+) tests that need kicad-cli or ngspice were not judged in that run",
        win_row,
        "INSTALL.md, Windows",
    )
    win_next = found(
        r"The next run, (\d+), judged them: (\d+) of its (\d+) tests failed on Windows",
        win_row,
        "INSTALL.md, Windows",
    )
    wsl_run = found(
        r"again by run (\d+) \(([\d-]+)\), (\d+) of (\d+), none failed\.",
        win_row.split("W by run", 1)[1],
        "INSTALL.md, WSL2",
    )
    linux = section(install, "Route L: Linux, Ubuntu 24.04", "INSTALL.md")
    clone_mac = run_line(m, "git clone", "INSTALL.md, route M")
    clone_win = run_line(n, "git clone", "INSTALL.md, route N")
    dry_mac = run_line(m, "--dry-run", "INSTALL.md, route M")
    run_mac = dry_mac.removesuffix(" --dry-run")
    if f"- Run: `{run_mac}`" not in m:
        raise Missing(f"INSTALL.md, route M: no step runs `{run_mac}`")
    dry_win = run_line(n, "-DryRun", "INSTALL.md, route N")
    if not dry_win.endswith(" -DryRun"):
        raise Missing("INSTALL.md, route N: the dry run's command does not end with -DryRun")
    # A person runs the script in their own window, where it can ask: the dry run's line without -DryRun,
    # which is the command README.md's table gives after its Set-Location.
    run_win = dry_win.removesuffix(" -DryRun")
    table = found(
        r"^\| Windows 10 or 11, native \(x64\) \| `([^`]+)` \|", readme, "README.md, Install", re.M
    ).group(1)
    if not run_win.endswith(table):
        raise Missing("README.md's Windows command is not route N's without -DryRun")
    prompt = found(
        r"Paste this to it:\n\n```text\n(.*?)\n```",
        section(readme, "Install", "README.md"),
        "README.md, Install",
        re.S,
    )
    absent = found(r"\| M, N \| ((?:`[a-z-]+`, )*`[a-z-]+`):", done, "INSTALL.md, Done when").group(1)
    kicad = pins["kicad"]
    return {
        "prompt": prompt.group(1),
        "install_md": f"{REPO}/blob/main/INSTALL.md",
        "brew": run_line(m, "brew --version", "INSTALL.md, route M"),
        "clone_mac": clone_mac,
        "dry_mac": dry_mac,
        "dry_mac_last": found(r"its last line is\s+`([^`]+)`", m, "INSTALL.md, route M").group(1),
        "run_mac": run_mac,
        "home_mac": dry_mac.split(" && ")[0],
        "beside_mac": found(r"run\s+`(cd ~/via && KICAD_DIR=[^`]+)`", m, "INSTALL.md, route M").group(1),
        "doctor_mac": run_line(m, "doctor", "INSTALL.md, route M"),
        "doctor_win": run_line(n, "doctor", "INSTALL.md, route N"),
        "home_win": dry_win.split("; ")[0],
        "clone_linux": run_line(linux, "git clone", "INSTALL.md, route L"),
        "sudo_linux": found(r"`(cd ~/via && sudo \./install\.sh)`", linux, "INSTALL.md, route L").group(1),
        "git_win": run_line(n, "git --version", "INSTALL.md, route N"),
        "winget_git": found(r"`(winget install --id Git\.Git[^`]*)`", n, "INSTALL.md, route N").group(1),
        "clone_win": clone_win,
        "dry_win": dry_win,
        "dry_win_last": found(r"last line is `([^`]+)`", n, "INSTALL.md, route N").group(1),
        "run_win": run_win,
        "wsl": found(r"`(wsl --install -d Ubuntu-24\.04)`", w, "INSTALL.md, route W").group(1),
        "wsl_needs": found(
            r"It needs (Windows 10 version \d+ \(build \d+\)) or later", w, "INSTALL.md, route W"
        ).group(1),
        "gates": gates,
        "absent": absent.replace("`", "").split(", "),
        "mac_root": "~/" + mac_root,
        "mac_bin": "~/" + mac_link.rsplit("/", 1)[0],
        "kicad_dir": kicad_dir,
        "win_root": win_root,
        "win_bin": win_root + "\\bin",
        "kicad": kicad["version"],
        "kicad_mac_gb": f"{kicad['macos']['bytes'] / 1e9:.1f}",
        "kicad_win_gb": f"{kicad['windows_x64']['bytes'] / 1e9:.1f}",
        "min_macos": kicad["macos"]["min_macos"],
        "brew_min": pins["homebrew"]["min_macos"],
        "java": pins["java"]["version"].split(".", 1)[0],
        "freerouting": pins["freerouting"]["version"],
        "ngspice": pins["ngspice"]["version"],
        "python": pins["python"]["version"],
        "mac_run": mac_run.groups(),
        "win_run": win_run.groups(),
        "win_next": win_next.groups(),
        "unjudged": unjudged.group(1),
        "wsl_run": wsl_run.groups(),
    }


WORDS = dict(enumerate(("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")))


def number(n: str | int) -> str:
    """A count in running text: one to nine as words, the rest as digits (docs/STYLE.md, the website)."""
    return WORDS.get(int(n), str(n))


def run_link(run: str) -> str:
    return f'<a class="link" href="{REPO}/actions/runs/{run}">run {run}</a>'


def agent(f: dict) -> str:
    """The line the owner wants on every install page: the install can go to the reader's agent."""
    return f"""<p>You can hand the whole install to your coding agent: Claude Code, Codex, Cursor, Copilot, Gemini CLI or any other. Paste this to it, and it follows <a class="link" href="{f["install_md"]}">INSTALL.md</a> one step at a time. It asks you before anything that needs sudo, an administrator, a restart or a big download.</p>
            {text_box(f["prompt"])}"""


def steps_html(steps: tuple[tuple[str, str, str], ...]) -> str:
    return "\n".join(
        f"""            <h2 id="{key}"><span class="guide-n" aria-hidden="true">{n}</span> {heading}</h2>
            {body}"""
        for n, (key, heading, body) in enumerate(steps, 1)
    )


def page(title: str, lede: str, top: str, steps: tuple, after: str) -> str:
    """The body of a guide page: its head, what comes before the steps, the steps, and what follows."""
    return f"""      <article class="section post guide" aria-labelledby="guide-title">
        <div class="wrap">
          <header class="post-head" data-reveal data-stagger>
            <p class="eyebrow">Guide</p>
            <h1 class="title post-title" id="guide-title">{title}</h1>
            <p class="lede">{lede}</p>
          </header>
          <div class="prose">
{top}
{steps_html(steps)}
{after}
          </div>
        </div>
      </article>"""


def code(text: str) -> str:
    return f"<code>{html.escape(text, quote=False)}</code>"


# ---------------------------------------------------------------- /guide


# Each step: its id, its heading and its body. The headings say what the step is, not what to do.
STEPS = (
    (
        "where",
        "Where Via runs",
        """<p>Via runs on Ubuntu 24.04, on a Mac with Apple Silicon, and on Windows 10 or 11. If you're on Ubuntu, you can go straight to step 2. A Mac and a Windows PC each have their own install page: <a class="link" href="guide/macos.html">installing Via on a Mac</a> and <a class="link" href="guide/windows.html">installing Via on Windows</a>.</p>
            <p>A Claude Code cloud environment works too. It's a Linux machine in the cloud that you use from your browser, and we've written a setup script that installs Via on it. Nobody has run that script on a real environment yet, so we'd like to hear how it goes. <a class="link" href="{REPO}/blob/main/environment/README.md">The environment's settings</a> are in the repository. We're also making a Docker image, but it isn't public yet.</p>""",
    ),
    (
        "install",
        "Installing the tools",
        """<p>One script installs the tools Via uses, including KiCad 10, ngspice, Java 21 and FreeRouting. It adds system packages, so it asks for sudo.</p>
            {ubuntu}
            <p>On a cloud environment, the setup script does this step for you.</p>
            {agent}""",
    ),
    (
        "doctor",
        "Checking the install",
        f"""<p><code>workcenter doctor</code> lists each tool Via needs and whether it found it. When nothing's missing, you're ready.</p>
            {commands("workcenter doctor")}""",
    ),
    (
        "checks",
        "A first run of the checks",
        f"""<p>Every board goes through 4 checks, in order.</p>
            <ul>
              <li>ERC checks the schematic's wiring.</li>
              <li>DRC checks the board's copper and spacing, and that the board matches the schematic.</li>
              <li>The simulation runs the circuit and holds its numbers to their limits.</li>
              <li>The export writes the files a board maker needs.</li>
            </ul>
            <p>Our small test board passes all 4, so it shows you what a pass looks like. The last line says GREEN.</p>
            {commands("workcenter gates tests/boards/pass-first-design")}
            <p>A copy of it has 1 track moved too close to a pad, so you can see a failure too. After a failure, <code>workcenter next</code> names the fix.</p>
            {commands("workcenter gates tests/boards/fail-drc-clearance", "workcenter next tests/boards/fail-drc-clearance")}""",
    ),
    (
        "new",
        "Starting your own board",
        f"""<p><code>workcenter new</code> makes a folder for your board, and we keep it outside Via's own folder. It starts with a design file from our template and an empty parts list.</p>
            {commands("workcenter new ~/my-board")}""",
    ),
    (
        "describe",
        "Telling your agent what you want",
        """<p>Next, you describe the board to your AI agent in your own words. A good description says what the board does, how it gets power and what it connects to. We use Claude Code, and another agent can start from <code>AGENTS.md</code>.</p>
            <p>The agent writes the design as a Python file, following Via's board-design skill. A skill is a written procedure that comes with Via. There's one for each job, from designing a board to pricing its parts.</p>""",
    ),
    (
        "next",
        "One step at a time",
        f"""<p>At any point, <code>workcenter next</code> names the one next step. It says what to do, which command to run, why, and what to read. Your agent runs it, fixes what it finds and asks again, until nothing's left.</p>
            {commands("workcenter next ~/my-board")}""",
    ),
    (
        "order",
        "The files you order with",
        f"""<p>When your board passes all 4 checks, the files a board maker asks for are in <code>build/fab</code>. They're the Gerbers, the drill files, the parts list and a PDF of the schematic.</p>
            {commands("workcenter gates ~/my-board")}
            <p>Board makers like JLCPCB and PCBWay take the Gerbers and the drill files when you order.</p>""",
    ),
)


def guide_page(f: dict) -> str:
    ubuntu = commands("git clone https://github.com/reagent-systems/via.git && cd via", "sudo ./install.sh")
    steps = tuple(
        (key, heading, body.replace("{REPO}", REPO).replace("{ubuntu}", ubuntu).replace("{agent}", agent(f)))
        for key, heading, body in STEPS
    )
    after = f"""            <p><a class="link" href="{REPO}/blob/main/ee-agent-kit/CHANGELOG.md">Version 0.1.0</a> is our first release, and we're still early. If a step doesn't work for you, we'd like to hear about it on <a class="link" href="feedback.html">the feedback page</a> or in <a class="link" href="https://discord.reagent-systems.com">our Discord</a>.</p>"""
    body = page(
        "How to use Via, step by step",
        "Here's the whole path from an idea to the files a board maker needs, in plain English. Your AI agent does most of the typing, and Via's checks tell it what's wrong until the board passes.",
        "",
        steps,
        after,
    )
    return shell(
        "How to use Via, step by step · Via",
        "How to use Via, step by step, from installing the tools to the files a board maker needs.",
        "guide",
        "",
        body,
        SCRIPTS,
    )


# ---------------------------------------------------------------- /guide/macos and /guide/windows


def stuck(other: str) -> str:
    """The end of an install page: where to ask, and the other install page."""
    return f"""            <p>If a step still fails after a second try, we'd like to see what it printed. You can ask us in <a class="link" href="https://discord.reagent-systems.com">our Discord</a>, or open an issue at <a class="link" href="{REPO}/issues">GitHub</a> with the command and its last 20 lines. Once Via's installed, <a class="link" href="../guide.html#checks">the guide</a> picks up from your first run of the checks. {other}</p>"""


def checks_body(f: dict, prompt: str, folder: str, window: str) -> str:
    """The install's 3 checks, from INSTALL.md's "Done when", in a new window of the reader's."""
    pass_board, fail_board = f["gates"]
    named = [code(a) for a in f["absent"]]
    absent = ", ".join(named[:-1]) + " and " + named[-1]
    return f"""<p>Your open window still has the PATH it started with, so open a new {window} window. It finds <code>workcenter</code> by name. Then run these {number(1 + len(f["gates"]))} checks in Via's folder.</p>
            {commands(folder, "workcenter doctor", pass_board, fail_board, prompt=prompt)}
            <ul>
              <li><code>workcenter doctor</code> lists each tool. Its first line is <code>workcenter ee: ok</code>, or <code>degraded</code> when the only tools it misses are {absent}. The installer doesn't install those, and the install is done without them.</li>
              <li>The first board is a pass, and the last line starts with <code>GREEN</code>.</li>
              <li>The second board breaks a clearance on purpose, so its last line starts with <code>RED</code>. That's how you know the checks can fail. If it says GREEN, something's wrong with the install.</li>
            </ul>"""


def macos_page(f: dict) -> str:
    sudo_dir = f["kicad_dir"].rsplit("/", 1)[0]
    run_mac, day, passed, total = f["mac_run"]
    steps = (
        (
            "need",
            "What you need first",
            f"""<p>A Mac with Apple Silicon and macOS {f["min_macos"]} or later. You'll also need Homebrew, which brings Python {f["python"]} and ngspice. If <code>brew --version</code> prints a version, you have it. If not, <a class="link" href="https://brew.sh">brew.sh</a> gives the one command that installs it.</p>
            {commands(f["brew"])}
            <p>Homebrew supports macOS {f["brew_min"]} and later. On macOS {f["min_macos"]} to {int(f["brew_min"]) - 1} it builds Python and ngspice from source, which is slow and may fail.</p>""",
        ),
        (
            "get",
            "Getting Via",
            f"""<p>Via installs from its own folder, so the first step is a copy of the repository in your home folder.</p>
            {commands(f["clone_mac"])}
            <p>If macOS offers to install the command line developer tools, say yes and run the command again.</p>""",
        ),
        (
            "look",
            "Looking before it installs",
            f"""<p>The dry run prints every step and every command, and installs, writes and downloads nothing. Its last line is <code>{html.escape(f["dry_mac_last"])}</code>.</p>
            {commands(f["dry_mac"])}""",
        ),
        (
            "run",
            "Installing",
            f"""<p>This is the one command that installs everything, for your own user.</p>
            {commands(f["run_mac"])}
            <ul>
              <li>KiCad {f["kicad"]} comes from its own disk image, about {f["kicad_mac_gb"]} GB, into <code>{f["kicad_dir"]}</code>.</li>
              <li>Java {f["java"]} and FreeRouting {f["freerouting"]}, the autorouter, go into <code>{f["mac_root"]}</code>, with Via's own Python environment.</li>
              <li>Python {f["python"]} and ngspice come from Homebrew, into Homebrew's own folder.</li>
              <li>The <code>workcenter</code> command goes into <code>{f["mac_bin"]}</code>, and the script adds that folder to your PATH in <code>~/.zprofile</code> (or <code>~/.bash_profile</code>).</li>
            </ul>
            <p>KiCad's disk image, Java and FreeRouting are checked against the SHA256 Via pins for each. Nothing runs as root unless <code>{sudo_dir}</code> isn't writable for you, and then the script asks before it uses sudo. Each step skips what's already done, so you can run it again.</p>
            <p>If <code>{f["kicad_dir"]}</code> already holds another KiCad, the script stops and keeps it. KiCad 10 can go beside it, in your own Applications folder, with no sudo at all.</p>
            {commands(f["beside_mac"])}""",
        ),
        (
            "check",
            "Checking that it worked",
            checks_body(f, SH, f["home_mac"], "Terminal"),
        ),
        (
            "fails",
            "When a step fails",
            f"""<p>The script stops at its first problem with a line that starts with <code>[via] ERROR:</code> and says what went wrong. You can run the same step once more, since each step skips what's already done. If <code>workcenter</code> isn't found, the window is older than the install: open a new one, or run <code>{f["doctor_mac"]}</code> by its full path.</p>
            <p>A few of Via's tools stay on Linux: openEMS (<code>workcenter fields</code>), the chip flow, and the tools that need KiCad's <code>pcbnew</code> in Via's own Python, like <code>workcenter placement</code>. They say SKIPPED on a Mac. Docker runs them.</p>""",
        ),
    )
    after = f"""            <h2 id="state">Where this stands</h2>
            <p>We run this install on GitHub's Apple Silicon Macs. In {run_link(run_mac)} on {day}, the script installed Via and {passed} of its {total} tests passed, with none failing. An Intel Mac is best effort: no test machine of ours is one, and it needs Homebrew already installed, since Homebrew's installer refuses an Intel Mac.</p>
{stuck('On a Windows PC, <a class="link" href="windows.html">the Windows page</a> has the same steps.')}"""
    body = page(
        "Installing Via on a Mac",
        "One script installs everything Via needs on a Mac, for your own user. Here's what you need first, what it puts where, and how to check that it worked.",
        f"""            <h2 id="agent">Letting your agent do it</h2>
            {agent(f)}
            <p>If you'd rather do it yourself, these are the same steps.</p>""",
        steps,
        after,
    )
    return shell(
        "Installing Via on a Mac · Via",
        "How to install Via on a Mac with Apple Silicon: what you need, the 1 command, what it installs and where, and how to check it.",
        "guide/macos",
        "../",
        body,
        SCRIPTS,
    )


def windows_page(f: dict) -> str:
    run, day, steps_passed = f["win_run"]
    later, failed, of = f["win_next"]
    wsl_run, wsl_day, wsl_ok, wsl_of = f["wsl_run"]
    steps = (
        (
            "need",
            "What you need first",
            f"""<p>A PC with Windows 10 or 11 on an x64 processor, and Git. Windows on Arm isn't offered natively, because ngspice's Windows build is x64 only; WSL2, at the end of this page, works there. Run every command here in PowerShell, not in the old Command Prompt.</p>
            {commands(f["git_win"], prompt=PS)}
            <p>If that doesn't print a version, Git's own page gives this command for it. Git's installer asks Windows for an administrator.</p>
            {commands(f["winget_git"], prompt=PS)}""",
        ),
        (
            "get",
            "Getting Via",
            f"""<p>Via installs from its own folder, so the first step is a copy of the repository in your home folder. If you've just installed Git, open a new PowerShell window first.</p>
            {commands(f["clone_win"], prompt=PS)}""",
        ),
        (
            "look",
            "Looking before it installs",
            f"""<p>The dry run prints each step as a <code>would:</code> line and each question it will ask you as a <code>would ask:</code> line, and installs, downloads and writes nothing. <code>-WhatIf</code> does the same. Its last line is <code>{html.escape(f["dry_win_last"])}</code></p>
            {commands(f["dry_win"], prompt=PS)}""",
        ),
        (
            "run",
            "Installing",
            f"""<p>This is the one command that installs everything, for your own user. It asks you before KiCad's installer and Python's.</p>
            {commands(f["run_win"], prompt=PS)}
            <ul>
              <li>KiCad {f["kicad"]}, about {f["kicad_win_gb"]} GB, and Python {f["python"]} come from winget, for your user, under <code>%LOCALAPPDATA%\\Programs</code>. Without winget, they come from their own installers.</li>
              <li>Java {f["java"]}, ngspice {f["ngspice"]}, FreeRouting {f["freerouting"]} and Via's own Python environment go into <code>{f["win_root"]}</code>.</li>
              <li>The <code>workcenter</code> command goes into <code>{f["win_bin"]}</code>, and the script adds that folder to your user's PATH.</li>
            </ul>
            <p>winget checks KiCad and Python by its own manifests, and every other download is checked against the SHA256 Via pins for it. The script needs no administrator of its own, but KiCad's installer may ask Windows for one once, for Microsoft's Visual C++ runtime. If you already have KiCad 8 or 9, KiCad 10 goes beside it in a folder of its own, and yours stays. The script never restarts your computer. If an installer asks for a restart, it stops and says so, and you run it again afterwards.</p>""",
        ),
        (
            "check",
            "Checking that it worked",
            checks_body(f, PS, f["home_win"], "PowerShell"),
        ),
        (
            "fails",
            "When a step fails",
            f"""<p>When the script stops, its last red line says why. After a restart an installer asked for, run the install again. If it says Microsoft's Visual C++ runtime is probably missing, that runtime needs an administrator to install. Anything else, run the step again once. If <code>workcenter</code> isn't found, the window is older than the install: open a new one, or run it by its full path, {code(f["doctor_win"])}.</p>
            <p>A few of Via's tools stay on Linux: openEMS (<code>workcenter fields</code>), the chip flow, and the tools that need KiCad's <code>pcbnew</code> in Via's own Python, like <code>workcenter placement</code>. They say SKIPPED on Windows. WSL2 runs them.</p>""",
        ),
        (
            "wsl",
            "Through WSL2 instead",
            f"""<p>WSL2 runs Ubuntu 24.04 inside Windows, and Via then installs the way it does on Ubuntu. It needs {f["wsl_needs"]} or later, or Windows 11. Installing WSL takes an administrator and a restart: open PowerShell with "Run as administrator" and run this.</p>
            {commands(f["wsl"], prompt=PS)}
            <p>After the restart, open "Ubuntu 24.04" from the Start menu and make a Linux user. Then, inside Ubuntu, keep Via in your Linux home folder, not under <code>/mnt/c</code>.</p>
            {commands(f["clone_linux"], f["sudo_linux"])}""",
        ),
    )
    after = f"""            <h2 id="state">Where this stands</h2>
            <p>We run this install on GitHub's Windows machines. In {run_link(run)} on {day}, the script installed Via and its smoke test passed all {number(steps_passed)} steps. The next one, {run_link(later)}, also judged the {f["unjudged"]} tests that need KiCad or ngspice, and {failed} of its {of} tests failed on Windows. We've fixed those causes since, and haven't run them there again yet. Through WSL2, {run_link(wsl_run)} on {wsl_day} passed {wsl_ok} of its {wsl_of} tests, with none failing.</p>
{stuck('On a Mac, <a class="link" href="macos.html">the Mac page</a> has the same steps.')}"""
    body = page(
        "Installing Via on Windows",
        "One PowerShell script installs everything Via needs on Windows, for your own user. Here's what you need first, what it puts where, and how to check that it worked.",
        f"""            <h2 id="agent">Letting your agent do it</h2>
            {agent(f)}
            <p>If you'd rather do it yourself, these are the same steps.</p>""",
        steps,
        after,
    )
    return shell(
        "Installing Via on Windows · Via",
        "How to install Via on Windows 10 or 11: what you need, the 1 command, what it installs and where, how to check it, and WSL2.",
        "guide/windows",
        "../",
        body,
        SCRIPTS,
    )


def pages() -> dict[Path, str]:
    f = facts()
    return {GUIDE: guide_page(f), MACOS: macos_page(f), WINDOWS: windows_page(f)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="exit 1 when a page differs from what this writes"
    )
    args = parser.parse_args()
    try:
        written = pages()
    except Missing as missing:
        print(f"site/guide.py: {missing}; write the page's lines again from it", file=sys.stderr)
        return 1
    if args.check:
        stale = [p for p, text in written.items() if not p.is_file() or p.read_text(encoding="utf-8") != text]
        for path in stale:
            print(f"{path.relative_to(ROOT)}: not what site/guide.py writes; run it again", file=sys.stderr)
        return 1 if stale else 0
    for path, text in written.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"{path.relative_to(ROOT)}: {len(text) // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
