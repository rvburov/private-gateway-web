#!/usr/bin/env bash
# Прием выпуска клиента на сервере. Запускает только ключ workflow «Выпуск на сайт» репозитория
# private-gateway-client (authorized_keys: command="bash .../import-release.sh --ssh",restrict).
# SSH_ORIGINAL_COMMAND — одна из команд, файл — в stdin:
#   import <платформа> <версия> <имя файла> <sha256>  установщик: хранилище и каталог «Скачать клиент»
#   asset <версия> <имя файла> <sha256>               файл ленты обновлений (rpm и другие): только хранилище
#   update-sig <версия> update.json.sig <sha256>      подпись манифеста: ждет update в папке приема
#   update <версия> update.json <sha256>              манифест последним: лента обновлений программы
# Порядок выпуска: import, asset, update-sig, update; раскатка повторяет update-sig и update.
# Вручную (пользователь deploy, файл уже на сервере):
#   bash /opt/private-gateway-web/deploy/import-release.sh windows 1.2.3 /путь/к/файлу.msi
# Файл проверяется по размеру и SHA-256, вносится командой cli (publish-release, store-file или
# publish-update — она проверяет, что файлы манифеста уже на сайте; стоп-крану, доле 0, файлы не
# нужны) и удаляется из imports.
# Подпись действует для одного следующего update той же версии и не дольше часа. Бета-выпуски не
# принимаются. Другие команды ключ выполнить не может.
set -Eeuo pipefail

MAX_BYTES=$((1024 * 1024 * 1024))
# Пределы программы: манифест до 64 КБ, подпись до 1 КБ (с переводом строки)
MAX_MANIFEST=$((64 * 1024))
MAX_SIGNATURE=1100
DEPLOY_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
# Принятый файл: удаляется при любом выходе — после внесения он уже в томе releases или в базе
tmp=""
# Подпись манифеста, которую взял update: одноразовая, удаляется при любом исходе
pending=""

log() {
  printf '%s [import-release] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >&2
}

die() {
  log "ОШИБКА: $*"
  exit 1
}

check_version() {
  [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "версия: X.Y.Z (бета-выпуски на сайт не попадают)"
}

check_name() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._~-]{0,150}$ ]] || die "недопустимое имя файла"
}

check_args() {
  [[ "$1" =~ ^(windows|macos|linux|android)$ ]] || die "платформа: windows, macos, linux или android"
  check_version "$2"
  check_name "$3"
}

cli() {
  cd "$DEPLOY_DIR"
  docker compose --env-file .env -f compose.prod.yml run --rm -T cli "$@"
}

main() {
  local imports action platform="" version name sha actual size limit="$MAX_BYTES"
  cd "$DEPLOY_DIR"
  [ -f .env ] || die "нет deploy/.env"
  imports="$DEPLOY_DIR/imports"
  mkdir -p "$imports"
  trap '[ -z "$tmp" ] || rm -f -- "$tmp"; [ -z "$pending" ] || rm -f -- "$pending"' EXIT
  exec 9> /tmp/pgweb-import.lock
  flock -w 600 9 || die "другой прием выпуска идет больше 10 минут"

  if [ "${1:-}" = --ssh ]; then
    local words=()
    read -r -a words <<< "${SSH_ORIGINAL_COMMAND:-}"
    action="${words[0]:-}"
    case "$action" in
      import)
        [ "${#words[@]}" = 5 ] || die "ожидается: import <платформа> <версия> <имя файла> <sha256>"
        platform="${words[1]}" version="${words[2]}" name="${words[3]}" sha="${words[4]}"
        check_args "$platform" "$version" "$name"
        ;;
      asset | update-sig | update)
        [ "${#words[@]}" = 4 ] || die "ожидается: $action <версия> <имя файла> <sha256>"
        version="${words[1]}" name="${words[2]}" sha="${words[3]}"
        check_version "$version"
        check_name "$name"
        ;;
      *)
        die "разрешены только команды import, asset, update-sig и update"
        ;;
    esac
    [[ "$sha" =~ ^[0-9a-f]{64}$ ]] || die "ожидается SHA-256 файла"
    case "$action" in
      update-sig)
        [ "$name" = update.json.sig ] || die "update-sig принимает только update.json.sig"
        limit="$MAX_SIGNATURE"
        ;;
      update)
        [ "$name" = update.json ] || die "update принимает только update.json"
        limit="$MAX_MANIFEST"
        [ -f "$imports/.update-$version.json.sig" ] || die "нет подписи $version: сначала update-sig"
        pending="$imports/.update-$version.json.sig"
        # Старая подпись могла остаться от другой доли раскатки: тогда программа отвергла бы пару
        [ -n "$(find "$pending" -mmin -60)" ] \
          || die "подпись $version принята больше часа назад: отправьте update-sig заново"
        ;;
    esac
    tmp="$imports/.incoming-$$"
    head -c "$((limit + 1))" > "$tmp"
  else
    [ "$#" = 3 ] || die "использование: import-release.sh <платформа> <версия> <файл>"
    action=import platform="$1" version="$2" name="$(basename "$3")"
    check_args "$platform" "$version" "$name"
    [ -f "$3" ] || die "нет файла $3"
    tmp="$imports/.incoming-$$"
    cp -- "$3" "$tmp"
    sha="$(sha256sum "$tmp" | cut -d' ' -f1)"
  fi

  size="$(stat -c %s "$tmp")"
  [ "$size" -gt 0 ] || die "файл пустой"
  [ "$size" -le "$limit" ] || die "файл больше $limit байт"
  actual="$(sha256sum "$tmp" | cut -d' ' -f1)"
  [ "$actual" = "$sha" ] || die "SHA-256 не совпал: файл поврежден при передаче"
  chmod 644 "$tmp"
  case "$action" in
    import)
      mv -f -- "$tmp" "$imports/$name"
      tmp="$imports/$name"
      log "принят $name ($size байт), вношу $platform $version"
      cli publish-release --platform "$platform" --version "$version" --file "/imports/$name"
      ;;
    asset)
      mv -f -- "$tmp" "$imports/$name"
      tmp="$imports/$name"
      log "принят $name ($size байт), кладу в хранилище (выпуск $version)"
      cli store-file --file "/imports/$name"
      ;;
    update-sig)
      mv -f -- "$tmp" "$imports/.update-$version.json.sig"
      tmp=""
      log "принята подпись манифеста $version, жду update"
      ;;
    update)
      mv -f -- "$tmp" "$imports/.update-$version.json"
      tmp="$imports/.update-$version.json"
      log "принят манифест $version ($size байт), вношу в ленту обновлений"
      cli publish-update --version "$version" --manifest "/imports/.update-$version.json" \
        --signature "/imports/.update-$version.json.sig"
      ;;
  esac
  log "готово: $action ${platform:+$platform }$version, SHA-256 $actual"
}

main "$@"
