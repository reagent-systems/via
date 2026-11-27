# Install Via

This file is for a coding agent that sets Via up, and for the person beside it.
Each step has a command, a check, and what to do when the check fails.
The install is finished when the checks under "Done when" hold.

## Rules for the agent

1. Read this whole file before the first command.
2. Before a command that needs sudo, an administrator, a restart, or a large download (over 1 GB),
   tell the person what it does and wait for a yes.
3. Never type a password. When a command asks for one, ask the person to run it in their own terminal.
4. Never pipe a download into a shell. Run each installer as a file.
5. Never edit Via's files to make a check pass.
6. Never install a second KiCad beside the one a route installs. Never remove one the person has.
7. Run each step's check before the next step.
8. When a check fails, do what its step says, once. When it fails twice, stop.
   Show the person the command and the last 20 lines it printed.
9. Report each step with its check. A step with no check run is not done.
10. Stop when "Done when" holds. Show the person the last lines of each check.

## Pick the route

Find the platform with 1 command:

- In a POSIX shell (Linux, macOS): `uname -sm`. It prints `Linux x86_64`, `Darwin arm64`, and so on.
- In PowerShell (Windows): `[Environment]::OSVersion.VersionString` and `$env:PROCESSOR_ARCHITECTURE`.

| Platform | Route | State |
|---|---|---|
| Ubuntu 24.04 (x86_64 or arm64) | L | Proven on GitHub's runners (ubuntu-24.04). |
| macOS 12 or later, Apple Silicon (`Darwin arm64`) | M | Not yet proven: the first CI run will say. |
| macOS 12 or later, Intel (`Darwin x86_64`) | M | Best effort: no CI job runs on an Intel Mac. |
| Windows 10 or 11, x64 | N, or W when the person asks for Linux | N and W are not yet proven: the first CI run will say. |
| Any computer with Docker | D | The image is proven on GitHub's Linux runners; Docker Desktop on macOS and Windows is not proven. |
| Another Linux | D | install.sh refuses every release but Ubuntu 24.04. |
| Windows on Arm | W or D | Not offered natively: ngspice's Windows build is x64 only. |

Tell the person the route and its state before step 1.

Every route but D starts the same way: a clone of Via in the home folder.
When the folder `via` in the home folder is already a clone of Via, keep it and run `git pull` in it.
The rest of this file names that folder `~/via` (on Windows, `$HOME\via`).

## Route L: Linux, Ubuntu 24.04

1. Check the release.
   - Run: `. /etc/os-release && echo "$VERSION_ID"`
   - Check: it prints `24.04`.
   - Fail: another release. Use route D.
2. Get Via.
   - Run: `git clone https://github.com/reagent-systems/via ~/via`
   - Check: `ls ~/via/install.sh` names the file.
   - Fail: `git` is absent. Ask the person before `sudo apt-get install -y git`.
3. Install the engines: KiCad 10, ngspice, Java 21, FreeRouting. This needs sudo.
   - Tell the person: "install.sh installs KiCad 10, ngspice, Java 21 and FreeRouting as root,
     under `/opt/workcenters/ee`, and links `workcenter` into `/usr/local/bin`."
   - When the person says yes, ask them to run in their own terminal: `cd ~/via && sudo ./install.sh`
   - When your shell runs as root and the person said yes, run it yourself.
   - Check: the last lines it prints are the doctor's. The first of them starts with `workcenter ee:`.
   - Fail: a line `[install] ERROR:` names the cause. Show it to the person.
     Run the script again once only when the line names a slow or stalled download.
4. Go to "Done when". Run its commands in `~/via`.

`./install.sh --check` runs the doctor alone, with no sudo.

## Route M: macOS

The installer is `install-macos.sh`. It installs for your own user, under
`~/Library/Application Support/via`: Homebrew's Python 3.12 and ngspice, KiCad 10 from its
pinned disk image into `/Applications/KiCad`, Java 21, FreeRouting, and the `workcenter` command
in `~/.local/bin`. It checks every download by its SHA256.
KiCad's disk image is about 1.4 GB: ask the person before step 4.

1. Check Homebrew.
   - Run: `brew --version`
   - Check: it prints `Homebrew` and a version.
   - Fail: Homebrew is absent. Tell the person and stop. Homebrew's own page, https://brew.sh,
     gives the 1 command that installs it; it asks for the person's password, so the person runs it.
2. Get Via.
   - Run: `git clone https://github.com/reagent-systems/via ~/via`
   - Check: `ls ~/via/install-macos.sh` names the file.
   - Fail: macOS opens a window that offers the command line developer tools. Ask the person to
     accept it, then run the step again.
3. Show the person the plan.
   - Run: `cd ~/via && ./install-macos.sh --dry-run`
   - Check: it prints every step and every command, and runs none.
