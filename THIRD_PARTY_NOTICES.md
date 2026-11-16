# Third-party software

SteamLaunch's original Python code and SVG icon are MIT licensed. The MIT license
does not relicense bundled dependencies. The project is independent of Valve.

The binary archive is a PyInstaller **onedir**, dynamically linked distribution:
libraries are under `_internal/` and can be replaced with compatible builds.
Do not prohibit reverse engineering for debugging modifications to LGPL libraries.
No Steam, Proton, Windows runtimes or game DLLs are included.

## Qt / Qt for Python / Shiboken

- Qt for Python (PySide6-Essentials, Shiboken6), release recipe: **6.12.0**.
- Qt libraries and plugins included by the Qt for Python wheels; exact Qt version
  and licenses are recorded in the wheel's files. LGPLv3/GPL/commercial and
  component-specific terms apply; the release uses the applicable open-source terms.
- Upstream source and license notices: https://code.qt.io/cgit/pyside/pyside-setup.git/
  (tag matching PySide release), https://download.qt.io/official_releases/QtForPython/,
  https://download.qt.io/official_releases/qt/ and https://www.qt.io/licensing/.
- The build script copies license files supplied by the actual installed wheels
  into `licenses/` where available; some wheels contain none. The LGPLv3/GPLv3
  license texts and a Qt copyright notice are explicitly included as well.
  `dependencies.json` identifies the packaged Python distributions.

## CPython

Bundled interpreter and standard library: Python Software Foundation license and
additional notices in the matching CPython source's `LICENSE`:
https://www.python.org/downloads/source/ and https://github.com/python/cpython.
The interpreter version is recorded in `bundle.json`. Release CI uses Python 3.12.

## PyInstaller

PyInstaller bootloader: GPL with the PyInstaller bootloader exception, allowing
distribution of applications under their own license.
https://pyinstaller.org/en/stable/license.html
https://github.com/pyinstaller/pyinstaller
The pinned version is in `packaging/requirements-build.txt` and `dependencies.json`.

## Other native libraries

PyInstaller can include additional shared libraries needed by Qt on the build
system (e.g. XCB, XKB, compression libraries). Their licenses remain applicable.
`native-libraries.json` records hashes and discovered package providers; available
system package notices are copied to `licenses/system/`. Optional Qt VirtualKeyboard
and PDF modules are excluded. The build guide documents inventory/audit steps; review the archive contents and
retain upstream notices/source availability before publishing a modified build.
Graphics drivers, glibc and the running window server are provided by the host OS.
