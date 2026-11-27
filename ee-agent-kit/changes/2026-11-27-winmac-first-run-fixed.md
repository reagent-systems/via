### Fixed
- On Windows, the lines `next`, `new`, the gates and the engine lock print quote a path in double quotes where it needs them, as cmd.exe and PowerShell read them, not in sh's single quotes.
- `design --check` no longer fails a board whose footprint library is on another drive than the temporary folder (Windows).
- A console or pipe that is not UTF-8 gets `?` for a character it lacks, where `workcenter` used to stop with UnicodeEncodeError.
