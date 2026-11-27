#Requires -Version 5.1
<#
.SYNOPSIS
Installs Via on Windows 10 or 11 (x64) for the user who runs it, with no administrator of its own.

.DESCRIPTION
Every version, address and SHA256 comes from toolchain\desktop.json, section "windows".
Steps, in order; each is kept when a run before this one finished it:
  1. KiCad 10.0 (an existing KiCad 10 is kept), else winget --scope user at the pinned version.
  2. Python 3.12, else winget --scope user at the pinned version.
  3. Java 21: the Temurin JRE zip under the root (winget's Temurin packages install for all users).
  4. ngspice: the official Windows build (console program ngspice_con.exe), unpacked with 7zr.exe.
  5. FreeRouting: the same jar install.sh installs on Linux.
  6. A venv under the root with requirements.txt.
  7. workcenter.cmd on this user's PATH.
  8. workcenter doctor.
Without winget, KiCad's and Python's own installers are downloaded and checked by their SHA256.
It asks before KiCad's and Python's installers. KiCad's may ask Windows for an administrator once,
for Microsoft's Visual C++ runtime. It never restarts the computer: when an installer asks for a
restart, it stops and says so; run it again after the restart.

.PARAMETER Root
Where Via keeps its tools. Default: %LOCALAPPDATA%\Via (tools/hostos.py default_root).

.PARAMETER Downloads
Where downloads are kept and used again. Default: <Root>\downloads.

.PARAMETER Yes
Answers yes to each question. For CI and for a coding agent the person has said yes to.

.PARAMETER DryRun
Prints every step and runs none: nothing is installed, downloaded or written. -WhatIf does the same.

.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1 -DryRun
.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$Root = '',
    [string]$Downloads = '',
    [switch]$Yes,
    [switch]$DryRun
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'
# Windows PowerShell 5.1's progress bar makes Invoke-WebRequest many times slower.
$ProgressPreference = 'SilentlyContinue'
# Windows PowerShell 5.1 on .NET Framework may not offer TLS 1.2 unless it is named.
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$script:DryRun = [bool]$DryRun -or [bool]$WhatIfPreference
$script:Python = ''
$script:Shim = ''

# --- Printing and asking

function Write-Step {
    param([string]$Text)
    if ($script:DryRun) { Write-Host "would: $Text" } else { Write-Host "step: $Text" }
}

function Write-Note {
    param([string]$Text)
    Write-Host "  $Text"
}

function Stop-Install {
    param([string]$Text, [int]$Code = 1)
    Write-Host "install.ps1: $Text" -ForegroundColor Red
    exit $Code
}

function Confirm-Step {
    param([string]$Question)
    if ($script:DryRun) {
        Write-Host "would ask: $Question"
        return $true
    }
    if ($Yes) {
        Write-Host "asked: $Question (yes, by -Yes)"
        return $true
    }
    if ([Console]::IsInputRedirected -or -not [Environment]::UserInteractive) {
        Stop-Install "$Question Nobody can answer here. Ask the person who runs this computer. Only if they say yes, run install.ps1 again with -Yes." 4
    }
    $answer = Read-Host "$Question [y/N]"
    return ($answer -match '^(y|yes)$')
}

# --- Reading the computer (also in a dry run)

function Get-ToolOutput {
    # Runs a program only to read what it prints (a version, a path); '' when it cannot run.
    param([string]$Exe, [string[]]$ArgList)
    $ErrorActionPreference = 'Continue'
    try {
        $out = & $Exe @ArgList 2>$null
        if ($LASTEXITCODE -ne 0) { return '' }
        return (($out | Out-String).Trim())
    } catch {
        return ''
    }
}

function Get-Series {
    # A version's first 2 numbers: KiCad's install folder and Python's series.
    param([string]$Version)
    return (($Version -split '\.')[0..1] -join '.')
}

function Test-Sha256 {
    param([string]$Path, [string]$Sha256)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    return ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -eq $Sha256)
}

function Test-Stamp {
    # A folder this script unpacked holds via-sha256.txt, the SHA256 of what it was unpacked from.
    param([string]$Folder, [string]$Sha256)
    $stamp = Join-Path $Folder 'via-sha256.txt'
    if (-not (Test-Path -LiteralPath $stamp -PathType Leaf)) { return $false }
    return (([IO.File]::ReadAllText($stamp)).Trim() -eq $Sha256)
}

