### Changed
- `make scope` answers `site` for a change whose every path is under `site/`; CI then runs only its `site` job (`make verify-www`), not `fast`, `full` or the desktop legs, and `verdict` asks `site` alone.
- The guide's first step links the Mac and Windows install pages, where it sent a Mac or a Windows PC to the cloud environment.