4. Install. Ask the person first: it downloads about 1.4 GB, and it may ask for sudo once.
   - Run: `cd ~/via && ./install-macos.sh`
   - When `/Applications` is not writable, the script asks before sudo. With no terminal to ask on,
     it stops and names `--yes`. Pass `--yes` only when the person said yes to sudo.
   - Check: the last lines are the doctor's. The first of them starts with `workcenter ee:`.
   - Fail: a line `[via] ERROR:` names the cause. Show it to the person. Run the step again once.
5. Open a new terminal, so that `~/.local/bin` is on PATH.
   - Check: `command -v workcenter` prints a path that ends in `/.local/bin/workcenter`.
   - Fail: tell the person that `~/.local/bin` is not on PATH. The script wrote 1 line for it into
     `~/.zprofile` (or `~/.bash_profile`).
6. Go to "Done when". Run its commands in `~/via`.

An Intel Mac is best effort: Homebrew builds Python 3.12 from source there, which is slow.
The script stops in an x86_64 shell on Apple Silicon (Rosetta) and on macOS older than 12.

## Route N: Windows, native

The installer is `install.ps1`. It installs for your own user, under `%LOCALAPPDATA%\Via`, with
no administrator of its own: KiCad 10 and Python 3.12 through winget, Java 21, ngspice, FreeRouting,
a venv, and the `workcenter` command on your PATH. It checks every download by its SHA256.
KiCad is about 1 GB: ask the person before step 4.
KiCad's installer may ask Windows for an administrator once, for Microsoft's Visual C++ runtime.

Run every command in PowerShell, not in cmd.exe.

1. Check Git.
   - Run: `git --version`
   - Check: it prints `git version`.
   - Fail: ask the person before `winget install --id Git.Git -e --source winget`
     (the command git-scm.com gives). Then open a new PowerShell and run the check again.
2. Get Via.
   - Run: `git clone https://github.com/reagent-systems/via "$HOME\via"`
   - Check: `Test-Path "$HOME\via\install.ps1"` prints `True`.
3. Show the person the plan.
   - Run: `Set-Location "$HOME\via"; powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1 -DryRun`
   - Check: it prints every step, each line starting with `would:`, and installs nothing.
4. Install. Ask the person first: it downloads about 1 GB, and KiCad's installer may show a
   Windows prompt for an administrator.
   - Run: `Set-Location "$HOME\via"; powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1`
   - Pass `-Yes` only when the person said yes to every question it asks.
   - Check: the last lines are the doctor's. The first of them starts with `workcenter ee:`.
   - Fail: the script says an installer asked for a restart. Tell the person; after the restart,
     run the step again. Any other failure: show it to the person, and run the step again once.
5. Open a new PowerShell, so that the new PATH holds.
   - Check: `Get-Command workcenter` finds the command.
6. Go to "Done when". Run its commands in `$HOME\via`.

Native Windows needs Via's Windows port. Until the port is on `main`, every `workcenter` command
stops at its start with `No module named 'fcntl'`. Then tell the person, and use route W or route D.

## Route W: Windows, through WSL2

WSL2 runs Ubuntu 24.04 inside Windows. Via then installs with route L, unchanged.
It needs Windows 10 version 2004 (build 19041) or later, or Windows 11.

Run these commands in PowerShell.

1. Check for WSL and Ubuntu 24.04.
   - Run: `wsl -l -v`
   - Check: a line names `Ubuntu-24.04` with VERSION `2`. Then go to step 4.
2. Install WSL and Ubuntu 24.04. This needs an administrator and a restart.
   - Tell the person both, and wait for a yes.
   - Ask the person to run in a PowerShell opened with "Run as administrator":
     `wsl --install -d Ubuntu-24.04`
   - Fail: the command prints WSL's help text. WSL is there already; ask the person to run
     `wsl --install -d Ubuntu-24.04` again after `wsl --list --online` names `Ubuntu-24.04`.
     When the list does not name it, show the list to the person and stop.
3. Ask the person to restart, open "Ubuntu 24.04" from the Start menu, and make a Linux user.
   - The Linux password is the person's. Never ask for it.
4. Run route L inside Ubuntu.
   - Run each command as: `wsl -d Ubuntu-24.04 -- bash -lc '<command>'`
   - Keep Via and the boards in the Linux home folder (`~/via`), not under `/mnt/c`.
   - Route L's step 3 needs sudo: ask the person to open "Ubuntu 24.04" and run
     `cd ~/via && sudo ./install.sh` there.
5. Go to "Done when". Run each of its commands as `wsl -d Ubuntu-24.04 -- bash -lc 'cd ~/via && <command>'`.

## Route D: Docker

