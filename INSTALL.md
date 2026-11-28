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
6. Never remove or move a KiCad the person has. Install KiCad 10 beside another version only with the person's yes.
7. Run each step's check before the next step.
8. When a check fails, do what its step says, once. When it fails twice, stop.
   Show the person the command and the last 20 lines it printed.
9. Report each step with its check. A step with no check run is not done.
10. Stop when "Done when" holds. Show the person the last lines of each check.

## Pick the route

Find the platform with 1 command:

- In a POSIX shell (Linux, macOS): `uname -sm`. It prints `Linux x86_64`, `Darwin arm64`, and so on.
- In PowerShell (Windows): `[Environment]::OSVersion.VersionString` and `$env:PROCESSOR_ARCHITECTURE`.
- In Git Bash on Windows (an agent's shell tool can be Git Bash), `uname -sm` prints a name that starts
  with `MINGW64_NT` or `MSYS_NT`. That is Windows: use route N or W, and run their commands through
  PowerShell (your PowerShell tool, or `powershell -NoProfile -Command "..."`).

| Platform | Route | State |
|---|---|---|
| Ubuntu 24.04 (x86_64 or arm64) | L | Proven on GitHub's runners (ubuntu-24.04). |
| macOS 12 or later, Apple Silicon (`Darwin arm64`) | M | Proven on GitHub's runners (macos-latest, arm64) by run 46084159219 (2026-11-27): M installed and the smoke passed all 8 steps, 868 of its 950 tests passed and none failed; again by run 46089464718 (2026-11-28), 878 of 960, none failed. On macOS 12 to 14, Homebrew is not supported: it builds Python and ngspice from source, which is slow and may fail. |
| macOS 12 or later, Intel (`Darwin x86_64`) | M with a Homebrew already installed, else D | Best effort: no CI job runs on an Intel Mac. Homebrew's installer refuses an Intel Mac. On macOS 12 to 14, Homebrew is not supported: it builds Python and ngspice from source, which is slow and may fail. |
| Windows 10 or 11, x64 | N, or W when the person asks for Linux | Proven on GitHub's runners (windows-latest), N and W. N by run 46093588252 (2026-11-28): it installed and the smoke passed all 8 steps, 788 of its 963 tests passed and none failed; 99 tests that need kicad-cli or ngspice were not judged in that run, by marks that looked on `PATH` alone, and the marks now ask where Via finds them. N's 3 earlier runs failed 84, 12 and 1 tests, on causes fixed since. W by run 46084159219 (2026-11-27): all 8 steps, 947 of 950 tests, none failed; again by run 46089464718 (2026-11-28), 957 of 960, none failed. |
| Any computer with Docker | D | Not proven, and no GitHub runner can prove it on macOS or Windows (Docker Desktop). The image build runs the gates in it on Linux, amd64 and arm64. |
| Another Linux | D | Not offered natively: install.sh refuses every release but Ubuntu 24.04. |
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

The installer is `install-macos.sh`. It installs for your own user. KiCad 10 comes from its pinned
disk image into `/Applications/KiCad`. Java 21, FreeRouting and Via's venv go under
`~/Library/Application Support/via`, and the `workcenter` command into `~/.local/bin`.
KiCad's disk image, Java and FreeRouting are checked against Via's pinned SHA256.
Python 3.12 and ngspice come from Homebrew, into Homebrew's own prefix, at the version Homebrew has;
the script warns when ngspice differs from Via's pin.
KiCad's disk image is about 1.4 GB: ask the person before step 4.

1. Check Homebrew.
   - Run: `brew --version`
   - Check: it prints `Homebrew` and a version.
   - Fail on Apple Silicon: Homebrew is absent. Tell the person and stop. Homebrew's own page,
     https://brew.sh, gives the 1 command that installs it; it asks for the person's password, so the
     person runs it.
   - Fail on Intel: Homebrew's installer refuses an Intel Mac (its install.sh stops with "Homebrew on
     macOS is only supported on Apple Silicon processors!"). Without a Homebrew already installed,
     use route D.
2. Get Via.
   - Run: `git clone https://github.com/reagent-systems/via ~/via`
   - Check: `ls ~/via/install-macos.sh` names the file.
   - Fail: macOS opens a window that offers the command line developer tools. Ask the person to
     accept it, then run the step again.
3. Show the person the plan.
   - Run: `cd ~/via && ./install-macos.sh --dry-run`
   - Check: it prints every step and every command, and its last line is
     `[via] dry run: nothing was installed, written or downloaded`.
4. Install. Ask the person first: it downloads about 1.4 GB, and it may ask for sudo once.
   - Run: `cd ~/via && ./install-macos.sh`
   - When `/Applications` is not writable, the script asks before sudo. With no terminal to ask on,
     it stops and names `--yes`. Pass `--yes` only when the person said yes to sudo.
   - Check: the last lines are the doctor's. The first of them starts with `workcenter ee:`.
   - Fail: a line `[via] ERROR:` names the cause. Show it to the person.
     When it names another KiCad in `/Applications/KiCad`, keep that KiCad. Ask the person whether
     KiCad 10 may go beside it, in `~/Applications/KiCad`. With their yes, run
     `cd ~/via && KICAD_DIR="$HOME/Applications/KiCad" ./install-macos.sh`.
     Any other cause: run the step again once.
5. Find `workcenter`.
   - The script put `~/.local/bin` on PATH in `~/.zprofile` (or `~/.bash_profile`), for new terminals.
     Your shell keeps the PATH it started with, so run every `workcenter` command by its full path.
   - Run: `~/.local/bin/workcenter doctor`
   - Check: its first line starts with `workcenter ee:`.
   - Fail: no such file. Step 4 did not finish: show the person its last 20 lines.
   - Tell the person: a new terminal of theirs finds `workcenter` by name.
6. Go to "Done when". Run its commands in `~/via`, with `~/.local/bin/workcenter` for `workcenter`.

An Intel Mac is best effort, and needs a Homebrew already installed.
On macOS 12 to 14 the script runs on a Homebrew that does not support them: Homebrew's install.sh
names macOS 15 its oldest. With no bottles there, Homebrew builds Python and ngspice from source,
which is slow and may fail.
The script stops in an x86_64 shell on Apple Silicon (Rosetta) and on macOS older than 12.

## Route N: Windows, native

The installer is `install.ps1`. It installs for your own user, with no administrator of its own.
Java 21, ngspice, FreeRouting and Via's venv go under `%LOCALAPPDATA%\Via`, and the `workcenter`
command into `%LOCALAPPDATA%\Via\bin`, which it adds to your user's PATH.
KiCad 10 and Python 3.12 come from winget, for your user, under `%LOCALAPPDATA%\Programs`, at the
pinned version, checked by winget's manifest. Without winget, they come from their own installers,
checked against Via's pinned SHA256. Java, ngspice, 7-Zip (it unpacks ngspice) and FreeRouting are
checked against Via's pinned SHA256.
KiCad is about 1 GB: ask the person before step 4.
KiCad's installer may ask Windows for an administrator once, for Microsoft's Visual C++ runtime.
When the person has another KiCad (8 or 9), KiCad 10 goes beside it in a folder of its own, and the
other is kept. Tell the person before step 4, and go on only with their yes.

Run every command in PowerShell, not in cmd.exe.

1. Check Git.
   - Run: `git --version`
   - Check: it prints `git version`.
   - Fail: Git is absent. Ask the person before `winget install --id Git.Git -e --source winget`
     (the command git-scm.com gives). Git's installer asks Windows for an administrator (its winget
     manifest says `ElevationRequirement: elevatesSelf`): tell the person that too.
     Your shell keeps the PATH it started with. Run the check again as
     `$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User'); git --version`,
     and start step 2's command with the same first part.
