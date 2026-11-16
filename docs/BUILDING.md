# Building and publishing

## Source development

Python >= 3.11 is supported for source usage. Use **Python 3.12 on Ubuntu 22.04**
for the published binary baseline (glibc 2.35). Do not upload an Arch-built archive
as a universal Linux binary: build-time native dependencies can require newer glibc.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r packaging/requirements-build.txt
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python -m pip install 'ruff>=0.12'
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check steamlaunch tests scripts packaging
PYTHON=.venv/bin/python ./scripts/build_release.sh
PYTHON=.venv/bin/python ./scripts/check_release.sh dist/SteamLaunch-0.2.0-linux-x86_64-local.tar.gz
```

Scripts never delete previous build directories. Results are in `dist/`; build
workspaces have unique IDs under `build/`. `--label release` is for the controlled
CI build environment only. The recipe pins direct/transitive freezer dependencies;
the host package mirror and compression timestamps still mean this is **not a
claim of byte-for-byte reproducibility**.
Building requires internet access to retrieve checksummed license texts. Builds
also retain CPython's license and available host package copyright notices and
write a native-library hash inventory. Optional Qt VirtualKeyboard/PDF plugins
are excluded; this application does not require these modules.

## Runtime design

- PyInstaller onedir, not a onefile extraction. Single executable has GUI/doctor/
  install/uninstall/wrap modes. `wrap` does not import the GUI.
- Qt XCB and Wayland platform/integration plugins are explicitly included.
- Before starting Steam/Proton, undo the freezer's `LD_LIBRARY_PATH` modification
  using `LD_LIBRARY_PATH_ORIG`, and restore the Qt plugin environment captured by
  the user runtime hook. Never strip `LD_PRELOAD` from the game: it carries Overlay.
- Installed versions are immutable directories. An atomically switched `current`
  symlink and a stable launcher keep saved Steam options valid after updates.
- Source mode retains its venv-based command. Existing profiles are not converted
  silently; explicit re-binding preserves the original restoration record.

## System libraries and backend tests

On Debian/Ubuntu the X11 plugin commonly needs `libxcb-cursor0`, `libxkbcommon-x11-0`,
`libxcb-icccm4`, `libxcb-keysyms1`, `libxcb-image0`, `libxcb-render-util0`,
`libx11-xcb1`, and normal OpenGL/EGL libraries (`libgl1`, `libegl1`). Native Wayland
needs libwayland-client, libxkbcommon, EGL and a working compositor/graphics stack.
These are normally present on a desktop distribution. This archive is not a
container or a replacement for system display/graphics drivers.

The archive smoke checker isolates HOME/XDG directories, tests the extracted
binary's GUI, install/update/uninstall, and executes a fake Proton command to
verify argv, cwd, PID, exit status and library-environment restoration. It does
not launch Steam or a game. Run `--platform xcb` under Xvfb/X11 and
`--platform wayland` under a Wayland compositor. CI uses Xvfb and headless Weston.
Offscreen success alone is **not** a test of X11 or Wayland.

## Release checklist

1. Update `steamlaunch.__version__` and CHANGELOG; test source and the binary archive.
2. Inspect `bundle.json`, `dependencies.json`, included `licenses/`, native library
   inventory (`find ... -name '*.so*'`, `ldd`) and upstream license/source obligations.
3. Test on clean supported desktops and manually check a real Steam game/Overlay.
   Do not advertise untested distributions or claim universal game compatibility.
4. The source archive is an explicit allowlist. Verify no personal paths, logs,
   VDFs, profiles, `.venv`, `.env`, PROGRESS.md or local build output are included.
5. Push a matching `v<version>` tag **when ready to publish**. The workflow builds,
   tests, attaches checksums/source/binaries and creates a **draft** GitHub release.
   Review it before publishing. No release is created by local installation.

The repository workflow requires no custom GitHub token; the tag release job uses
the repository-scoped GITHUB_TOKEN with contents:write. Pull-request CI has read
permissions and does not publish releases.
