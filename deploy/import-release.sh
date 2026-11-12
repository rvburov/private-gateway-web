#!/usr/bin/env bash
# Прием выпуска клиента на сервере. Запускает только ключ workflow «Выпуск на сайт» репозитория
# private-gateway-client (authorized_keys: command="bash .../import-release.sh --ssh",restrict):
#   SSH_ORIGINAL_COMMAND = "import <платформа> <версия> <имя файла> <sha256>", файл — в stdin.
# Вручную (пользователь deploy, файл уже на сервере):
#   bash /opt/private-gateway-web/deploy/import-release.sh windows 1.2.3 /путь/к/файлу.msi
# Файл проверяется по размеру и SHA-256, вносится командой cli publish-release (она копирует его в
# закрытый том releases) и удаляется из imports. Другие команды ключ выполнить не может.
set -Eeuo pipefail

MAX_BYTES=$((1024 * 1024 * 1024))
DEPLOY_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
# Принятый файл: удаляется при любом выходе — после внесения он уже в томе releases
tmp=""

log() {
  printf '%s [import-release] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2
}

die() {
  log "ОШИБКА: $*"
  exit 1
}

check_args() {
  [[ "$1" =~ ^(windows|macos|linux|android)$ ]] || die "платформа: windows, macos, linux или android"
  [[ "$2" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "версия: X.Y.Z (бета-выпуски на сайт не попадают)"
  [[ "$3" =~ ^[A-Za-z0-9][A-Za-z0-9._~-]{0,150}$ ]] || die "недопустимое имя файла"
}

publish() {
  local platform="$1" version="$2" name="$3"
  cd "$DEPLOY_DIR"
  docker compose --env-file .env -f compose.prod.yml run --rm -T cli \
    publish-release --platform "$platform" --version "$version" --file "/imports/$name"
}

main() {
  local imports platform version name sha actual size
  cd "$DEPLOY_DIR"
  [ -f .env ] || die "нет deploy/.env"
  imports="$DEPLOY_DIR/imports"
  mkdir -p "$imports"
  trap '[ -z "$tmp" ] || rm -f -- "$tmp"' EXIT
  exec 9> /tmp/pgweb-import.lock
  flock -w 600 9 || die "другой прием выпуска идет больше 10 минут"

  if [ "${1:-}" = --ssh ]; then
    local words=()
    read -r -a words <<< "${SSH_ORIGINAL_COMMAND:-}"
    if [ "${#words[@]}" != 5 ] || [ "${words[0]}" != import ]; then
      die "разрешена только команда import"
    fi
    platform="${words[1]}" version="${words[2]}" name="${words[3]}" sha="${words[4]}"
    check_args "$platform" "$version" "$name"
    [[ "$sha" =~ ^[0-9a-f]{64}$ ]] || die "ожидается SHA-256 файла"
    tmp="$imports/.incoming-$$"
    head -c "$((MAX_BYTES + 1))" > "$tmp"
  else
    [ "$#" = 3 ] || die "использование: import-release.sh <платформа> <версия> <файл>"
    platform="$1" version="$2" name="$(basename "$3")"
    check_args "$platform" "$version" "$name"
    [ -f "$3" ] || die "нет файла $3"
    tmp="$imports/.incoming-$$"
    cp -- "$3" "$tmp"
    sha="$(sha256sum "$tmp" | cut -d' ' -f1)"
  fi

  size="$(stat -c %s "$tmp")"
  [ "$size" -gt 0 ] || die "файл пустой"
  [ "$size" -le "$MAX_BYTES" ] || die "файл больше 1 ГБ"
  actual="$(sha256sum "$tmp" | cut -d' ' -f1)"
  [ "$actual" = "$sha" ] || die "SHA-256 не совпал: файл поврежден при передаче"
  chmod 644 "$tmp"
  mv -f -- "$tmp" "$imports/$name"
  tmp="$imports/$name"
  log "принят $name ($size байт), вношу $platform $version"
  publish "$platform" "$version" "$name"
  log "готово: $platform $version, SHA-256 $actual"
}

main "$@"
