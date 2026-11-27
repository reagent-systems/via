"""install-macos.sh and its pins, toolchain/desktop.json, held on Linux.

No test here installs anything, and none needs macOS. The script is read (shellcheck, `bash -n`, the
constructs bash 3.2 lacks), and it is run only inside a fence:
1. PATH holds 1 folder the test makes. In it, stand-ins for the programs the script may ask in a dry run
   (`uname`, `sw_vers`, `sysctl`, `brew`) write their call to a calls file and answer from the test's
   environment; `python3` writes its call and runs the real Python, which reads the pins. Every program
   that would install or write (`curl`, `hdiutil`, `ditto`, `sudo`, `shasum`, `tar`, `mkdir`, `ln`, `mv`,
   `rm`, `cp`, `chmod`, `mktemp`, `grep`, `rmdir`, `xattr`) is a stand-in that writes `REFUSED` and ends
   with 99. Any other program is not found. macOS's `plutil`, which reads the pins on a Mac, is not
   there, so the script reads them with `python3` here (the plutil branch runs first on macOS's CI leg).
2. HOME and TMPDIR point into the test's folder, and no WORKCENTER_ROOT or WORKCENTER_LINK is inherited.
3. Each run ends by checking its calls file: no `REFUSED`, and no program the run may not ask.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "install-macos.sh"
PINS = ROOT / "toolchain" / "desktop.json"
INSTALL = ROOT / "install.sh"
BASH = "/bin/bash"
SHA = re.compile(r"^[0-9a-f]{64}$")
STEPS = [
    "Homebrew",
    "Python 3.12 and ngspice",
    "KiCad",
    "Java 21",
    "FreeRouting",
    "the venv",
    "the workcenter command",
    "workcenter doctor",
]
READERS = {"uname", "sw_vers", "sysctl", "brew", "python3"}
# Homebrew's installer aborts on Intel (raw.githubusercontent.com/Homebrew/install/HEAD/install.sh,
# read 2026-11-27: "Homebrew on macOS is only supported on Apple Silicon processors!"), and
# formulae.brew.sh/api/formula/python@3.12.json lists bottles for arm64 macOS only.
INTEL_LINE = (
    "[via] Intel Mac: best effort; Via targets Apple Silicon. It needs a Homebrew already installed: "
    "Homebrew's installer no longer supports Intel, and Python 3.12 builds from source."
)
REFUSED = ["curl", "hdiutil", "ditto", "sudo", "shasum", "tar", "mkdir", "ln", "mv", "rm", "cp", "chmod"]
REFUSED += ["mktemp", "grep", "rmdir", "xattr"]


def pins() -> dict:
    return json.loads(PINS.read_text())


def files_of(d: dict) -> list[dict]:
    """Every entry of the pins that names a download: it has a `url`."""
    out = []
    for v in d.values():
        if isinstance(v, dict):
            if "url" in v:
                out.append(v)
            out += files_of(v)
    return out


def code_lines() -> list[str]:
    """The script's lines without comments (a `#` that starts a line or follows a blank)."""
    out = []
    for line in SCRIPT.read_text().splitlines():
        if line.lstrip().startswith("#"):
            continue
        out.append(re.sub(r"\s#\s.*$", "", line))
    return out


