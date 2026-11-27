"""INSTALL.md and the README's Install section: what a person hands to a coding agent, and what the
agent follows. A command INSTALL.md names that the CLI does not have, a file it names that is not in
the tree, or a platform row missing from the README is caught here, not on someone's computer."""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
INSTALL = ROOT / "INSTALL.md"
README = ROOT / "README.md"

# The 2 installers other pieces of the Windows and macOS round write on their own branches (wip/wmac:
# install-macos.sh; wip/wwin: install.ps1 and workcenter.cmd). A route can finish only when its
# installer is in the tree and so is the code its "Done when" needs: the doctor's paths through
# tools/hostos.py (wip/wpaths) on both, and an engine lock without fcntl (wip/wlock) on Windows.
# Until then INSTALL.md and the README send that computer to another route, and say so in these
# words; once all of it is in the tree, they must offer the route. The doc is true whatever lands first.
INSTALLERS = ("install-macos.sh", "install.ps1")
MAC_WAIT = "Until `install-macos.sh` and Via's macOS paths are on `main`"
WIN_WAIT = "Until `install.ps1` and Via's Windows port are on `main`"
NOT_ON_MAIN = "not on `main` yet"

# The platforms the README's table has 1 row for each, by the words that start the row.
PLATFORMS = (
    "Linux, Ubuntu 24.04",
    "macOS, Apple Silicon",
    "macOS, Intel",
    "Windows 10 or 11, native",
    "Windows 10 or 11, WSL2",
    "Docker",
)

# The states a row may give, word for word: proven by a run, or not yet.
PROVEN = "Proven on GitHub's runners"
NOT_YET = "Not yet proven: the next CI run will say"
NO_RUNNER = "Not proven, and no GitHub runner can prove it"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def paths_port() -> bool:
    """The doctor reads KiCad's folders through tools/hostos.py (wip/wpaths), not Linux's alone: its
    symbols row and the 3D models' folder read `hostos.kicad_share()`."""
    return re.search(r"hostos\.kicad_(dirs|share)\(\)", text(CLI)) is not None


def lock_port() -> bool:
    """The engine lock imports on Windows (wip/wlock): no module-level `import fcntl`."""
    return re.search(r"^import fcntl$", text(ROOT / "tools" / "enginelock.py"), re.M) is None


def mac_ready() -> bool:
    return (ROOT / "install-macos.sh").is_file() and paths_port()


def win_ready() -> bool:
    files = all((ROOT / f).is_file() for f in ("install.ps1", "workcenter.cmd"))
    return files and paths_port() and lock_port()


def table(doc: str) -> list[list[str]]:
    """The cells of each body row of the first Markdown table in `doc`."""
    rows = [line for line in doc.splitlines() if line.startswith("| ") and not line.startswith("|---")]
    return [[cell.strip() for cell in row.split("|")[1:-1]] for row in rows[1:]]


def route_rows() -> list[list[str]]:
    """INSTALL.md's "Pick the route" table: platform, route, state."""
    return table(section(text(INSTALL), "## Pick the route"))


def section(doc: str, heading: str) -> str:
    """The text under `heading` (a whole line), up to the next heading of the same level or above."""
    level = heading.split()[0]
    assert f"\n{heading}\n" in doc, heading
    rest = doc.split(f"\n{heading}\n", 1)[1]
    stop = re.search(rf"^#{{1,{len(level)}}} ", rest, re.M)
    return rest[: stop.start()] if stop else rest


def code_spans(doc: str) -> list[str]:
    """Each line of a fenced block, and each inline code span outside the blocks."""
    fences = re.findall(r"^```.*?^```", doc, re.S | re.M)
    lines = [line for block in fences for line in block.splitlines()[1:-1]]
    return lines + re.findall(r"`([^`\n]+)`", re.sub(r"^```.*?^```", "", doc, flags=re.S | re.M))


def subcommands() -> list[str]:
    """The CLI's subcommands, from its own help."""
    out = subprocess.run([sys.executable, str(CLI), "--help"], capture_output=True, text=True, check=True)
    return re.search(r"\{([a-z,]+)\}", out.stdout).group(1).split(",")