2. Get Via.
   - Run: `git clone https://github.com/reagent-systems/via "$HOME\via"`
   - Check: `Test-Path "$HOME\via\install.ps1"` prints `True`.
3. Show the person the plan.
   - Run: `Set-Location "$HOME\via"; powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1 -DryRun`
   - Check: it prints each step as a `would:` line and each question as a `would ask:` line, and its
     last line is `dry run: nothing was installed, downloaded or written.`
   - Show the person every `would ask:` line.
4. Install. Ask the person first: it downloads about 1 GB, and KiCad's installer may show a
   Windows prompt for an administrator.
   - From an agent's shell, nobody can answer the script's questions. Without `-Yes` it stops with
     exit 4 at its first one, with "Nobody can answer here." Do not run it again as it was.
   - When the person said yes to every `would ask:` line from step 3, run:
     `Set-Location "$HOME\via"; powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1 -Yes`
   - Check: the last lines are the doctor's. The first of them starts with `workcenter ee:`.
   - Fail: the script says an installer asked for a restart (exit 3). Tell the person; after the
     restart, run the step again. When it says Microsoft's Visual C++ runtime is probably missing,
     show the person: installing that runtime needs an administrator. Any other failure: show it to
     the person, and run the step again once.
5. Find `workcenter`.
   - The script added `%LOCALAPPDATA%\Via\bin` to your user's PATH, for new terminals.
     Your shell keeps the PATH it started with, so run every `workcenter` command by its full path.
   - Run: `& "$env:LOCALAPPDATA\Via\bin\workcenter.cmd" doctor`
   - Check: its first line starts with `workcenter ee:`.
   - Fail: the path is not found. Step 4 did not finish: show the person its last 20 lines.
   - Tell the person: a new PowerShell of theirs finds `workcenter` by name.
6. Go to "Done when". Run its commands in `$HOME\via`, with
   `& "$env:LOCALAPPDATA\Via\bin\workcenter.cmd"` for `workcenter`.

## Route W: Windows, through WSL2

WSL2 runs Ubuntu 24.04 inside Windows. Via then installs with route L, unchanged.
It needs Windows 10 version 2004 (build 19041) or later, or Windows 11.