def fence(
    tmp_path: Path, *, arch: str = "arm64", system: str = "Darwin", brew: bool = True, macos: str = "15.6"
) -> dict:
    """The environment of 1 fenced run, with its stand-ins in tmp_path/bin."""
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    calls = tmp_path / "calls"
    calls.write_text("")
    answers = {
        "uname": 'case "$1" in -s) echo "$FAKE_S";; -m) echo "$FAKE_M";; *) echo "$FAKE_S";; esac',
        "sw_vers": 'echo "$FAKE_V"',
        "sysctl": "echo 0",
        "brew": 'case "$1" in --prefix) echo "$FAKE_PREFIX${2:+/opt/$2}";; '
        'list) echo "$FAKE_LIST";; *) exit 98;; esac',
    }
    if not brew:
        del answers["brew"]
    for name, answer in answers.items():
        p = bin_ / name
        p.write_text(f'#!{BASH}\nprintf "%s %s\\n" "{name}" "$*" >> "$CALLS"\n{answer}\n')
        p.chmod(0o755)
    py = bin_ / "python3"
    real = shutil.which("python3")
    py.write_text(f'#!{BASH}\nprintf "python3 %s\\n" "${{1:-}}" >> "$CALLS"\nexec {real} "$@"\n')
    py.chmod(0o755)
    for name in REFUSED:
        p = bin_ / name
        p.write_text(f'#!{BASH}\nprintf "REFUSED {name} %s\\n" "$*" >> "$CALLS"\nexit 99\n')
        p.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / "tmp").mkdir()
    return {
        "PATH": str(bin_),
        "HOME": str(home),
        "TMPDIR": str(tmp_path / "tmp"),
        "CALLS": str(calls),
        "FAKE_S": system,
        "FAKE_M": arch,
        "FAKE_V": macos,
        "FAKE_LIST": "ngspice 47",
        "FAKE_PREFIX": "/opt/homebrew" if arch == "arm64" else "/usr/local",
        "SHELL": "/bin/zsh",
    }


def run(tmp_path: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [BASH, str(SCRIPT), *args],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
    )


def called(tmp_path: Path) -> list[str]:
    return (tmp_path / "calls").read_text().splitlines()


def assert_only_readers(tmp_path: Path) -> None:
    lines = called(tmp_path)
    assert not [x for x in lines if x.startswith("REFUSED")], lines
    assert {x.split()[0] for x in lines} <= READERS, lines


def assert_nothing_written(tmp_path: Path) -> None:
    assert list((tmp_path / "home").iterdir()) == []
    assert list((tmp_path / "tmp").iterdir()) == []


# ---- the script, read ---------------------------------------------------------------------------------


def test_shellcheck_reads_the_script_clean():
    """shellcheck as the Makefile's lint line runs it: no options, the script's own shebang."""
    if shutil.which("shellcheck") is None:
        pytest.skip("shellcheck is not on PATH")
    ran = subprocess.run(["shellcheck", str(SCRIPT)], capture_output=True, text=True)
    assert ran.returncode == 0, ran.stdout + ran.stderr


def test_bash_reads_the_script():
    ran = subprocess.run([BASH, "-n", str(SCRIPT)], capture_output=True, text=True)
    assert ran.returncode == 0, ran.stderr


def test_the_script_uses_nothing_bash_3_2_or_a_bare_macos_lacks():
    """macOS ships bash 3.2.57 and BSD tools: no mapfile, no associative or name arrays, no case
    changes in an expansion, no `|&`, `&>>` or `{fd}` redirections, no arrays at all (bash 3.2 calls an
    empty one unbound under `set -u`), and no GNU-only programs (sha256sum, timeout, readlink -f)."""
    text = "\n".join(code_lines())
    banned = {
        "mapfile": r"\bmapfile\b",
        "readarray": r"\breadarray\b",
        "declare -A or -n": r"\b(declare|local|typeset)\s+-[a-zA-Z]*[An]",
        "case change": r"\$\{[^}]*(,,|\^\^)",
        "@Q and other transforms": r"\$\{[^}]*@[QEPAa]\}",
        "|&": r"\|&",
        "&>>": r"&>>",
        "{fd} redirection": r"\{[a-zA-Z_]+\}[<>]",
        "coproc": r"\bcoproc\b",
        "wait -n": r"\bwait\s+-n\b",
        "an array": r"\b[A-Za-z_]+=\(",
        "sha256sum": r"\bsha256sum\b",
        "timeout": r"(^|[\s;|&(])timeout\s",
        "readlink -f": r"readlink\s+-f",
        "EPOCHSECONDS": r"EPOCH(SECONDS|REALTIME)",
    }
    found = {name: re.findall(rx, text, re.M) for name, rx in banned.items()}
    assert {k: v for k, v in found.items() if v} == {}
    assert SCRIPT.read_text().startswith("#!/bin/bash\n")
    assert "shasum -a 256" in text


