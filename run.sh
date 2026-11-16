#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ ! -x "$ROOT/.venv/bin/python" ]; then
    echo "Создай окружение: python -m venv \"$ROOT/.venv\"" >&2
    exit 1
fi
exec "$ROOT/.venv/bin/python" -I -m steamlaunch "$@"