def written(doc: str) -> list[tuple[str, set[str]]]:
    """Each `workcenter <command>` the document writes as code, with the flags it gives it."""
    found = []
    for span in code_spans(doc):
        # `workcenter ee: ok` is the doctor's first line, not a command.
        for part in re.split(r"\bworkcenter (?=[a-z]+(?:\s|$))", " ".join(span.split()))[1:]:
            part = re.split(r" (?:&&|\|\||\||;|>|2>|>>) |'", part)[0]
            found.append((part.split()[0], set(re.findall(r"(?<![\w-])--[a-z][a-z0-9-]*", part))))
    return found


def named_files(doc: str) -> set[str]:
    """The repository's files a document names: a relative link, and each word of a code span that is
    1 relative path (no URL, no `~`, `$`, `%`, `\\`, `:` or quote) with a folder or a file's
    extension: `install.ps1` in a PowerShell line, `tests/boards/x` in a gates command."""
    names = {link for link in re.findall(r"\]\(([^)#\s]+)", doc) if "://" not in link}
    for span in code_spans(doc):
        if span.lstrip().startswith(("~", "/", "$", "%")):
            continue  # 1 path outside the tree, blanks and all: `~/Library/Application Support/via`
        for word in span.split():
            word = word.removeprefix("./")
            if re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_.-]+)*/?", word) and (
                "/" in word or re.search(r"\.(?:md|sh|ps1|py|json|txt|csv|yml|cmd)$", word)
            ):
                names.add(word)
    return names


def test_install_md_says_when_it_is_done_with_the_fixtures_real_verdicts():
    """The "Done when" checks are the README's quick start: the doctor, a fixture that is GREEN and a
    fixture that is RED on purpose, named by their projects as the gates print them."""
    done = section(text(INSTALL), "## Done when")
    for line in (
        "workcenter doctor",
        "workcenter gates tests/boards/pass-first-design",
        "workcenter gates tests/boards/fail-drc-clearance",
    ):
        assert line in done, line
    # The verdict lines the gates print end with the project's name: the .kicad_pro in each folder.
    assert (ROOT / "tests/boards/pass-first-design/divider.kicad_pro").is_file()
    assert (ROOT / "tests/boards/fail-drc-clearance/rc_divider.kicad_pro").is_file()
    assert "GREEN: divider" in done and "RED: rc_divider" in done
    fixtures = text(ROOT / "tests" / "boards" / "README.md")
    assert re.search(r"^\| `pass-first-design` \| GREEN on `workcenter gates`", fixtures, re.M)
    assert re.search(r"^\| `fail-drc-clearance` \| ERC pass, DRC fail", fixtures, re.M)


def test_every_workcenter_command_install_md_names_is_a_command_with_those_flags():
    known = subcommands()
    found = written(text(INSTALL))
    assert {"doctor", "gates"} <= {name for name, _ in found}
    assert [name for name, _ in found if name not in known] == []
    wrong = []
    for name, flags in found:
        out = subprocess.run(
            [sys.executable, str(CLI), name, "--help"], capture_output=True, text=True, check=True
        ).stdout
        wrong += [f"workcenter {name} {flag}" for flag in sorted(flags) if flag not in out]
    assert wrong == []


def test_every_file_install_md_names_is_in_the_tree_or_is_an_installer_its_route_waits_for():
    names = named_files(text(INSTALL))
    assert set(INSTALLERS) <= names and "install.sh" in names and "tests/boards/pass-first-design" in names
    missing = [n for n in sorted(names) if not (ROOT / n).exists()]
    print("installers not in the tree:", ", ".join(missing) or "none")
    # An absent installer is allowed only because the next test holds its route back.
    assert [n for n in missing if n not in INSTALLERS] == []


def test_the_file_names_test_finds_a_file_that_is_not_there():
    """The pattern above is not so narrow that it reads nothing."""
    planted = "Run `./install-linux.sh`, read [this](docs/NOPE.md), `workcenter gates tests/x`."
    assert named_files(planted) == {"install-linux.sh", "docs/NOPE.md", "tests/x"}
    nothing = (
        "`~/via` `$HOME\\via` `https://x.y/z.sh` `git clone a b` `10.0.8` `/tmp/x` `ghcr.io/a/b:main`"
        " `~/Library/Application Support/via`"
    )
    assert named_files(nothing) == set()


