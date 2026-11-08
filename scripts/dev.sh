#!/usr/bin/env bash
# Локальная разработка без публикации сайта и без настройки VPN.
set -euo pipefail
PGWEB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PGWEB_ENV_FILE="$PGWEB_ROOT/.env.local"
PGWEB_PYTHON="$PGWEB_ROOT/backend/.venv/bin/python"
[[ -x "$PGWEB_ROOT/backend/.venv/Scripts/python.exe" ]] && PGWEB_PYTHON="$PGWEB_ROOT/backend/.venv/Scripts/python.exe"

init_env() {
  if command -v python3 >/dev/null 2>&1; then PGWEB_SYSTEM_PYTHON=python3; else PGWEB_SYSTEM_PYTHON=python; fi
  "$PGWEB_SYSTEM_PYTHON" - "$PGWEB_ROOT" <<'PY'
import os
from pathlib import Path
import secrets
import sys

root = Path(sys.argv[1])
target = root / ".env.local"
(root / ".localdata" / "downloads").mkdir(parents=True, exist_ok=True)
(root / ".localdata" / "imports").mkdir(parents=True, exist_ok=True)
if target.exists():
    print("Существующий .env.local сохранен без изменений.")
else:
    password = secrets.token_hex(24)
    values = {
        "POSTGRES_PASSWORD": password,
        "PGWEB_SECRET_KEY": secrets.token_hex(32),
        "PGWEB_MASTER_KEYS": "1:" + secrets.token_hex(32),
        "PGWEB_DATABASE_URL": f"postgresql+asyncpg://pgweb:{password}@127.0.0.1:5433/pgweb",
        "PGWEB_PUBLIC_ORIGIN": "http://127.0.0.1:5173",
        "PGWEB_COOKIE_SECURE": "false",
        "PGWEB_DOWNLOAD_ROOT": "../.localdata/downloads",
    }
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write("# Только локальная разработка. Не публиковать и не коммитить.\n")
        for name, value in values.items():
            output.write(f"{name}={value}\n")
    print("Создан .env.local со случайными ключами; значения не выводятся.")
PY
}

need_environment() {
  [[ -f "$PGWEB_ENV_FILE" ]] || { echo 'Сначала: scripts/dev.sh init' >&2; exit 1; }
  [[ -x "$PGWEB_PYTHON" ]] || { echo 'Сначала: scripts/cloud-setup.sh' >&2; exit 1; }
}

# Файл настроек читается dotenv, а не исполняется как shell-код. stdin остается терминалом.
backend() {
  need_environment
  cd "$PGWEB_ROOT/backend"
  exec "$PGWEB_PYTHON" -c 'import os,sys; from dotenv import load_dotenv; load_dotenv(sys.argv[1], override=False); os.execvp(sys.argv[2], sys.argv[2:])' "$PGWEB_ENV_FILE" "$@"
}

case "${1:-help}" in
  init) init_env ;;
  setup) init_env; exec "$PGWEB_ROOT/scripts/cloud-setup.sh" ;;
  db)
    init_env
    docker compose --env-file "$PGWEB_ENV_FILE" -f "$PGWEB_ROOT/deploy/compose.yml" -f "$PGWEB_ROOT/deploy/compose.dev.yml" up -d --wait postgres
    ;;
  migrate) backend "$PGWEB_PYTHON" -m alembic upgrade head ;;
  admin)
    shift
    backend "$PGWEB_PYTHON" -m app.cli bootstrap-admin "$@"
    ;;
  cli)
    shift
    backend "$PGWEB_PYTHON" -m app.cli "$@"
    ;;
  start)
    need_environment
    [[ -f "$PGWEB_ROOT/frontend/node_modules/vite/bin/vite.js" ]] || { echo 'Сначала: scripts/cloud-setup.sh' >&2; exit 1; }
    PGWEB_API_PID=
    PGWEB_UI_PID=
    cleanup() {
      trap - EXIT INT TERM
      [[ -z "$PGWEB_API_PID" ]] || kill "$PGWEB_API_PID" 2>/dev/null || true
      [[ -z "$PGWEB_UI_PID" ]] || kill "$PGWEB_UI_PID" 2>/dev/null || true
      wait 2>/dev/null || true
    }
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    backend "$PGWEB_PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers --no-server-header --no-access-log &
    PGWEB_API_PID=$!
    (cd "$PGWEB_ROOT/frontend" && exec node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort) &
    PGWEB_UI_PID=$!
    printf '%s\n' 'Откройте http://127.0.0.1:5173. Ctrl+C останавливает только эти два процесса.'
    # wait -n есть не во всех версиях bash на macOS.
    while kill -0 "$PGWEB_API_PID" 2>/dev/null && kill -0 "$PGWEB_UI_PID" 2>/dev/null; do sleep 1; done
    exit 1
    ;;
  stop-db)
    [[ -f "$PGWEB_ENV_FILE" ]] || exit 0
    docker compose --env-file "$PGWEB_ENV_FILE" -f "$PGWEB_ROOT/deploy/compose.yml" -f "$PGWEB_ROOT/deploy/compose.dev.yml" stop postgres
    ;;
  *)
    printf '%s\n' 'scripts/dev.sh setup | init | db | migrate | start | admin --email EMAIL | cli КОМАНДА | stop-db'
    ;;
esac