def test_the_script_names_no_url_and_no_checksum():
    """Every address and checksum comes from toolchain/desktop.json."""
    text = SCRIPT.read_text()
    assert not re.findall(r"https?://", text)
    assert not re.findall(r"\b[0-9a-f]{64}\b", text)


def test_the_dmg_and_the_java_archive_stay_in_the_downloads_folder():
    """The macOS leg of CI keeps ROOT/downloads between runs (ee-agent-kit/CI.md, "Windows and macOS"):
    a DMG removed after use leaves the cache nothing, and every run downloads 1.4 GB again."""
    code = "\n".join(code_lines())
    assert 'dmg="${ROOT}/downloads/${file}"' in code and 'tgz="${ROOT}/downloads/${file}"' in code
    assert not re.search(r'\brm\b[^\n]*"\$(dmg|tgz)"', code)
    assert 'say "kept for a run again: ${dmg}' in code and 'say "kept for a run again: ${tgz}"' in code


def test_every_pin_the_script_reads_is_in_the_pins_file():
    keys = sorted(set(re.findall(r"\bpin ([a-z0-9_.]+)", "\n".join(code_lines()))))
    assert len(keys) >= 15, keys
    d = pins()
    for key in keys:
        v = d
        for part in key.split("."):
            assert isinstance(v, dict) and part in v, key
            v = v[part]
        assert isinstance(v, str | int) and str(v), key


# ---- the pins -----------------------------------------------------------------------------------------


def test_the_pins_parse_and_name_every_file_with_its_checksum():
    d = pins()
    assert d["kicad"]["version"] == "10.0.8"
    assert d["python"]["version"] == "3.12"
    assert d["java"]["version"].startswith("21.")
    files = files_of(d)
    assert len(files) == 9, files  # KiCad 2, ngspice, Java 3, the jar, Python, 7-Zip (Windows)
    for f in files:
        assert f["url"].startswith("https://"), f
        assert SHA.match(f["sha256"]), f
        assert isinstance(f["bytes"], int) and f["bytes"] > 0, f
        assert f.get("file", f["url"].rsplit("/", 1)[-1]) in f["url"], f
    for key in ("macos", "windows_x64"):
        assert d["kicad"][key]["file"].endswith(".dmg" if key == "macos" else ".exe")
        assert d["kicad"]["version"] in d["kicad"][key]["url"]


def test_every_url_and_checksum_is_named_in_1_place_only():
    """Each address and each SHA256 stands once in desktop.json and in no other file of the checkout,
    except the FreeRouting jar's SHA256, which install.sh pins too (the next test holds them equal)."""
    text = PINS.read_text()
    values = []
    for f in files_of(pins()):
        values += [f["url"], f["sha256"]] + ([f["mirror"]] if "mirror" in f else [])
    assert len(values) == len(set(values))
    for v in values:
        assert text.count(v) == 1, v
    if not (ROOT / ".git").exists():
        pytest.skip("no git checkout to search")
    allowed = {"toolchain/desktop.json"}
    for v in values:
        ran = subprocess.run(["git", "-C", str(ROOT), "grep", "-l", "-F", v], capture_output=True, text=True)
        where = set(ran.stdout.split()) - allowed
        if v == pins()["freerouting"]["sha256"]:
            where -= {"install.sh"}
        assert where == set(), (v, where)


def test_the_freerouting_jar_is_the_one_install_sh_pins():
    sh = INSTALL.read_text()
    sha = re.search(r'FREEROUTING_SHA256="\$\{FREEROUTING_SHA256:-([0-9a-f]{64})\}"', sh).group(1)
    ver = re.search(r'FREEROUTING_VERSION="\$\{FREEROUTING_VERSION:-([0-9.]+)\}"', sh).group(1)
    fr = pins()["freerouting"]
    assert (fr["sha256"], fr["version"]) == (sha, ver)
    assert fr["url"].endswith(f"/v{ver}/freerouting-{ver}.jar")


