#!/usr/bin/env bash
# Зависимости только этого проекта. Не устанавливает службы и не запускает приложение.
set -euo pipefail
PGWEB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PGWEB_ROOT"

if command -v python3 >/dev/null 2>&1; then
  PGWEB_SYSTEM_PYTHON=python3
else
  PGWEB_SYSTEM_PYTHON=python
fi
"$PGWEB_SYSTEM_PYTHON" -c 'import sys; assert sys.version_info >= (3,12), "Нужен Python 3.12 или новее"'
node -e 'if (Number(process.versions.node.split(".")[0]) < 22) throw new Error("Нужен Node.js 22 или новее")'

if [[ ! -d backend/.venv ]]; then
  "$PGWEB_SYSTEM_PYTHON" -m venv backend/.venv
fi
PGWEB_PYTHON="$PGWEB_ROOT/backend/.venv/bin/python"
[[ -x "$PGWEB_ROOT/backend/.venv/Scripts/python.exe" ]] && PGWEB_PYTHON="$PGWEB_ROOT/backend/.venv/Scripts/python.exe"
[[ -x "$PGWEB_PYTHON" ]] || { echo 'В backend/.venv нет Python для этой ОС.' >&2; exit 1; }
if ! "$PGWEB_PYTHON" -m pip --version >/dev/null 2>&1; then
  "$PGWEB_PYTHON" -m ensurepip --upgrade
fi
mkdir -p "$PGWEB_ROOT/.localdata/pip-cache" "$PGWEB_ROOT/.localdata/npm-cache"
"$PGWEB_PYTHON" -m pip install --cache-dir "$PGWEB_ROOT/.localdata/pip-cache" --require-hashes -r backend/requirements-dev.lock
"$PGWEB_PYTHON" -m pip check
(cd frontend && npm ci --cache "$PGWEB_ROOT/.localdata/npm-cache" --no-audit --no-fund)
printf '%s\n' 'Зависимости установлены. Локальный запуск: scripts/dev.sh init, db, migrate, start.'
