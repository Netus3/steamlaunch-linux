#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ARCHIVE=${1:-}
if [ -z "$ARCHIVE" ]; then
    ARCHIVE=$(find "$ROOT/dist" -maxdepth 1 -name 'SteamLaunch-*-linux-*.tar.gz' -print -quit)
fi
if [ "$#" -gt 1 ]; then
    shift
    exec "${PYTHON:-python3}" "$ROOT/scripts/check_release.py" "$ARCHIVE" "$@"
fi
exec "${PYTHON:-python3}" "$ROOT/scripts/check_release.py" "$ARCHIVE"
