# SteamLaunch for Linux (vibecoded for my own use lol)

A small desktop application for launching a custom Windows executable **in the
Steam launch context of a game you own and have installed**. Keeps Steam's Proton
and Linux Runtime command chain; does not replace Steamworks DLLs or patch games.

[Русская инструкция](README.ru.md) · [Build/release guide](docs/BUILDING.md) ·
[Troubleshooting](docs/TROUBLESHOOTING.md) · [License](LICENSE)

## Download and start

Download the **Linux x86_64 `.tar.gz` binary archive** from this repository's
**Releases** page (not GitHub's automatic “Source code” download). Extract the
whole folder and open **`SteamLaunch`**. No system Python, pip, FUSE or root access
is required. If your file manager asks, allow executing the file.

For a permanent installation, use the application's **Install / update for current
user** button (currently labelled in Russian), or run in the extracted folder:

```sh
./install.sh
```

An application-menu entry and `~/.local/bin/steamlaunch` are created. You can then
delete the downloaded/extracted copy. Updates use the same procedure and retain
profiles, backup records and a stable launch path. Downloads are never installed
or updated automatically.

**Portable mode:** works without installation, but you must not move or delete
the extracted folder while Steam bindings refer to it. Use the installed version
for permanent bindings.

## Requirements and scope

- Linux **x86_64**, glibc. Release CI targets Ubuntu 22.04 / glibc 2.35 or newer.
  Locally built `-local` archives target the build machine and may need newer glibc.
- Native Steam package, a signed-in account, an owned/available installed game,
  installed Proton and working graphics drivers. **Flatpak Steam, musl/Alpine,
  ARM and macOS/Windows are not supported by this release.**
- GUI supports **X11 and native Wayland**, with XWayland fallback when available.
  Qt plugins are bundled; system display/graphics libraries must still be installed.
  See the [build guide](docs/BUILDING.md) for common XCB packages.
- The current GUI is in Russian. English documentation is provided here.

## Use

1. In the Steam game's **Properties → Compatibility**, force the Proton version
   you want, including for games that also have a native Linux build.
2. Enable Steam Overlay in Steam and the game's properties.
3. Create a profile in SteamLaunch: choose account/game, Windows `.exe`, arguments
   and working directory. Save it.
4. Completely exit Steam using **Steam → Exit**. Click **Bind to Steam** and
   confirm. The old launch options are saved; they are not combined with the new ones.
5. Start Steam, then use **Launch through Steam** or the game's Steam **Play** button.
6. To undo, completely exit Steam and click **Restore** in SteamLaunch.

Existing 0.1 profiles and restoration records are retained. After switching from
a source/portable install to the installed application, close Steam and click
**Bind to Steam** again from the installed GUI. This updates the launcher path
without forgetting the original launch options. **Do not delete the old source
folder until you have updated or restored its bindings.**

### Safety and limitations

- The selected game's **existing Proton prefix** is used. Another executable can
  modify saves, registry and dependencies. Back up important saves/prefixes first.
  Restoring launch options does **not** roll back prefix or save changes.
- Overlay, playtime and game compatibility depend on Steam/Proton/the executable;
  they are not guaranteed for every game. Achievements, Cloud and multiplayer do
  not appear automatically. Native Wayland GUI support is independent of Overlay.
- No DRM/anti-cheat bypass is implemented. Do not use modified builds in protected
  multiplayer. Steam, Proton, game files and DirectX DLLs are **not distributed**.
- The application edits only the selected `LaunchOptions` field, with backups,
  conflict checks and a crash-recovery journal. It never terminates Steam itself.
- Missing game dependencies must be installed separately, in the correct prefix.
- One automatically bound profile per Steam game/account; restore before switching
  the game/account associated with a bound profile.

## Data, diagnostics and removal

Profiles: `$XDG_CONFIG_HOME/steamlaunch` (default `~/.config/steamlaunch`).
Logs/backups: `$XDG_STATE_HOME/steamlaunch` (default `~/.local/state/steamlaunch`).
Installation: `$XDG_DATA_HOME/steamlaunch` (default `~/.local/share/steamlaunch`).

```sh
~/.local/bin/steamlaunch doctor
~/.local/bin/steamlaunch gui --display-backend x11
~/.local/bin/steamlaunch gui --display-backend wayland
```

Automatic backend selection respects `QT_QPA_PLATFORM` when explicitly set.
To remove the application, **restore all bindings first**, then run:

```sh
~/.local/bin/steamlaunch uninstall --yes
```

Profiles, logs and restoration backups are retained. Old installed versions are
retained during updates so a running process never loses its libraries; removal
cleans only the positively identified application installation.

Logs may contain paths/arguments; VDF backups may contain private Steam data.
**Do not attach complete backups or profiles to public issues.** No telemetry,
account credentials or Steam Web API key are required.

## From source / contributing

Current local validation: 75 automated tests; extracted binary GUI on Niri
Wayland and X11 via XWayland; isolated installation/update/removal and frozen
wrapper integration. The Ubuntu/Xvfb/headless-Weston CI recipe still needs its
first run after uploading the repository. Do not mistake the Arch-built local
archive for the cross-distribution CI release.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
./run.sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check steamlaunch tests scripts packaging
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [BUILDING.md](docs/BUILDING.md).
Source code is MIT; bundled third-party libraries retain their own licenses.
See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Not affiliated with Valve.
