### Fixed
- The desktop legs' tests step skipped every test that needs kicad-cli or ngspice on Windows (99 in run 46093588252) and kicad-cli's on macOS (44), though the same run's gates used both: the engine marks now ask `tools/hostos.py` where Via finds each, and the step puts each engine's folder at the end of the tests' `PATH`.
- On Windows `tools/workcenter` finds the ngspice install.ps1 unpacked under the root without `workcenter.cmd`'s `NGSPICE`: it is the first of `hostos.ngspice_candidates()`.
