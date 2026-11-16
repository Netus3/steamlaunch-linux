# Troubleshooting

## GUI

Try `SteamLaunch gui --display-backend x11` or `--display-backend wayland`.
Use `QT_DEBUG_PLUGINS=1` to diagnose Qt plugin dependencies. A missing XCB system
library is not fixed by changing a game's Proton version. Native Wayland and
Steam Overlay inside a game are independent.

## Game starts then exits

Read both the profile's wrapper/Proton log **and the game's own log**. A generic
“Unexpected application exit” or “video card requirements” dialog can hide a
missing DLL or shader compiler error. Do not install every Winetricks component
or recreate the prefix without evidence.

- A `c0000135` import failure identifies a missing DLL/dependency chain.
- `builtin`/`native` in a Proton loaddll trace identifies the actual implementation
  used, not just whether a component was installed.
- Some older games need original D3DX/compiler DLLs. Install only the identified
  component using Protontricks for the **selected Steam AppID**, not `~/.wine`.
- A mod's working directory may be its root, not its `bin` directory.
- `wrong ELF class ... ignored` overlay preload warnings alone do not prove the
  cause of a game failure. Do not remove all LD_PRELOAD entries to hide them.
- Back up saves/prefixes before changing Proton versions or dependencies.

## Restore if the application cannot start

The state directory's `bindings.json` records the original string in `previous`.
`null` means the original LaunchOptions field was absent (clear it in Steam).
Restore the string manually through Steam's game properties. Do not restore an
entire old localconfig.vdf over newer unrelated settings. Once Steam is closed,
the application's Restore button can clear a record already restored manually.

Keep restoration records until every binding is removed. Never post complete VDF
backups, credentials, or private profile/log content to a public issue.
