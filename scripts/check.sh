#!/usr/bin/env bash
set -euo pipefail
PGWEB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PGWEB_PYTHON="$PGWEB_ROOT/backend/.venv/bin/python"
[[ -x "$PGWEB_ROOT/backend/.venv/Scripts/python.exe" ]] && PGWEB_PYTHON="$PGWEB_ROOT/backend/.venv/Scripts/python.exe"
[[ -x "$PGWEB_PYTHON" ]] || { echo 'Сначала: scripts/cloud-setup.sh' >&2; exit 1; }
if [[ -z "${PGWEB_TEST_DATABASE_URL:-}" ]]; then
  echo 'Задайте PGWEB_TEST_DATABASE_URL для отдельной PostgreSQL-базы с test в имени; рабочую базу тестам не передавать.' >&2
  exit 1
fi
mkdir -p "$PGWEB_ROOT/artifacts/test-results"
(cd "$PGWEB_ROOT/backend" && "$PGWEB_PYTHON" -m ruff check .)
(cd "$PGWEB_ROOT/backend" && "$PGWEB_PYTHON" -m pytest -q --junitxml="$PGWEB_ROOT/artifacts/test-results/backend.xml")
(cd "$PGWEB_ROOT/frontend" && npm run typecheck && npm test && npm run build)
printf '%s\n' 'Проверки кода, backend и frontend завершены.'