The image holds what install.sh installs on Ubuntu 24.04, and Via with its fixture boards.
It is built for amd64 and arm64. The arm64 image has no openEMS; a board needs none.

The image the repository publishes is `ghcr.io/reagent-systems/via:main`.
Today (2026-11-27) ghcr.io refuses an anonymous pull of it: "authentication required".
`ghcr.io/thyfriendlyfox/via:main`, the last image built before the repository moved, answers an
anonymous pull. It is older than `main`.

1. Check Docker.
   - Run: `docker version`
   - Check: it prints a `Server:` part.
   - Fail: Docker is absent or not running. Ask the person to install or start Docker Desktop
     (Windows, macOS) or Docker Engine (Linux), then run the check again.
2. Pull the image. Ask the person first: it is a large download.
   - Run: `docker pull ghcr.io/reagent-systems/via:main`
   - Check: its last line names the image.
   - Fail: `denied` or `unauthorized`. The package is not public yet. Tell the person, and with
     their yes use `ghcr.io/thyfriendlyfox/via:main` in its place, in every command below.
3. Go to "Done when", with each command in the container's form below.

The container's form of the 3 checks of "Done when". The fixture boards are inside the image,
under `/opt/workcenters/ee/src/tests/boards`. Each gates check copies its board to `/tmp` in the
container first, because the gates write beside the board:

```sh
docker run --rm ghcr.io/reagent-systems/via:main workcenter doctor
docker run --rm ghcr.io/reagent-systems/via:main sh -c 'cp -r /opt/workcenters/ee/src/tests/boards/pass-first-design /tmp/ && workcenter gates /tmp/pass-first-design'
docker run --rm ghcr.io/reagent-systems/via:main sh -c 'cp -r /opt/workcenters/ee/src/tests/boards/fail-drc-clearance /tmp/ && workcenter gates /tmp/fail-drc-clearance'
```

The 3 lines are the same in a POSIX shell and in PowerShell. Nothing is mounted, so nothing is
written on the computer.

On your own board, mount its folder on `/work`, the image's working folder:
`docker run --rm --user "$(id -u):$(id -g)" -v "$PWD":/work ghcr.io/reagent-systems/via:main workcenter gates .`
(in PowerShell: `docker run --rm -v "${PWD}:/work" ghcr.io/reagent-systems/via:main workcenter gates .`).

## Done when

All 3 hold, each run in the clone of Via (route D: in the container's form):

1. `workcenter doctor` exits 0, and its first line starts with `workcenter ee: ok`.
2. `workcenter gates tests/boards/pass-first-design` exits 0, and its last line starts with `GREEN: divider`.
3. `workcenter gates tests/boards/fail-drc-clearance` exits 1, and its last line starts with `RED: rc_divider`.
   This board breaks a clearance on purpose. GREEN here means the install is wrong.

Check 3 proves the gates can say RED. An install that says GREEN to everything is not done.

The doctor may say `degraded` for a tool a route does not install. These rows are allowed, and only
on these routes; report them to the person, and the install is done:

| Route | Rows that may be absent |
|---|---|
| M, N | `xvfb`, `openems`, `rsvg-convert`, `ffmpeg`: renders through Xvfb and openEMS run on Linux and in Docker only. |
| D on arm64 | `openems`: the arm64 image has none. |

When a check fails:

| What the run printed | What to do |
|---|---|
| `MISSING kicad-cli`, or a kicad-cli version that does not start with `10.` | The route's KiCad step did not finish, or another KiCad comes first on PATH. Run that step again once. Never remove a KiCad. |
| `MISSING ngspice` | Run the route's install step again once. |
| `MISSING python` | Via needs Python 3.12 or later. Run the route's install step again once. |
| `degraded, without` a row the table above does not allow | Show the doctor's whole output to the person and stop. |
| `SKIPPED`, exit 2 | An engine is absent. This is not GREEN. Show the line to the person and stop. |
| `RED` on pass-first-design | Show the whole output to the person and stop. This board is GREEN on Ubuntu 24.04. |
| `GREEN` on fail-drc-clearance | Show the whole output to the person and stop. The DRC did not run as it must. |
| `No module named 'fcntl'` | Native Windows without Via's Windows port. Use route W or route D. |
| `workcenter` is not found | Open a new terminal. Then run the route's PATH check. |

## Report to the person

- the platform and the route, with its state from the table above
- each step, and its check
- the doctor's first line, and every row that is not `ok`
- the last line of each gate run, with its exit code

A route not yet proven on GitHub's runners (M, N, W, or D on macOS or Windows) has no record of a
run yet. Tell the person that a report of this run in an issue at
https://github.com/reagent-systems/via/issues helps the next person.

## Next

`workcenter new ~/my-board` starts a board in a folder of its own.
`workcenter next ~/my-board` names the one next step, until the board is GREEN.