function Test-Winget {
    return [bool](Get-Command 'winget' -ErrorAction SilentlyContinue)
}

function Test-Administrator {
    $me = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    return $me.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# --- The only functions that change the computer: each prints its step and returns in a dry run

function Invoke-Tool {
    param([string]$Text, [string]$Exe, [string[]]$ArgList)
    Write-Step "$Text`: $Exe $($ArgList -join ' ')"
    if ($script:DryRun) { return 0 }
    # The pipe makes PowerShell wait for a windowed installer, and keeps its output out of the result.
    & $Exe @ArgList | Out-Host
    return [int]$LASTEXITCODE
}

function Save-Download {
    param([string]$Url, [string]$Sha256, [string]$Path)
    if (Test-Sha256 $Path $Sha256) {
        Write-Note "kept $Path (its SHA256 is the pinned one)"
        return
    }
    Write-Step "download $Url to $Path, then check its SHA256"
    if ($script:DryRun) { return }
    $part = "$Path.part"
    # SourceForge sends PowerShell's own user agent a web page instead of the file; a plain one gets the file.
    Invoke-WebRequest -Uri $Url -OutFile $part -UseBasicParsing -UserAgent 'via-install'
    $got = (Get-FileHash -LiteralPath $part -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($got -ne $Sha256) {
        Remove-Item -LiteralPath $part -Force
        Stop-Install "$Url gave SHA256 $got; toolchain\desktop.json pins $Sha256. Nothing was installed from it."
    }
    Move-Item -LiteralPath $part -Destination $Path -Force
}

function Expand-Zip {
    param([string]$Zip, [string]$Dest)
    Write-Step "unpack $Zip into $Dest"
    if ($script:DryRun) { return }
    if (Test-Path -LiteralPath $Dest) { Remove-Item -LiteralPath $Dest -Recurse -Force }
    Expand-Archive -LiteralPath $Zip -DestinationPath $Dest -Force
}

function Clear-Folder {
    # Empties a folder before an archive is unpacked into it, so nothing of an older pin stays.
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    Write-Step "remove folder $Path"
    if ($script:DryRun) { return }
    Remove-Item -LiteralPath $Path -Recurse -Force
}

function New-Folder {
    param([string]$Path)
    if (Test-Path -LiteralPath $Path -PathType Container) { return }
    Write-Step "make folder $Path"
    if ($script:DryRun) { return }
    New-Item -ItemType Directory -Path $Path -Force | Out-Null
}

function Copy-File {
    param([string]$From, [string]$To)
    Write-Step "copy $From to $To"
    if ($script:DryRun) { return }
    Copy-Item -LiteralPath $From -Destination $To -Force
}

function Write-TextFile {
    # UTF-8 without a byte order mark: Windows PowerShell 5.1's Set-Content would write one.
    param([string]$Path, [string]$Text)
    Write-Step "write $Path"
    if ($script:DryRun) { return }
    [IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding($false)))
}

function Add-UserPath {
    param([string]$Folder)
    # Read raw, so that a %VARIABLE% in the user's PATH stays a variable.
    $key = Get-Item -LiteralPath 'HKCU:\Environment'
    $raw = [string]$key.GetValue('Path', '', 'DoNotExpandEnvironmentNames')
    $parts = @($raw -split ';' | Where-Object { $_ -ne '' })
    if ($parts -notcontains $Folder) {
        Write-Step "add $Folder to this user's PATH"
        if ($script:DryRun) { return }
        $value = (@($parts) + $Folder) -join ';'
        if ($raw.Contains('%')) {
            # Kept as an expandable string. Set-ItemProperty tells nobody, so setting and clearing a
            # throwaway user variable through .NET sends Windows' WM_SETTINGCHANGE: a new terminal sees it.
            Set-ItemProperty -LiteralPath 'HKCU:\Environment' -Name 'Path' -Value $value -Type ExpandString
            [Environment]::SetEnvironmentVariable('VIA_PATH_NOTICE', '1', 'User')
            [Environment]::SetEnvironmentVariable('VIA_PATH_NOTICE', $null, 'User')
        } else {
            # Also tells Windows the PATH changed, so a new terminal sees it.
            [Environment]::SetEnvironmentVariable('Path', $value, 'User')
        }
    } else {
        Write-Note "PATH: this user's PATH holds $Folder"
    }
    if (($env:Path -split ';') -notcontains $Folder) { $env:Path = "$env:Path;$Folder" }
}

# --- Fetching a pinned file

function Get-Pinned {
    # The pinned file in the downloads folder, downloaded and checked when it is not there yet.
    param($pin)
    $name = [IO.Path]::GetFileName(([Uri]$pin.url).LocalPath)
    $path = Join-Path $script:Downloads $name
    Save-Download $pin.url $pin.sha256 $path
    return $path
}

function Assert-NoRestart {
    # winget's return codes (winget-cli doc/windows/package-manager/winget/returnCodes.md) and the
    # Windows Installer's 3010: the installer wants Windows restarted.
    param([int]$Code, [string]$What)
    if ($Code -eq -1978334967 -or $Code -eq -1978334965 -or $Code -eq 3010) {
        Stop-Install "$What asks Windows to restart to finish. Restart when you choose, then run install.ps1 again: it keeps what is done." 3
    }
    if ($Code -eq -1978334966) {
        Stop-Install "$What cannot install until Windows restarts. Restart when you choose, then run install.ps1 again." 3
    }
}

function Assert-Installed {
    # 0, "already installed" and "no newer version" are a finished install.
    param([int]$Code, [string]$What)
    Assert-NoRestart $Code $What
    if ($Code -notin @(0, -1978335135, -1978335189)) {
        Stop-Install "$What did not install (exit $Code)."
    }
}

# --- The steps

function Find-KiCadCli {
    $series = Get-Series $Pins.kicad.version
    $major = ($series -split '\.')[0]
    $candidates = @()
    if ($env:KICAD_CLI) { $candidates += $env:KICAD_CLI }
    $candidates += 'kicad-cli'
    $candidates += (Join-Path $env:LOCALAPPDATA "Programs\KiCad\$series\bin\kicad-cli.exe")
    if ($env:ProgramFiles) { $candidates += (Join-Path $env:ProgramFiles "KiCad\$series\bin\kicad-cli.exe") }
    foreach ($exe in $candidates) {
        $seen = Get-ToolOutput $exe @('version')
        if ($seen -match "^$major\.") {
            return @{ Exe = $exe; Version = ($seen -split "`r?`n")[0] }
        }
    }
    return $null
}

function Install-KiCad {
    $found = Find-KiCadCli
    if ($found) {
        Write-Note "KiCad: kept $($found.Exe) ($($found.Version))"
        return
    }
    $ask = "Install KiCad $($Pins.kicad.version) for this user (about 1 GB)? Its installer may ask Windows for an administrator once, for Microsoft's Visual C++ runtime."
    if (-not (Confirm-Step $ask)) { Stop-Install 'Via needs KiCad 10; nothing was installed.' }
    if (Test-Winget) {
        $code = Invoke-Tool "KiCad $($Pins.kicad.version)" 'winget' @(
            'install', '--exact', '--id', $Pins.kicad.winget_id, '--version', $Pins.kicad.version,
            '--source', 'winget', '--scope', 'user', '--silent', '--accept-package-agreements', '--accept-source-agreements')
    } else {
        Write-Note 'winget: not on this computer; KiCad comes from its own installer, checked by its SHA256'
        $exe = Get-Pinned $Pins.kicad
        $code = Invoke-Tool "KiCad $($Pins.kicad.version)" $exe ($Pins.kicad.user_switches -split ' ')
    }
    Assert-Installed $code 'KiCad'
    if ($script:DryRun) { return }
    $found = Find-KiCadCli
    $userCli = Join-Path $env:LOCALAPPDATA "Programs\KiCad\$(Get-Series $Pins.kicad.version)\bin\kicad-cli.exe"
    if (-not $found -and (Test-Path -LiteralPath $userCli -PathType Leaf)) {
        Stop-Install ("KiCad installed, but $userCli does not answer. Microsoft's Visual C++ runtime is probably missing: " +
            "KiCad's installer asks Windows for an administrator to add it, and goes on without it when nobody says yes. " +
            "Install the Visual C++ v14 Redistributable (x64) from learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist " +
            "(this needs an administrator), then run install.ps1 again.")
    }
    if (-not $found) {
        Stop-Install "KiCad installed, but no kicad-cli of KiCad $($Pins.kicad.version) answers. Set KICAD_CLI to its kicad-cli.exe and run install.ps1 again."
    }
    Write-Note "KiCad: $($found.Exe) ($($found.Version))"
}

function Find-Python {
    $series = Get-Series $Pins.python.version
    $candidates = @()
    $candidates += (Join-Path $env:LOCALAPPDATA ('Programs\Python\Python' + ($series -replace '\.', '') + '\python.exe'))
    $launched = Get-ToolOutput 'py' @("-$series", '-c', 'import sys; print(sys.executable)')
    if ($launched) { $candidates += $launched }
    $candidates += 'python'
    foreach ($exe in $candidates) {
        $seen = Get-ToolOutput $exe @('-c', 'import sys; print(*sys.version_info[:2], sep=chr(46))')
        if ($seen -eq $series) {
            $where = Get-ToolOutput $exe @('-c', 'import sys; print(sys.executable)')
            if ($where) { return $where }
        }
    }
    return ''
}

function Install-Python {
    $series = Get-Series $Pins.python.version
    $script:Python = Find-Python
    if ($script:Python) {
        Write-Note "Python $series`: kept $script:Python"
        return
    }
    # The switches say InstallLauncherAllUsers=0: Python's installer otherwise puts its py launcher in
    # for all users (an administrator). winget's own switches do not say it, so --override replaces them.
    $ask = "Install Python $($Pins.python.version) for this user (no administrator; your PATH is not changed)?"
    if (-not (Confirm-Step $ask)) { Stop-Install "Via's venv needs Python $series; nothing was installed." }
    if (Test-Winget) {
        $code = Invoke-Tool "Python $($Pins.python.version)" 'winget' @(
            'install', '--exact', '--id', $Pins.python.winget_id, '--version', $Pins.python.version,
            '--source', 'winget', '--scope', 'user', '--silent', '--override', $Pins.python.user_switches,
            '--accept-package-agreements', '--accept-source-agreements')
    } else {
        Write-Note 'winget: not on this computer; Python comes from its own installer, checked by its SHA256'
        $exe = Get-Pinned $Pins.python
        $code = Invoke-Tool "Python $($Pins.python.version)" $exe ($Pins.python.user_switches -split ' ')
    }
    Assert-Installed $code 'Python'
    if ($script:DryRun) {
        $script:Python = "<the Python $series just installed>"
        return
    }
    $script:Python = Find-Python
    if (-not $script:Python) { Stop-Install "Python installed, but no Python $series answers. Run install.ps1 again in a new terminal." }
    Write-Note "Python $series`: $script:Python"
}

function Install-Java {
    # FreeRouting needs Java 21 with its window library (bin\awt.dll is in the JRE zip).
    $dest = Join-Path $Root 'java21'
    $java = Join-Path $dest ($Pins.java.folder + '\bin\java.exe')
    if (Test-Stamp $dest $Pins.java.sha256) {
        Write-Note "Java $($Pins.java.version): kept $java"
    } else {
        $zip = Get-Pinned $Pins.java
        Expand-Zip $zip $dest
        Write-TextFile (Join-Path $dest 'via-sha256.txt') $Pins.java.sha256
    }
    # tools/routers.py runs the java this file names, whatever java stands first on PATH.
    Write-TextFile (Join-Path $Root 'java.path') "$java`n"
}

function Install-Ngspice {
    $dest = Join-Path $Root 'ngspice'
    $exe = Join-Path $dest ($Pins.ngspice.exe -replace '/', '\')
    if (Test-Stamp $dest $Pins.ngspice.sha256) {
        Write-Note "ngspice $($Pins.ngspice.version): kept $exe"
        return
    }
    $sevenzr = Get-Pinned $Pins.sevenzip
    $archive = Get-Pinned $Pins.ngspice
    Clear-Folder $dest
    New-Folder $dest
    $code = Invoke-Tool "unpack ngspice $($Pins.ngspice.version) with 7-Zip $($Pins.sevenzip.version)" $sevenzr @('x', '-y', "-o$dest", $archive)
    if ($code -ne 0) { Stop-Install "7-Zip could not unpack $archive (exit $code)." }
    if (-not $script:DryRun -and -not (Test-Path -LiteralPath $exe -PathType Leaf)) {
        Stop-Install "$archive holds no $($Pins.ngspice.exe)."
    }
    Write-TextFile (Join-Path $dest 'via-sha256.txt') $Pins.ngspice.sha256
}

function Install-FreeRouting {
    $dest = Join-Path $Root 'freerouting'
    $jar = Join-Path $dest 'freerouting.jar'
    if (Test-Sha256 $jar $Pins.freerouting.sha256) {
        Write-Note "FreeRouting $($Pins.freerouting.version): kept $jar"
        return
    }
    $file = Get-Pinned $Pins.freerouting
    New-Folder $dest
    Copy-File $file $jar
}

function Install-Venv {
    $series = Get-Series $Pins.python.version
    $venv = Join-Path $Root 'venv'
    $py = Join-Path $Root 'venv\Scripts\python.exe'
    $cfg = Join-Path $venv 'pyvenv.cfg'
    $kept = $false
    if ((Test-Path -LiteralPath $py) -and (Test-Path -LiteralPath $cfg)) {
        $line = Select-String -LiteralPath $cfg -Pattern '^version\s*=\s*(\S+)' | Select-Object -First 1
        if ($line -and $line.Matches[0].Groups[1].Value.StartsWith("$series.")) { $kept = $true }
    }
    if ($kept) {
        Write-Note "venv: kept $venv (Python $series)"
    } else {
        $code = Invoke-Tool "venv at $venv" $script:Python @('-m', 'venv', '--clear', $venv)
        if ($code -ne 0) { Stop-Install "Python could not make the venv at $venv (exit $code)." }
    }
    $requirements = Join-Path $PSScriptRoot 'requirements.txt'
    $code = Invoke-Tool 'requirements.txt into the venv' $py @(
        '-m', 'pip', 'install', '--disable-pip-version-check', '-r', $requirements)
    if ($code -ne 0) { Stop-Install "pip could not install $requirements (exit $code)." }
}

function Add-Shim {
    # A 4-line workcenter.cmd in <Root>\bin hands over to the checkout's workcenter.cmd. setlocal keeps
    # WORKCENTER_ROOT out of the cmd.exe window it is typed in.
    $bin = Join-Path $Root 'bin'
    $shim = Join-Path $bin 'workcenter.cmd'
    $target = Join-Path $PSScriptRoot 'workcenter.cmd'
    New-Folder $bin
    $text = "@echo off`r`nsetlocal`r`nif not defined WORKCENTER_ROOT set `"WORKCENTER_ROOT=$Root`"`r`n`"$target`" %*`r`n"
    Write-TextFile $shim $text
    Add-UserPath $bin
    $script:Shim = $shim
}

function Invoke-Doctor {
    $code = Invoke-Tool 'workcenter doctor' $script:Shim @('doctor')
    if ($code -ne 0) { Stop-Install "workcenter doctor exited $code; its rows above say what is missing." $code }
}

# --- Main

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    Stop-Install 'This installer is for Windows. On Linux run install.sh; on macOS, install-macos.sh.'
}
if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') {
    Stop-Install 'Windows on Arm: the ngspice build Via pins is x64 only. Use WSL2 with install.sh.'
}
$Pins = (Get-Content -LiteralPath (Join-Path $PSScriptRoot 'toolchain\desktop.json') -Raw | ConvertFrom-Json).windows
if (-not $Root) { $Root = Join-Path $env:LOCALAPPDATA 'Via' }
if (-not $Downloads) { $Downloads = Join-Path $Root 'downloads' }
$script:Downloads = $Downloads
if ($script:DryRun) { Write-Host 'dry run: every step is printed and none runs.' }
Write-Host "Via's root: $Root"
if (Test-Administrator) {
    $ask = 'This PowerShell runs as an administrator, but Via installs for one user: the account that runs it. Go on?'
    if (-not (Confirm-Step $ask)) { Stop-Install 'Stopped: run install.ps1 again from a PowerShell that is not elevated.' }
}
New-Folder $Root
New-Folder $Downloads

Install-KiCad
Install-Python
Install-Java
Install-Ngspice
Install-FreeRouting
Install-Venv
Add-Shim
Invoke-Doctor

if ($script:DryRun) {
    Write-Host 'dry run: nothing was installed, downloaded or written.'
} else {
    Write-Host "Via is installed. Open a new terminal; 'workcenter doctor' runs there."
    Write-Host "If that terminal does not know 'workcenter', run it by its full path: $script:Shim"
}
