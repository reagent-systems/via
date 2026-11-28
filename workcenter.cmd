@echo off
rem Via's command on Windows: runs tools\workcenter with the Python of the venv that install.ps1 made.
rem The root is WORKCENTER_ROOT, else %LOCALAPPDATA%\Via (tools/hostos.py default_root on Windows).
rem install.ps1 puts a 2-line workcenter.cmd on the user's PATH that hands over to this file.
rem It has no label to jump to: cmd.exe can miss one in a file with LF line endings.
setlocal
if not defined WORKCENTER_ROOT set "WORKCENTER_ROOT=%LOCALAPPDATA%\Via"
if not defined PYTHONUTF8 set "PYTHONUTF8=1"
rem ngspice's console program, where install.ps1 unpacks the official Windows build.
if not defined NGSPICE if exist "%WORKCENTER_ROOT%\ngspice\Spice64\bin\ngspice_con.exe" set "NGSPICE=%WORKCENTER_ROOT%\ngspice\Spice64\bin\ngspice_con.exe"
rem KiCad's command line, per-user install first (winget --scope user), then the machine install.
if not defined KICAD_CLI if exist "%LOCALAPPDATA%\Programs\KiCad\10.0\bin\kicad-cli.exe" set "KICAD_CLI=%LOCALAPPDATA%\Programs\KiCad\10.0\bin\kicad-cli.exe"
if not defined KICAD_CLI if exist "%ProgramFiles%\KiCad\10.0\bin\kicad-cli.exe" set "KICAD_CLI=%ProgramFiles%\KiCad\10.0\bin\kicad-cli.exe"
set "VIA_PY=%WORKCENTER_ROOT%\venv\Scripts\python.exe"
if not exist "%VIA_PY%" echo workcenter: no Python at "%VIA_PY%"; run install.ps1 first. 1>&2
if not exist "%VIA_PY%" exit /b 2
"%VIA_PY%" "%~dp0tools\workcenter" %*
exit /b %ERRORLEVEL%
