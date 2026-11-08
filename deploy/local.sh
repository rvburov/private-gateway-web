#!/usr/bin/env bash
# Контейнерный стенд на 127.0.0.1:8080. Не настраивает удаленный сервер.
set -euo pipefail
PGWEB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PGWEB_ENV_FILE="$PGWEB_ROOT/.env.local"
PGWEB_COMPOSE=(-f "$PGWEB_ROOT/deploy/compose.yml")
if [[ -n "${CODEX_PROXY_CERT:-}" ]]; then
  export PGWEB_BUILD_CA_FILE="$CODEX_PROXY_CERT"
  PGWEB_COMPOSE+=(-f "$PGWEB_ROOT/deploy/compose.cloud.yml")
fi
if [[ -n "${MSYSTEM:-}" ]]; then export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'; fi

dc() { docker compose --env-file "$PGWEB_ENV_FILE" "${PGWEB_COMPOSE[@]}" "$@"; }

case "${1:-help}" in
  up)
    "$PGWEB_ROOT/scripts/dev.sh" init
    dc build api web
    dc up -d --wait postgres
    dc run --rm migrate
    dc up -d --wait api web
    printf '%s\n' 'Локальный стенд: http://127.0.0.1:8080. Аккаунтов по умолчанию нет.'
    ;;
  admin)
    shift
    dc exec api python -m app.cli bootstrap-admin "$@"
    ;;
  cli)
    shift
    dc run --rm cli "$@"
    ;;
  migrate) dc run --rm migrate ;;
  status) dc ps ;;
  logs) shift; dc logs --tail=100 "$@" ;;
  down) dc down ;;
  config) dc config --quiet ;;
  *) printf '%s\n' 'deploy/local.sh up | admin --email EMAIL | cli КОМАНДА | migrate | status | logs [СЕРВИС] | down | config' ;;
esac