def test_install_md_has_a_route_per_platform_and_stop_rules():
    doc = text(INSTALL)
    for heading in (
        "## Route L: Linux, Ubuntu 24.04",
        "## Route M: macOS",
        "## Route N: Windows, native",
        "## Route W: Windows, through WSL2",
        "## Route D: Docker",
        "## Done when",
    ):
        assert f"\n{heading}\n" in doc, heading
    for word in ("sudo", "administrator", "restart", "fails twice", "Stop"):
        assert word in doc, word
    for installer in ("./install.sh", "./install-macos.sh", "install.ps1"):
        assert installer in doc, installer


def test_the_readme_hands_the_install_to_a_coding_agent_with_a_prompt_that_names_install_md():
    install = section(text(README), "## Install")
    opening = install.strip().split("\n\n")[0]
    assert "coding agent" in opening
    for agent in ("Claude Code", "Codex", "Cursor", "Copilot", "Gemini CLI"):
        assert agent in opening, agent
    prompts = re.findall(r"^```text\n(.*?)^```", install, re.S | re.M)
    assert len(prompts) == 1
    prompt = prompts[0]
    assert "INSTALL.md" in prompt
    assert "https://raw.githubusercontent.com/reagent-systems/via/main/INSTALL.md" in prompt
    assert len(prompt.splitlines()) <= 7
    # An agent that cannot fetch a URL reads the same file in a clone.
    clone = "If you cannot fetch it, clone https://github.com/reagent-systems/via and read INSTALL.md"
    assert clone in prompt
    for words in ("sudo", "administrator", "restart", "large download", '"Done when"', "fails twice"):
        assert words in prompt, words


def test_the_readme_table_has_a_row_for_each_platform_with_a_command_and_a_true_state():
    install = section(text(README), "## Install")
    rows = [line for line in install.splitlines() if line.startswith("| ") and not line.startswith("| ---")]
    header, rows = rows[0], rows[1:]
    assert header.split("|")[1:4] == [" Computer ", " Command ", " State "]
    cells = {row.split("|")[1].strip(): row.split("|")[2:4] for row in rows}
    assert [p for p in PLATFORMS if not any(name.startswith(p) for name in cells)] == []
    assert len(cells) == len(PLATFORMS)
    for name, (command, state) in cells.items():
        assert re.search(r"`[^`]+`", command), name
        assert state.strip().startswith((PROVEN, NOT_YET, NO_RUNNER, "Best effort")), name
    proven = [name for name, (_, state) in cells.items() if state.strip().startswith(PROVEN)]
    assert proven == ["Linux, Ubuntu 24.04"]
    # Each installer a row names is in the tree, or its row says it is not on main yet.
    files = {f for f in named_files(install) if not f.startswith("tests/")}
    assert [f for f in files if not (ROOT / f).exists() and f not in INSTALLERS] == []
    for name, (_, state) in cells.items():
        ready = {"macOS": mac_ready, "Windows 10 or 11, native": win_ready}
        for start, is_ready in ready.items():
            if name.startswith(start):
                assert (NOT_ON_MAIN in state) == (not is_ready()), name


def test_the_readme_says_where_the_container_was_run_and_who_can_pull_it():
    readme = text(README)
    assert "nobody has run these commands on Windows or macOS yet" not in readme
    install = section(text(README), "## Install")
    assert "ghcr.io/reagent-systems/via:main" in install
    assert "anonymous" in install


def test_the_root_instruction_files_and_routing_point_an_agent_at_install_md():
    agents = text(ROOT / "AGENTS.md")
    assert agents == text(ROOT / "CLAUDE.md")
    assert re.search(r"^Setting Via up on a computer.*`INSTALL\.md`", agents, re.M | re.S)
    routing = text(ROOT / "ee-agent-kit" / "ROUTING.md")
    rows = [line for line in routing.splitlines() if "`../INSTALL.md`" in line]
    assert len(rows) == 1 and "Done when" in rows[0]


