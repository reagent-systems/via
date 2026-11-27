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

# The 2 installers other pieces of the Windows and macOS round are writing on their own branches
# (wip/wmac: install-macos.sh; wip/wwin: install.ps1). INSTALL.md names them before they land; once
# a file is in the tree, it is held like any other.
COMING = ("install-macos.sh", "install.ps1")

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
NOT_YET = "Not yet proven: the first CI run will say"
NO_RUNNER = "Not proven, and no GitHub runner can prove it"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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


def test_every_file_install_md_names_is_in_the_tree_or_is_an_installer_on_its_way():
    print("allowed before they land:", ", ".join(COMING))
    names = named_files(text(INSTALL))
    assert set(COMING) <= names, "an installer INSTALL.md no longer names stays allowed for nothing"
    assert "install.sh" in names and "tests/boards/pass-first-design" in names
    missing = [n for n in sorted(names) if not (ROOT / n).exists() and n not in COMING]
    assert missing == []


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
    # Each installer a row names is in the tree or on its way.
    files = {f for f in named_files(install) if not f.startswith("tests/")}
    assert [f for f in files if not (ROOT / f).exists() and f not in COMING] == []


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