# ---- the script, run in the fence ---------------------------------------------------------------------


def test_help_prints_the_usage_and_ends_with_0(tmp_path):
    env = fence(tmp_path)
    for flag in ("--help", "-h"):
        ran = run(tmp_path, env, flag)
        assert ran.returncode == 0, ran.stderr
        assert "Usage: ./install-macos.sh" in ran.stdout
        for word in ("--dry-run", "--yes", "--check"):
            assert word in ran.stdout
    assert_only_readers(tmp_path)
    assert_nothing_written(tmp_path)


def test_an_unknown_argument_ends_with_2_and_the_usage(tmp_path):
    env = fence(tmp_path)
    ran = run(tmp_path, env, "--dry-run", "--frobnicate")
    assert ran.returncode == 2
    assert "unknown argument: --frobnicate" in ran.stderr
    assert "Usage: ./install-macos.sh" in ran.stderr
    assert ran.stdout == ""
    assert_nothing_written(tmp_path)


def step_lines(out: str) -> list[str]:
    return [x for x in out.splitlines() if re.match(r"^\[via\] step \d/8: ", x)]


def test_the_dry_run_prints_every_step_in_order_and_runs_none(tmp_path):
    env = fence(tmp_path)
    ran = run(tmp_path, env, "--dry-run")
    assert ran.returncode == 0, ran.stdout + ran.stderr
    steps = step_lines(ran.stdout)
    assert [re.sub(r"^\[via\] step (\d)/8: ", r"\1 ", x).split(":")[0] for x in steps] == [
        f"{i} {s}" for i, s in enumerate(STEPS, 1)
    ], steps
    d = pins()
    k = d["kicad"]["macos"]
    j = d["java"]["macos_arm64"]
    fr = d["freerouting"]
    for v in (k["url"], k["sha256"], j["url"], j["sha256"], fr["url"], fr["sha256"]):
        assert v in ran.stdout, v
    assert d["java"]["macos_x64"]["url"] not in ran.stdout
    root = f"{tmp_path}/home/Library/Application Support/via"
    assert f"{root}/venv" in ran.stdout
    assert f"{tmp_path}/home/.local/bin/workcenter" in ran.stdout
    assert "would run: brew install python@3.12 ngspice" in ran.stdout
    assert "Intel" not in ran.stdout
    assert ran.stdout.rstrip().splitlines()[-1].startswith("[via] dry run: nothing was installed")
    # Each command it prints is 1 a shell can run: the root's blank stays inside its word.
    commands = [x.split("would run: ", 1)[1] for x in ran.stdout.splitlines() if "would run: " in x]
    assert len(commands) >= 20, commands
    words = [w for c in commands for w in shlex.split(c)]
    assert f"{root}/venv" in words
    assert f"{root}/venv/bin/python" in words
    assert words.count(f"{tmp_path}/home/.local/bin/workcenter") >= 2
    assert_only_readers(tmp_path)
    assert_nothing_written(tmp_path)


def test_the_dry_run_on_an_intel_mac_says_best_effort_once_and_takes_the_intel_java(tmp_path):
    env = fence(tmp_path, arch="x86_64")
    ran = run(tmp_path, env, "--dry-run")
    assert ran.returncode == 0, ran.stdout + ran.stderr
    lines = [x for x in ran.stdout.splitlines() if "Intel" in x]
    assert lines == [INTEL_LINE]
    assert pins()["java"]["macos_x64"]["url"] in ran.stdout
    assert pins()["java"]["macos_arm64"]["url"] not in ran.stdout
    assert len(step_lines(ran.stdout)) == 8
    assert_only_readers(tmp_path)
    assert_nothing_written(tmp_path)