def test_a_route_whose_parts_are_not_in_the_tree_sends_its_computer_to_another_route():
    """INSTALL.md can land before or after the installers and the ports, and is true either way: a
    route not ready here is not picked first, and its section says what it waits for."""
    doc = text(INSTALL)
    mac = [row for row in route_rows() if row[0].startswith("macOS")]
    win = [row for row in route_rows() if row[0].startswith("Windows 10 or 11")]
    assert len(mac) == 2 and len(win) == 1
    for _, route, _ in mac:
        assert route.startswith("M") == mac_ready(), route
        assert route.startswith("D") or route.startswith("M"), route
    assert win[0][1].startswith("N") == win_ready() and win[0][1].startswith(("N", "W")), win[0][1]
    assert (MAC_WAIT in section(doc, "## Route M: macOS")) == (not mac_ready())
    assert (WIN_WAIT in section(doc, "## Route N: Windows, native")) == (not win_ready())
    # The import error a Windows run without the lock's port stops at is named only while it can happen.
    assert ("No module named 'fcntl'" in doc) == (not lock_port())


def test_install_md_route_table_gives_each_platform_a_true_state():
    rows = route_rows()
    starts = (PROVEN, NOT_YET, NO_RUNNER, "Best effort", "Not offered")
    assert [row[0] for row in rows if not row[2].startswith(starts)] == []
    assert [row[0] for row in rows if row[2].startswith(PROVEN)] == ["Ubuntu 24.04 (x86_64 or arm64)"]
    assert [row[0] for row in rows if PROVEN in row[2] and not row[2].startswith(PROVEN)] == []


def test_every_step_of_a_route_has_a_check():
    """Rule 9: a step with no check run is not done. A step that only hands over says where to."""
    doc = text(INSTALL)
    for heading in re.findall(r"^## Route .*$", doc, re.M):
        steps = re.split(r"^\d+\. ", section(doc, heading), flags=re.M)[1:]
        assert steps, heading
        for step in steps:
            assert step.startswith("Go to") or "- Check:" in step, (heading, step.splitlines()[0])


def test_an_agent_runs_the_checks_by_full_path_since_its_shell_keeps_the_path_it_started_with():
    """An installer adds its folder to PATH for new terminals only; the agent's shell is not one."""
    doc = text(INSTALL)
    mac = section(doc, "## Route M: macOS")
    win = section(doc, "## Route N: Windows, native")
    assert "`~/.local/bin/workcenter doctor`" in mac
    assert '`& "$env:LOCALAPPDATA\\Via\\bin\\workcenter.cmd" doctor`' in win
    done = section(doc, "## Done when")
    assert "`~/.local/bin/workcenter`" in done and '`& "$env:LOCALAPPDATA\\Via\\bin\\workcenter.cmd"`' in done
    row = [line for line in done.splitlines() if line.startswith("| `workcenter` is not found")]
    assert len(row) == 1 and "new terminal. Then run" not in row[0] and "full path" in row[0]
    # The paths are the installers' own defaults, once the installers are in the tree.
    if (ROOT / "install-macos.sh").is_file():
        assert 'LINK="${WORKCENTER_LINK:-${HOME}/.local/bin/workcenter}"' in text(ROOT / "install-macos.sh")
    if (ROOT / "install.ps1").is_file():
        ps1 = text(ROOT / "install.ps1")
        assert "Join-Path $env:LOCALAPPDATA 'Via'" in ps1 and "Join-Path $Root 'bin'" in ps1
        assert "Join-Path $bin 'workcenter.cmd'" in ps1


def test_route_m_sends_no_intel_mac_to_homebrews_installer_and_names_homebrews_macos_floor():
    """Homebrew's install.sh aborts on Intel and supports macOS 15 and newer
    (raw.githubusercontent.com/Homebrew/install/HEAD/install.sh, read 2026-11-27)."""
    mac = section(text(INSTALL), "## Route M: macOS")
    assert "Homebrew's installer refuses an Intel Mac" in mac and "route D" in mac
    for name, _, state in route_rows():
        if name.startswith("macOS"):
            assert "macOS 12 to 14" in state, name
    readme = [row for row in table(section(text(README), "## Install")) if row[0].startswith("macOS")]
    assert len(readme) == 2 and all("macOS 12 to 14" in row[2] for row in readme)


