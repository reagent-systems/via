### Fixed
- The desktop legs' tests step skipped every test that needs kicad-cli or ngspice on Windows (99 in run 46093588252) and kicad-cli's on macOS (44), though the same run's gates used both: the engine marks now ask `tools/hostos.py` where Via finds each, and the step puts each engine's folder at the end of the tests' `PATH`.
- On Windows `tools/workcenter` finds the ngspice install.ps1 unpacked under the root without `workcenter.cmd`'s `NGSPICE`: it is the first of `hostos.ngspice_candidates()`.
- SIM kept a user's `.spiceinit` out of a deck by its own `HOME` alone, and ngspice also reads one from `USERPROFILE`, which Windows always sets, and from `SPICE_USERINIT_DIR`: on Windows a user's `%USERPROFILE%\.spiceinit` reached every deck the gate ran. The gate now replaces all three.
- EXPORT with a `KIKIT_PYTHON` that names no file said `engine missing: None` (Windows) or `engine missing: <path>` and judged nothing: now the panel alone is not judged, and the board's files are.
- `workcenter sim --bundle` prints the ngspice the gate ran in its `bundle <deck>:` line, so on Windows the line starts a program the shell finds (install.ps1 puts none on `PATH`).