def test_without_homebrew_the_run_prints_the_1_command_and_stops(tmp_path):
    env = fence(tmp_path, brew=False)
    ran = run(tmp_path, env)
    assert ran.returncode == 1
    command = pins()["homebrew"]["install"]
    assert ran.stdout.splitlines().count(f"  {command}") == 1, ran.stdout
    assert "Homebrew is not installed" in ran.stdout
    assert "then run ./install-macos.sh again" in ran.stdout
    assert len(step_lines(ran.stdout)) == 1
    assert_only_readers(tmp_path)
    assert_nothing_written(tmp_path)


def test_without_homebrew_the_dry_run_names_the_stop_and_goes_on(tmp_path):
    env = fence(tmp_path, brew=False)
    ran = run(tmp_path, env, "--dry-run")
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert f"  {pins()['homebrew']['install']}" in ran.stdout.splitlines()
    assert "the real run stops here" in ran.stdout
    assert len(step_lines(ran.stdout)) == 8
    assert_only_readers(tmp_path)


def test_off_macos_the_run_refuses_and_names_install_sh(tmp_path):
    env = fence(tmp_path, system="Linux", arch="x86_64")
    ran = run(tmp_path, env)
    assert ran.returncode == 1
    assert "install-macos.sh is for macOS" in ran.stderr
    assert "sudo ./install.sh" in ran.stderr
    assert step_lines(ran.stdout) == []
    assert_only_readers(tmp_path)
    assert_nothing_written(tmp_path)


def test_the_root_and_the_command_follow_their_variables(tmp_path):
    env = fence(tmp_path)
    env["WORKCENTER_ROOT"] = f"{tmp_path}/my root"
    env["WORKCENTER_LINK"] = f"{tmp_path}/bin2/workcenter"
    ran = run(tmp_path, env, "--dry-run", "--yes")
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert f"{tmp_path}/my root/venv" in ran.stdout
    assert f"{tmp_path}/bin2/workcenter" in ran.stdout
    assert "Application Support" not in ran.stdout
    assert not (tmp_path / "my root").exists()


def source_and_call(tmp_path: Path, env: dict, call: str) -> subprocess.CompletedProcess:
    """Source the script (its steps run only when it is executed) and call 1 function."""
    return subprocess.run(
        [BASH, "-c", f'set -euo pipefail; . "{SCRIPT}"; {call}'],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
    )


def test_sudo_is_asked_first_and_without_a_terminal_or_yes_the_run_stops(tmp_path):
    env = fence(tmp_path)
    ran = source_and_call(tmp_path, env, 'as_admin "copy KiCad into /Applications" ditto a b')
    assert ran.returncode == 1
    assert "needs sudo to copy KiCad into /Applications" in ran.stdout
    assert "sudo ditto a b" in ran.stdout
    assert "--yes" in ran.stderr
    assert "REFUSED sudo" not in "\n".join(called(tmp_path))


def test_sudo_after_yes_says_what_it_runs_first(tmp_path):
    env = fence(tmp_path)
    ran = source_and_call(tmp_path, env, 'YES=1; as_admin "copy KiCad into /Applications" ditto a b')
    assert "needs sudo to copy KiCad into /Applications" in ran.stdout
    assert "REFUSED sudo ditto a b" in called(tmp_path)
    said = ran.stdout.index("needs sudo")
    assert said >= 0


def test_a_checksum_that_differs_stops_the_run_and_names_both(tmp_path):
    """The check itself, with a real shasum: a stand-in prints what the real one prints."""
    env = fence(tmp_path)
    (tmp_path / "bin" / "shasum").write_text(f'#!{BASH}\necho "{"0" * 64}  $3"\n')
    want = pins()["freerouting"]["sha256"]
    ran = source_and_call(tmp_path, env, f'check_sha "{tmp_path}/f.jar" {want}')
    assert ran.returncode == 1
    assert f"expected {want}" in ran.stderr
    assert f"got {'0' * 64}" in ran.stderr
    ok = source_and_call(tmp_path, env, f'check_sha "{tmp_path}/f.jar" {"0" * 64}')
    assert ok.returncode == 0, ok.stderr