def test_routes_m_and_n_say_which_downloads_via_checks_and_where_each_part_goes():
    doc = text(INSTALL)
    assert "every download by its SHA256" not in doc
    mac = section(doc, "## Route M: macOS")
    win = section(doc, "## Route N: Windows, native")
    assert "Homebrew's own prefix" in mac and "checked against Via's pinned SHA256" in mac
    assert "winget's manifest" in win and "checked against Via's pinned SHA256" in win
    assert "%LOCALAPPDATA%\\Programs" in win


def test_another_kicad_is_kept_and_kicad_10_goes_beside_it_with_the_persons_yes():
    doc = text(INSTALL)
    rules = section(doc, "## Rules for the agent")
    assert "Never install a second KiCad" not in rules
    assert "Never remove or move a KiCad the person has" in rules
    assert "beside another version only with the person's yes" in rules
    mac = section(doc, "## Route M: macOS")
    assert 'KICAD_DIR="$HOME/Applications/KiCad" ./install-macos.sh' in mac
    assert "another KiCad" in section(doc, "## Route N: Windows, native")
    if (ROOT / "install-macos.sh").is_file():
        said = 'KICAD_DIR=\\"\\$HOME/Applications/KiCad\\" ./install-macos.sh'
        assert said in text(ROOT / "install-macos.sh")


def test_every_image_tag_the_docs_name_is_one_the_image_workflow_pushes():
    """The image workflow pushes `main` from main, and a release's tag only once the tag exists; no
    release tag is pushed yet, so `main` is the 1 tag a person can pull."""
    workflow = text(ROOT / ".github" / "workflows" / "image.yml")
    assert 'tags+=(-t "$IMAGE:main")' in workflow
    for doc in (README, INSTALL):
        tags = re.findall(r"ghcr\.io/[a-z0-9-]+/via:([A-Za-z0-9._-]+)", text(doc))
        assert tags and sorted(set(tags)) == ["main"], doc.name


def test_done_when_lets_a_route_finish_with_the_degraded_rows_it_cannot_install():
    done = section(text(INSTALL), "## Done when")
    assert "or `degraded` with only the rows the table below allows for this route" in done
    rows = table(done.split("When a check fails")[0])
    allowed = {row[0]: set(re.findall(r"`([a-z0-9-]+)`", row[1])) for row in rows}
    assert allowed == {"M, N": {"openems", "rsvg-convert", "ffmpeg"}, "D on arm64": {"openems"}}
    # Each is a row the doctor has.
    for row in set().union(*allowed.values()):
        assert f'"{row}": {{' in text(CLI), row


def test_the_installers_lines_install_md_quotes_are_the_installers_own():
    doc = text(INSTALL)
    mac = section(doc, "## Route M: macOS")
    win = section(doc, "## Route N: Windows, native")
    quoted = {
        "install-macos.sh": [(mac, "dry run: nothing was installed, written or downloaded")],
        "install.ps1": [
            (win, "dry run: nothing was installed, downloaded or written."),
            (win, "would ask:"),
            (win, "Nobody can answer here."),
            (win, "Visual C++ runtime is probably missing"),
        ],
    }
    for installer, lines in quoted.items():
        for where, line in lines:
            assert line in where, line
            if (ROOT / installer).is_file():
                assert line in text(ROOT / installer), line
    assert "exit 4" in win


def test_route_w_reads_wsl_as_utf8_and_checks_the_linux_user():
    wsl = section(text(INSTALL), "## Route W: Windows, through WSL2")
    assert "`$env:WSL_UTF8=1; wsl -l -v`" in wsl
    assert "`wsl -d Ubuntu-24.04 -- whoami`" in wsl and "not `root`" in wsl


def test_a_windows_agent_in_git_bash_finds_its_route_and_runs_it_in_powershell():
    pick = section(text(INSTALL), "## Pick the route")
    assert "`MINGW64_NT`" in pick and "`MSYS_NT`" in pick and "PowerShell tool" in pick


def test_windows_steps_name_the_administrator_git_asks_for_and_a_path_powershell_passes_whole():
    doc = text(INSTALL)
    step1 = section(doc, "## Route N: Windows, native").split("\n2. ")[0]
    assert "administrator" in step1
    assert '`workcenter new "$HOME\\my-board"`' in section(doc, "## Next")
