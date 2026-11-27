"""install.ps1 and workcenter.cmd: Via's native Windows install, held by reading the files.

Nothing here runs Windows. The tests read install.ps1, workcenter.cmd and toolchain/desktop.json:
- every pin the installer uses (version, address, SHA256) comes from desktop.json's `windows` section;
- every step that changes the computer goes through 1 of a few functions, and each of them prints the
  step and returns before acting in a dry run (`-DryRun` or `-WhatIf`);
- the installer asks before KiCad's and Python's installers (KiCad's may ask Windows for an
  administrator, for its Visual C++ runtime), never elevates or restarts the computer itself, and ends
  with `workcenter doctor`;
- the shim runs the venv's Python with tools/workcenter, at the root tools/hostos.py names.

When pwsh is on PATH, 1 test parses install.ps1 with PowerShell's own parser; on a machine with no
pwsh it skips, and the brace and string checks below hold the script's shape. The real run is the
Windows leg of CI.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install.ps1"
SHIM = ROOT / "workcenter.cmd"
PINS_FILE = ROOT / "toolchain" / "desktop.json"
SCRIPT = INSTALL.read_text(encoding="utf-8")
SHIM_TEXT = SHIM.read_text(encoding="utf-8")
PINS = json.loads(PINS_FILE.read_text(encoding="utf-8"))["windows"]

# The functions allowed to change the computer. Each prints its step and returns in a dry run.
ACTORS = (
    "Invoke-Tool",
    "Save-Download",
    "Expand-Zip",
    "New-Folder",
    "Copy-File",
    "Write-TextFile",
    "Add-UserPath",
    "Clear-Folder",
)
# What changes the computer in PowerShell: a native program through the call operator, and the
# cmdlets and .NET calls that write.
EFFECTS = re.compile(
    r"&\s*[$\"']|\bStart-Process\b|\bInvoke-WebRequest\b|\bInvoke-RestMethod\b|\bStart-BitsTransfer\b"
    r"|\bInvoke-Expression\b|\bExpand-Archive\b|\bNew-Item\b|\bCopy-Item\b|\bMove-Item\b|\bRemove-Item\b"
    r"|\bRename-Item\b|\bSet-Item\b|\bSet-ItemProperty\b|\bNew-ItemProperty\b|\bRemove-ItemProperty\b"
    r"|\bClear-Item\b|\[IO\.File\]::(?:Write|Append|Create|Delete|Move|Copy)\w*|\bWriteAllText\b"
    r"|\bSetEnvironmentVariable\b|\bwinget\s+install\b"
)


def code_only(text: str) -> str:
    """The script with its comments and the insides of its strings blanked (newlines kept), so that a
    brace or a cmdlet's name inside a string or a comment counts for nothing."""
    out = list(text)
    i, n = 0, len(text)

    def blank(a: int, b: int) -> None:
        for k in range(a, b):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        c = text[i]
        if text.startswith("<#", i):
            end = text.find("#>", i + 2)
            assert end >= 0, f"block comment at {i} never ends"
            blank(i, end + 2)
            i = end + 2
        elif c == "#":
            end = text.find("\n", i)
            end = n if end < 0 else end
            blank(i, end)
            i = end
        elif c == "'":
            k = i + 1
            while True:
                assert k < n, f"string at {i} never ends"
                if text[k] == "'" and text.startswith("''", k):
                    k += 2
                elif text[k] == "'":
                    break
                else:
                    k += 1
            blank(i + 1, k)
            i = k + 1
        elif c == '"':
            k = i + 1
            while True:
                assert k < n, f"string at {i} never ends"
                if text[k] == "`":
                    k += 2
                elif text.startswith('""', k):
                    k += 2
                elif text[k] == '"':
                    break
                else:
                    k += 1
            blank(i + 1, k)
            i = k + 1
        else:
            i += 1
    return "".join(out)


CODE = code_only(SCRIPT)