def test_the_command_it_writes_sets_every_path_via_reads(tmp_path):
    """The `workcenter` file the link step writes, printed by the function that makes it."""
    env = fence(tmp_path)
    ran = source_and_call(
        tmp_path,
        env,
        'ROOT="/x/Application Support/via"; SRC_DIR=/src; KICAD_DIR=/Applications/KiCad; '
        "BREW_PREFIX=/opt/homebrew; launcher_text",
    )
    assert ran.returncode == 0, ran.stderr
    out = ran.stdout
    assert out.startswith("#!/bin/bash\n")
    for name in (
        "WORKCENTER_ROOT",
        "WORKCENTER_SRC",
        "KICAD_CLI",
        "NGSPICE",
        "FREEROUTING_JAR",
        "KICAD_SYMBOL_DIR",
        "KICAD_FOOTPRINT_DIR",
        "KICAD10_3DMODEL_DIR",
    ):
        assert re.search(rf'^if \[ -z "\$\{{{name}:-\}}" \]; then {name}=', out, re.M), name
    assert "KICAD_CLI=/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli" in out
    assert "KICAD_SYMBOL_DIR=/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols" in out
    assert "NGSPICE=/opt/homebrew/bin/ngspice" in out
    last = 'exec "$WORKCENTER_ROOT/venv/bin/python" "$WORKCENTER_SRC/tools/workcenter" "$@"'
    assert out.rstrip().endswith(last)
    # The file it writes is a shell script bash reads, with the space in the root kept.
    script = tmp_path / "wc"
    script.write_text(out)
    probe = subprocess.run(
        [BASH, "-c", f'eval "$(sed -n "/^if/p" {script})"; printf "%s" "$WORKCENTER_ROOT"'],
        capture_output=True,
        text=True,
        env={"PATH": os.environ["PATH"]},
    )
    assert probe.stdout == "/x/Application Support/via", probe.stderr


# ---- the review's findings (E1 to E10) ----------------------------------------------------------------


def test_the_script_claims_no_proof_that_has_not_run():
    """No macOS CI job has run yet: the script says what it targets, not what is proven."""
    text = SCRIPT.read_text().lower()
    for word in ("proven", "proves", "proved"):
        assert word not in text, word
    assert "apple silicon is the target" in text


def stand_in(tmp_path: Path, name: str, body: str) -> None:
    p = tmp_path / "bin" / name
    p.write_text(f'#!{BASH}\nprintf "{name} %s\\n" "$*" >> "$CALLS"\n{body}\n')
    p.chmod(0o755)


def test_on_an_intel_mac_without_homebrew_the_run_stops_and_names_no_installer(tmp_path):
    """Homebrew's installer aborts on Intel: the script must not send the user there."""
    env = fence(tmp_path, arch="x86_64", brew=False)
    command = pins()["homebrew"]["install"]
    ran = run(tmp_path, env)
    assert ran.returncode == 1
    assert command not in ran.stdout + ran.stderr
    assert "Homebrew's installer no longer supports Intel" in ran.stderr
    assert len(step_lines(ran.stdout)) == 1
    assert_only_readers(tmp_path)
    assert_nothing_written(tmp_path)
    dry = run(tmp_path, env, "--dry-run")
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert command not in dry.stdout
    assert "the real run stops here" in dry.stdout


def test_homebrew_supports_macos_15_and_newer_and_the_run_says_so_below(tmp_path):
    hb = pins()["homebrew"]
    assert hb["min_macos"] == "15"
    assert "MACOS_OLDEST_SUPPORTED" in hb["source"]
    env = fence(tmp_path, macos="14.7")
    ran = run(tmp_path, env, "--dry-run")
    assert ran.returncode == 0, ran.stdout + ran.stderr
    lines = [x for x in ran.stdout.splitlines() if "macOS 14.7" in x]
    assert lines == [
        "[via] this is macOS 14.7: Homebrew supports macOS 15 and newer, so Python 3.12 builds from "
        "source here, which is slow and may fail."
    ], ran.stdout
    assert len(step_lines(ran.stdout)) == 8
    (tmp_path / "b").mkdir()
    again = run(tmp_path / "b", fence(tmp_path / "b", macos="15.0"), "--dry-run")
    assert again.returncode == 0, again.stdout + again.stderr
    assert "Homebrew supports" not in again.stdout