Run these commands in PowerShell. `$env:WSL_UTF8=1` makes `wsl` print UTF-8; without it, its output
in an agent's shell is UTF-16, and `Ubuntu-24.04` reads as spaced-out letters.

1. Check for WSL and Ubuntu 24.04.
   - Run: `$env:WSL_UTF8=1; wsl -l -v`
   - Check: a line names `Ubuntu-24.04` with VERSION `2`. Then go to step 3.
   - Fail: no such line, or `wsl` is not found. Go to step 2.
2. Install WSL and Ubuntu 24.04, restart, and make a Linux user. This needs an administrator and a restart.
   - Tell the person both, and wait for a yes.
   - Ask the person to run in a PowerShell opened with "Run as administrator":
     `wsl --install -d Ubuntu-24.04`
   - Then ask the person to restart, open "Ubuntu 24.04" from the Start menu, and make a Linux user.
     The Linux password is the person's. Never ask for it.
   - Check: `$env:WSL_UTF8=1; wsl -l -v` names `Ubuntu-24.04` with VERSION `2`, and
     `wsl -d Ubuntu-24.04 -- whoami` prints the person's Linux user, not `root`.
   - Fail: the install command printed WSL's help text. WSL is there already; ask the person to run
     `wsl --install -d Ubuntu-24.04` again after `wsl --list --online` names `Ubuntu-24.04`.
     When the list does not name it, show the list to the person and stop.
3. Run route L inside Ubuntu.
   - Run each command as: `wsl -d Ubuntu-24.04 -- bash -lc '<command>'`
   - Check: each of route L's checks, run the same way.
   - Keep Via and the boards in the Linux home folder (`~/via`), not under `/mnt/c`.
   - Route L's step 3 needs sudo: ask the person to open "Ubuntu 24.04" and run
     `cd ~/via && sudo ./install.sh` there.
4. Go to "Done when". Run each of its commands as `wsl -d Ubuntu-24.04 -- bash -lc 'cd ~/via && <command>'`.

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

## What macOS and Windows do not run

Routes M and N run the gates, `design`, `next` and the autoroute. Some tools stay on Linux and in
Docker, and say so where they stop:

- openEMS (`workcenter fields`), the chip flow, and renders through Xvfb.
- `workcenter placement`, `inspect`, `copper`, the assembly pictures and the legend's ink rule: they
  need pcbnew in Via's own Python, and KiCad's pcbnew loads only in KiCad's Python there. They say
  SKIPPED or not judged. `design --route` stitches pours in KiCad's own Python, so it works there.
- ngspice is 47 on macOS and Windows, and 42 on Ubuntu 24.04.

Tell the person when their board needs one of these: route W or route D runs it.

## Done when

All 3 hold, each run in the clone of Via. Route M writes `~/.local/bin/workcenter` for `workcenter`;
route N writes `& "$env:LOCALAPPDATA\Via\bin\workcenter.cmd"`; route W runs each through `wsl`;
route D runs the container's form. Your shell keeps the PATH it started with; a new terminal of the
person's finds `workcenter` by name.

1. `workcenter doctor` exits 0, and its first line is `workcenter ee: ok`, or `degraded` with only the rows the table below allows for this route.
2. `workcenter gates tests/boards/pass-first-design` exits 0, and its last line starts with `GREEN: divider`.
3. `workcenter gates tests/boards/fail-drc-clearance` exits 1, and its last line starts with `RED: rc_divider`.
   This board breaks a clearance on purpose. GREEN here means the install is wrong.

Check 3 proves the gates can say RED. An install that says GREEN to everything is not done.

The doctor says `degraded` for a tool a route does not install. These rows may be absent, and only
on these routes; report them to the person, and the install is done:

| Route | Rows that may be absent |
|---|---|
| M, N | `openems`, `rsvg-convert`, `ffmpeg`: neither installer installs them, and openEMS runs on Linux and in Docker only. Off Linux the Xvfb row says n/a, which is not degraded. |
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
| `workcenter` is not found | Your shell keeps the PATH it started with. Run it by its full path: `~/.local/bin/workcenter` on M, `& "$env:LOCALAPPDATA\Via\bin\workcenter.cmd"` on N. A new terminal of the person's finds it by name. |

## Report to the person

- the platform and the route, with its state from the table above
- each step, and its check
- the doctor's first line, and every row that is not `ok`
- the last line of each gate run, with its exit code

A route not proven on GitHub's runners (D on macOS or Windows, M on an Intel Mac) has no green
run. Tell the person that a report of this run in an issue at
https://github.com/reagent-systems/via/issues helps the next person.

## Next

In a POSIX shell, `workcenter new ~/my-board` starts a board in a folder of its own, and
`workcenter next ~/my-board` names the one next step, until the board is GREEN.
In PowerShell, write the folder as `"$HOME\my-board"`: `workcenter new "$HOME\my-board"`, then
`workcenter next "$HOME\my-board"`. Windows PowerShell passes a `~` to a command as it is.