def closing(code: str, start: int) -> int:
    """The index of the brace that closes the one at `start`."""
    depth = 0
    for k in range(start, len(code)):
        if code[k] == "{":
            depth += 1
        elif code[k] == "}":
            depth -= 1
            if depth == 0:
                return k
    raise AssertionError(f"brace at {start} never closes")


def functions(code: str) -> dict[str, tuple[int, int]]:
    """Each function's name and the span of its body."""
    found = {}
    for m in re.finditer(r"^function\s+([\w-]+)\s*\{", code, re.M):
        start = m.end() - 1
        found[m.group(1)] = (start, closing(code, start))
    return found


FUNCTIONS = functions(CODE)


def load_hostos(monkeypatch, platform: str):
    monkeypatch.setattr(sys, "platform", platform)
    spec = importlib.util.spec_from_file_location("hostos_for_install_windows", ROOT / "tools" / "hostos.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- The pins ---------------------------------------------------------------------------------


def test_the_windows_pins_name_each_tool_with_an_address_a_sha256_and_a_source():
    assert sorted(PINS) == ["freerouting", "java", "kicad", "ngspice", "python", "sevenzip"]
    for name, pin in PINS.items():
        assert re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]), name
        assert pin["url"].startswith("https://"), name
        assert pin["version"] and pin["source"], name


def test_the_jar_pin_is_the_one_install_sh_checks_on_linux():
    """The same router and the same jar on every computer (winmac plan, choice 3)."""
    linux = (ROOT / "install.sh").read_text(encoding="utf-8")
    version = re.search(r'^FREEROUTING_VERSION="\$\{FREEROUTING_VERSION:-([^}]+)\}"', linux, re.M).group(1)
    sha = re.search(r'^FREEROUTING_SHA256="\$\{FREEROUTING_SHA256:-([0-9a-f]{64})\}"', linux, re.M).group(1)
    assert (PINS["freerouting"]["version"], PINS["freerouting"]["sha256"]) == (version, sha)


def test_kicad_is_pinned_to_the_10_0_release_and_python_to_3_12():
    assert PINS["kicad"]["version"].startswith("10.0.")
    assert PINS["python"]["version"].startswith("3.12.")
    assert PINS["kicad"]["version"] in PINS["kicad"]["url"]
    assert PINS["python"]["version"] in PINS["python"]["url"]


def test_every_pin_the_installer_uses_comes_from_the_pins_file():
    """No address, checksum or pinned version is written in the script itself; it reads each one."""
    for text, where in ((SCRIPT, "install.ps1"), (SHIM_TEXT, "workcenter.cmd")):
        assert re.findall(r"\b[0-9a-fA-F]{64}\b", text) == [], where
        assert re.findall(r"https?://", text) == [], where
        for name, pin in PINS.items():
            if len(pin["version"]) >= 4:
                assert pin["version"] not in text, (where, name)
    assert "toolchain" in SCRIPT and "desktop.json" in SCRIPT and "ConvertFrom-Json" in SCRIPT
    for name, pin in PINS.items():
        assert f"$Pins.{name}" in SCRIPT, name
        for field in pin:
            if field != "source":
                assert re.search(rf"\$Pins\.{name}\.{field}\b|\$pin\.{field}\b", SCRIPT), (name, field)


# --- The script's shape -------------------------------------------------------------------------