def test_below_macos_12_the_run_stops_for_kicad(tmp_path):
    env = fence(tmp_path, macos="11.7")
    ran = run(tmp_path, env)
    assert ran.returncode == 1
    assert "KiCad 10.0.8 needs macOS 12 or newer" in ran.stderr


def kicad_step(tmp_path: Path, env: dict, setup: str) -> subprocess.CompletedProcess:
    return source_and_call(tmp_path, env, f"{setup}; step_kicad")


def test_the_dry_run_shows_the_sudo_step_when_the_folder_is_not_writable(tmp_path):
    """can_write is the 1 test of writability; a dry run takes it too, so it shows the sudo question."""
    env = fence(tmp_path)
    ran = kicad_step(tmp_path, env, "DRY=1; can_write() { return 1; }; KICAD_DIR=/Applications/KiCad")
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert "this step needs sudo to copy KiCad into /Applications" in ran.stdout
    assert "would ask first, then run: sudo ditto" in ran.stdout
    writable = kicad_step(tmp_path, env, "DRY=1; can_write() { return 0; }; KICAD_DIR=/Applications/KiCad")
    assert "sudo" not in writable.stdout
    assert "would run: ditto" in writable.stdout
    assert_only_readers(tmp_path)
    assert_nothing_written(tmp_path)


def test_the_nearest_folder_that_exists_is_the_one_tested(tmp_path):
    env = fence(tmp_path)
    (tmp_path / "a").mkdir()
    ran = source_and_call(tmp_path, env, f'nearest_dir "{tmp_path}/a/b/c"; nearest_dir /no/such/folder')
    assert ran.stdout.splitlines() == [f"{tmp_path}/a", "/"], ran.stderr


def test_kicad_under_home_is_copied_without_sudo_and_its_folder_made(tmp_path):
    """Even when nothing seems writable, a folder under HOME is the user's: mkdir -p, never sudo."""
    env = fence(tmp_path)
    home = env["HOME"]
    ran = kicad_step(tmp_path, env, 'DRY=1; can_write() { return 1; }; KICAD_DIR="$HOME/Applications/KiCad"')
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert "sudo" not in ran.stdout
    assert f"would run: mkdir -p {home}/Applications" in ran.stdout
    runs = [shlex.split(x.split("would run: ", 1)[1]) for x in ran.stdout.splitlines() if "would run: " in x]
    assert ["ditto", "<a new temporary folder>/KiCad", f"{home}/Applications/KiCad"] in runs, runs
    env["KICAD_DIR"] = f"{home}/Applications/KiCad"
    whole = run(tmp_path, env, "--dry-run")
    assert whole.returncode == 0, whole.stdout + whole.stderr
    assert "sudo" not in whole.stdout.replace("Nothing here runs sudo", "")
    assert_only_readers(tmp_path)
    assert_nothing_written(tmp_path)


def test_another_kicad_in_the_way_is_the_users_and_the_side_by_side_install_comes_first(tmp_path):
    env = fence(tmp_path)
    other = tmp_path / "KiCad"
    other.mkdir()
    ran = kicad_step(tmp_path, env, f'DRY=0; KICAD_DIR="{other}"')
    assert ran.returncode == 1
    err = ran.stderr
    side = err.index('KICAD_DIR="$HOME/Applications/KiCad" ./install-macos.sh')
    assert side < err.index("ask before moving it"), err
    assert "Trash" not in err
    assert other.exists()


