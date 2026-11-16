# Contributing

Use a project virtualenv; never install build dependencies into system Python.
See [docs/BUILDING.md](docs/BUILDING.md) for tests and release builds.

Tests must use temporary Steam fixtures, not the developer's actual localconfig,
prefixes or running games. GUI tests use offscreen Qt. Changes affecting launch
arguments, environment or bindings need regression tests. Verify frozen binaries
as well as source mode; never persist a temporary freezer extraction path.

For bug reports include application version, distro/architecture, X11/Wayland,
Steam installation type, Proton version, steps and a **redacted** relevant log
excerpt. Do not upload full Steam configuration backups or account information.

Keep distribution limits and manual game/Overlay testing separate from unit-test
results. Do not add auto-installation of game dependencies or auto-killing Steam.