def test_the_script_parses_with_powershells_own_parser(tmp_path):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("no pwsh on this machine: the shape tests below hold the script")
    command = (
        "$e = $null; $t = $null; "
        f"[void][System.Management.Automation.Language.Parser]::ParseFile('{INSTALL}', [ref]$t, [ref]$e); "
        "$e | ForEach-Object { $_.Message }; exit $e.Count"
    )
    proc = subprocess.run(
        [pwsh, "-NoProfile", "-Command", command], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_script_is_ascii_so_windows_powershell_5_1_reads_it_as_written():
    """Windows PowerShell 5.1 reads a file without a byte order mark in the computer's ANSI code page:
    1 character past ASCII can change the script."""
    assert SCRIPT.isascii() and SHIM_TEXT.isascii()


def test_braces_parentheses_and_brackets_close_outside_strings_and_comments():
    for opener, closer in ("{}", "()", "[]"):
        depth = 0
        for line_no, line in enumerate(CODE.splitlines(), 1):
            for c in line:
                depth += (c == opener) - (c == closer)
                assert depth >= 0, (opener, line_no)
        assert depth == 0, opener
    assert "@'" not in CODE and '@"' not in CODE, "no here-strings: the shape check does not read them"


def test_no_variable_in_a_string_is_followed_by_a_colon():
    """In "$code: ..." PowerShell reads `$code:` as a variable of a drive named code and stops."""
    strings = re.findall(r'"(?:[^"`]|`.)*"', SCRIPT)
    bad = [s for s in strings for m in re.finditer(r"\$(\w+):", s) if m.group(1) not in ("env", "script")]
    assert bad == []


def test_every_variable_a_function_reads_is_set_in_it_or_at_the_scripts_top():
    """Set-StrictMode stops at a variable never set: a message in Install-KiCad named `$series`, which
    only Find-KiCadCli sets."""
    top = set(re.findall(r"^\$(\w+)\s*=", SCRIPT, re.M)) | {"Root", "Downloads", "Yes", "DryRun", "Pins"}
    top |= {"true", "false", "null", "_", "LASTEXITCODE", "WhatIfPreference", "PSScriptRoot"}
    top |= {"ErrorActionPreference", "ProgressPreference", "script", "env"}  # $script:X, $env:X
    unset = []
    for name, (a, b) in FUNCTIONS.items():
        raw = SCRIPT[a:b]
        own = set(re.findall(r"\$(\w+)\s*(?:=|\+=)", raw))
        own |= set(re.findall(r"\[[\w\[\]]+\]\$(\w+)", raw))  # param([string]$Name)
        own |= set(re.findall(r"foreach \(\$(\w+) in", raw))
        own |= set(re.findall(r"param\(\$(\w+)\)", raw))
        known = {v.lower() for v in own | top}  # PowerShell's names ignore case
        used = set(re.findall(r"(?<![\w:])\$(\w+)", raw))
        unset += [(name, v) for v in sorted(used) if v.lower() not in known]
    assert unset == []


def test_the_script_runs_on_powershell_5_1_and_7_and_stops_at_the_first_error():
    assert re.search(r"^#Requires -Version 5\.1$", SCRIPT, re.M)
    assert "[CmdletBinding(SupportsShouldProcess = $true)]" in SCRIPT
    assert "Set-StrictMode -Version 3.0" in SCRIPT
    assert "$ErrorActionPreference = 'Stop'" in SCRIPT
    # 5.1 writes a byte order mark with these; Via reads java.path as plain UTF-8.
    for writer in ("Set-Content", "Out-File", "Add-Content"):
        assert writer not in CODE, writer
    # 5.1's web client needs TLS 1.2 named; its progress bar makes a download many times slower.
    assert "[Net.SecurityProtocolType]::Tls12" in SCRIPT
    assert "$ProgressPreference = 'SilentlyContinue'" in SCRIPT


# --- Dry run ------------------------------------------------------------------------------------


def test_only_the_acting_functions_change_the_computer():
    """A line that installs, downloads, writes or changes the user's PATH sits inside 1 of ACTORS."""
    assert set(ACTORS) <= set(FUNCTIONS)
    spans = [FUNCTIONS[name] for name in ACTORS]
    outside = [
        CODE.count("\n", 0, m.start()) + 1
        for m in EFFECTS.finditer(CODE)
        if not any(a < m.start() < b for a, b in spans)
        and not (FUNCTIONS["Get-ToolOutput"][0] < m.start() < FUNCTIONS["Get-ToolOutput"][1])
    ]
    assert outside == []


def test_each_acting_function_prints_its_step_and_returns_in_a_dry_run():
    for name in ACTORS:
        a, b = FUNCTIONS[name]
        body = SCRIPT[a:b]
        step = body.find("Write-Step")
        guard = body.find("if ($script:DryRun) { return")
        first = EFFECTS.search(CODE[a:b])
        assert 0 <= step < guard, name
        assert first is None or guard < first.start(), name


def test_dry_run_is_a_switch_and_whatif_means_the_same():
    assert re.search(r"\[switch\]\$DryRun", SCRIPT)
    assert "$script:DryRun = [bool]$DryRun -or [bool]$WhatIfPreference" in SCRIPT


def test_a_question_to_a_program_is_never_an_install():
    """Get-ToolOutput runs a program in a dry run too: only to ask a version or a path."""
    calls = [line for line in SCRIPT.splitlines() if "Get-ToolOutput " in line and "function" not in line]
    assert calls
    for line in calls:
        assert not re.search(r"\binstall\b|\bvenv\b|\bpip\b|\b x\b", line), line


# --- What it asks, what it installs, how it ends ------------------------------------------------


def body(name: str) -> str:
    a, b = FUNCTIONS[name]
    return SCRIPT[a:b]


def test_kicad_and_python_come_from_winget_for_this_user_at_the_pinned_version():
    for name in ("Install-KiCad", "Install-Python"):
        text = body(name)
        for flag in ("'install'", "'--exact'", "'--id'", "'--version'", "'--scope'", "'user'", "'--silent'"):
            assert flag in text, (name, flag)
        assert "--accept-package-agreements" in text and "--accept-source-agreements" in text
    assert "$Pins.kicad.winget_id" in body("Install-KiCad")
    assert "$Pins.python.winget_id" in body("Install-Python")


def test_java_is_the_temurin_zip_not_wingets_machine_wide_msi():
    """winget's EclipseAdoptium.Temurin.21.JRE and .JDK (21.0.11.10, 21.0.12.8) are MSI packages of
    Scope machine only: an administrator. The zip goes under the root and needs none."""
    assert "Temurin" not in CODE
    text = body("Install-Java")
    assert "$Pins.java" in text and "Expand-Zip" in text and "java.path" in text


def test_every_download_is_checked_by_its_sha256_before_use():
    text = body("Save-Download")
    assert "Get-FileHash" in text and "SHA256" in text
    # A file already there with the right hash is used again: a second run downloads nothing.
    assert text.find("Test-Sha256") < text.find("Invoke-WebRequest")
    calls = re.findall(r"Save-Download\s+(\$Pins\.\w+|\$pin)\b", CODE)
    assert sorted(set(calls)) == ["$pin"]
    assert sorted(re.findall(r"Get-Pinned\s+\$Pins\.(\w+)", SCRIPT)) == sorted(
        ["freerouting", "java", "ngspice", "sevenzip", "kicad", "python"]
    )


def test_it_asks_before_an_installer_that_can_ask_for_an_administrator():
    for name in ("Install-KiCad", "Install-Python"):
        text = body(name)
        assert 0 <= text.find("Confirm-Step") < text.find("Invoke-Tool"), name
    assert "administrator" in body("Install-KiCad")
    ask = body("Confirm-Step")
    assert "$Yes" in ask and "Read-Host" in ask and "$script:DryRun" in ask


def test_it_never_elevates_or_restarts_and_stops_when_an_installer_wants_a_restart():
    for word in ("RunAs", "Restart-Computer", "shutdown", "Stop-Computer"):
        assert word not in CODE, word
    # winget's return codes (winget-cli doc returnCodes.md): restart to finish, restart then try again,
    # restart started.
    for code in ("-1978334967", "-1978334966", "-1978334965"):
        assert code in SCRIPT, code
    assert "restart" in body("Assert-NoRestart").lower()


def test_a_second_run_keeps_what_the_first_one_made():
    assert "Test-Path" in body("Install-Venv") and "pyvenv.cfg" in body("Install-Venv")
    for name in ("Install-Java", "Install-Ngspice"):
        assert "Test-Stamp" in body(name), name
    # The jar is 1 file: its own SHA256 says it is there.
    assert "Test-Sha256 $jar $Pins.freerouting.sha256" in body("Install-FreeRouting")
    assert "-notcontains" in body("Add-UserPath")
    # The user's PATH is read raw, so a %VARIABLE% in it stays a variable.
    assert "DoNotExpandEnvironmentNames" in body("Add-UserPath")
    assert "ExpandString" in body("Add-UserPath")


def test_an_existing_kicad_10_is_kept():
    text = body("Install-KiCad")
    assert text.find("Find-KiCadCli") < text.find("Confirm-Step")


def test_the_last_step_is_workcenter_doctor_through_the_shim():
    calls = [m for m in re.finditer(r"Invoke-Tool\b[^\n]*", SCRIPT)]
    assert "doctor" in calls[-1].group(0)
    main = SCRIPT[SCRIPT.rindex("# --- Main") :]
    steps = re.findall(r"^(Install-\w+|Add-Shim|Invoke-Doctor)\b", main, re.M)
    assert steps[-1] == "Invoke-Doctor"
    assert steps == [
        "Install-KiCad",
        "Install-Python",
        "Install-Java",
        "Install-Ngspice",
        "Install-FreeRouting",
        "Install-Venv",
        "Add-Shim",
        "Invoke-Doctor",
    ]


def test_the_root_is_the_one_hostos_names_on_windows(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", "/la")
    hostos = load_hostos(monkeypatch, "win32")
    assert hostos.default_root() == Path("/la") / "Via"
    assert hostos.venv_python(Path("/r")).relative_to("/r").parts == ("venv", "Scripts", "python.exe")
    assert "Join-Path $env:LOCALAPPDATA 'Via'" in SCRIPT
    assert "venv\\Scripts\\python.exe" in SCRIPT


# --- The shim -----------------------------------------------------------------------------------


def test_the_shim_runs_tools_workcenter_with_the_venvs_python():
    lines = SHIM_TEXT.splitlines()
    assert lines[0] == "@echo off"
    assert "setlocal" in lines
    assert 'if not defined WORKCENTER_ROOT set "WORKCENTER_ROOT=%LOCALAPPDATA%\\Via"' in lines
    assert 'set "VIA_PY=%WORKCENTER_ROOT%\\venv\\Scripts\\python.exe"' in lines
    assert '"%VIA_PY%" "%~dp0tools\\workcenter" %*' in lines
    assert lines[-1] == "exit /b %ERRORLEVEL%"


def test_the_shim_has_no_labels_so_line_endings_cannot_break_it():
    """cmd.exe can miss a label in a file with LF line endings; the shim has no label and no goto."""
    for line in SHIM_TEXT.splitlines():
        assert not line.lstrip().startswith(":"), line
        assert "goto" not in line.lower(), line


def test_the_shims_ngspice_is_where_the_installer_puts_it():
    exe = "\\".join(PINS["ngspice"]["exe"].split("/"))
    assert f'"%WORKCENTER_ROOT%\\ngspice\\{exe}"' in SHIM_TEXT
    assert "Join-Path $Root 'ngspice'" in SCRIPT


def test_the_installer_puts_a_shim_on_the_users_path_that_hands_over_to_this_one():
    text = body("Add-Shim")
    assert "workcenter.cmd" in text and "Add-UserPath" in text and "Write-TextFile" in text
    assert "Join-Path $Root 'bin'" in text


# --- Findings of the independent review (F-1 to F-10) --------------------------------------------


def test_python_installs_its_py_launcher_for_this_user_only_on_both_paths():
    """Python 3.12's installer defaults InstallLauncherAllUsers to -1 (cpython v3.12.10
    Tools/msi/bundle/bundle.wxs:31), and its launcher_AllUsers package is ForcePerMachine with
    InstallCondition "(InstallAllUsers or InstallLauncherAllUsers) and Include_launcher"
    (packagegroups/launcher.wxs): an administrator. InstallLauncherAllUsers=0 picks launcher_JustForMe.
    winget's manifest switches (Custom: InstallAllUsers=0 PrependPath=1) do not say it, so the winget
    call replaces them with the same per-user switches as the installer's own path."""
    switches = PINS["python"]["user_switches"].split()
    assert "InstallAllUsers=0" in switches and "InstallLauncherAllUsers=0" in switches
    assert "/quiet" in switches
    text = body("Install-Python")
    assert "'--override', $Pins.python.user_switches" in text
    assert "($Pins.python.user_switches -split ' ')" in text


def test_every_winget_install_names_the_winget_source():
    """Without --source, winget also asks the msstore source, which can fail or prompt."""
    for name in ("Install-KiCad", "Install-Python"):
        assert "'--source', 'winget'" in body(name), name


def test_every_download_sends_a_plain_user_agent():
    """SourceForge sends PowerShell's default user agent a web page instead of the 7z (seen with curl
    -A 'WindowsPowerShell/5.1': 200 text/html; -A 'via-install': the 13814879-byte archive)."""
    calls = [line for line in body("Save-Download").splitlines() if "Invoke-WebRequest" in line]
    assert calls and all("-UserAgent" in line for line in calls)
    assert len(re.findall(r"\bInvoke-WebRequest\b", CODE)) == len(calls)


def test_when_nobody_can_answer_the_stop_names_the_persons_yes():
    """A coding agent reads the stop message, not the help: it must say to ask the person first."""
    text = body("Confirm-Step")
    stop = [line for line in text.splitlines() if "Stop-Install" in line]
    assert len(stop) == 1
    assert "Ask the person" in stop[0] and "Only if they say yes" in stop[0] and "-Yes" in stop[0]


def test_the_path_change_is_announced_even_when_the_users_path_is_expandable():
    """Windows' default user PATH holds %USERPROFILE%; Set-ItemProperty tells nobody. Setting and
    clearing a user variable through .NET sends WM_SETTINGCHANGE, so a new terminal sees the PATH."""
    text = body("Add-UserPath")
    expand = text.find("-Type ExpandString")
    assert expand >= 0
    after = text[expand:]
    assert after.count("SetEnvironmentVariable(") >= 2
    assert "$null, 'User')" in after
    # Until a run confirms it, the last line also names the shim's full path.
    main = SCRIPT[SCRIPT.rindex("# --- Main") :]
    assert "$script:Shim" in main[main.rindex("Via is installed") - 200 :]


def test_a_new_ngspice_pin_unpacks_into_an_empty_folder():
    text = body("Install-Ngspice")
    assert 0 <= text.find("Clear-Folder $dest") < text.find("Invoke-Tool")
    clear = body("Clear-Folder")
    assert "Remove-Item" in clear and "-Recurse" in clear


def test_a_kicad_cli_that_is_there_but_silent_points_at_the_visual_cpp_runtime():
    """KiCad's NSIS script runs VC_redist.x64.exe and ignores its exit; a declined administrator
    prompt leaves kicad-cli.exe unable to start."""
    text = body("Install-KiCad")
    assert "Test-Path" in text and "Visual C++" in text and "administrator" in text
    assert "learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist" in text


@pytest.mark.skipif(sys.platform != "win32", reason="runs install.ps1 itself: Windows only")
def test_a_dry_run_on_windows_exits_0_and_makes_nothing(tmp_path):
    root = tmp_path / "via-root"
    shell = shutil.which("powershell") or shutil.which("pwsh")
    assert shell
    command = [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(INSTALL)]
    proc = subprocess.run(
        [*command, "-DryRun", "-Root", str(root)],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "nothing was installed" in proc.stdout
    assert not root.exists()