def test_the_ngspice_homebrew_installed_is_held_to_its_pin(tmp_path):
    env = fence(tmp_path)
    ok = source_and_call(tmp_path, env, "check_ngspice ngspice")
    assert ok.returncode == 0, ok.stderr
    assert "ngspice 47 from Homebrew, as pinned" in ok.stdout
    env["FAKE_LIST"] = "ngspice 48"
    other = source_and_call(tmp_path, env, "check_ngspice ngspice")
    assert other.returncode == 0, other.stderr
    assert "WARNING: Homebrew installed ngspice 48; Via pins 47" in other.stdout
    dry = source_and_call(tmp_path, env, "DRY=1; check_ngspice ngspice")
    assert "would check: brew list --versions ngspice names 47" in dry.stdout
    # The 2 real checks asked brew; the dry run did not.
    assert [x for x in called(tmp_path) if x.startswith("brew")] == ["brew list --versions ngspice"] * 2


@pytest.mark.parametrize("why", ["the copy fails", "sudo is not allowed"])
def test_a_stop_after_the_dmg_is_mounted_detaches_it_and_removes_its_folder(tmp_path, why):
    env = fence(tmp_path)
    k = pins()["kicad"]["macos"]
    root = Path(env["HOME"]) / "Library" / "Application Support" / "via"
    (root / "downloads").mkdir(parents=True)
    (root / "downloads" / k["file"]).write_text("a stand-in DMG")
    mnt = tmp_path / "tmp" / "via-kicad.test"
    stand_in(tmp_path, "shasum", f'echo "{k["sha256"]}  $3"')
    stand_in(tmp_path, "mktemp", f'/bin/mkdir -p "{mnt}"; echo "{mnt}"')
    stand_in(tmp_path, "hdiutil", "exit 0")
    stand_in(tmp_path, "ditto", "exit 1")
    stand_in(tmp_path, "mkdir", 'exec /bin/mkdir "$@"')
    stand_in(tmp_path, "rmdir", 'exec /bin/rmdir "$@"')
    if why == "the copy fails":
        setup = 'DRY=0; KICAD_DIR="$HOME/Applications/KiCad"'
    else:
        setup = "DRY=0; can_write() { return 1; }; KICAD_DIR=/Applications/KiCad"
    ran = kicad_step(tmp_path, env, setup)
    assert ran.returncode == 1, ran.stdout + ran.stderr
    lines = called(tmp_path)
    assert f"hdiutil detach {mnt}" in lines, lines
    attach = next(x for x in lines if x.startswith("hdiutil attach"))
    assert lines.index(f"hdiutil detach {mnt}") > lines.index(attach)
    assert not mnt.exists()


def test_every_pin_is_read_into_a_variable_on_its_own_line():
    """`set -e` ignores a failed substitution inside an argument; a bare assignment stops the run."""
    lines = [x.strip() for x in code_lines() if "$(pin " in x]
    assert len(lines) >= 20, lines
    bad = [x for x in lines if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*="\$\(pin [^)]*\)"', x)]
    assert bad == []


@pytest.mark.parametrize(
    "key,stop",
    [
        ("python.version", "step 1/8"),
        ("ngspice.version", "step 3/8"),
        ("kicad.macos.url", "download: "),
        ("freerouting.sha256", "step 6/8"),
    ],
)
def test_a_missing_pin_stops_the_run_and_names_its_key(tmp_path, key, stop):
    """A pin read inside an argument must stop the run too, not go on with an empty value."""
    d = pins()
    v = d
    parts = key.split(".")
    for part in parts[:-1]:
        v = v[part]
    del v[parts[-1]]
    cut = tmp_path / "pins.json"
    cut.write_text(json.dumps(d))
    env = fence(tmp_path)
    ran = source_and_call(tmp_path, env, f'PINS="{cut}"; main --dry-run')
    assert ran.returncode == 1, ran.stdout
    assert f"toolchain/desktop.json names no {key}" in ran.stderr
    if stop.startswith("step"):
        assert stop not in ran.stdout, ran.stdout
    else:
        assert "download:  (" not in ran.stdout, ran.stdout
    assert "dry run: nothing was installed" not in ran.stdout
