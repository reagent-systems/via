### Fixed
- README's container commands named the tag v0.1.0, which no registry holds; they use main.
- Engine output (ngspice, kicad-cli) that holds a byte that is not UTF-8 is read with U+FFFD, where `run()` and the DRC report used to stop with UnicodeDecodeError (Linux too).
- A symlink in a sim run folder that dangles or names another folder's file is replaced by a link to the deck's own file; before, a dangling one stopped the run with FileExistsError and a resolving one was kept (Linux too).
