#!/usr/bin/env bash
# Восстановление базы сайта из копии. Стирает текущую базу целиком, поэтому: сначала
# остановить api, перед удалением снимается копия текущей базы (manual/), а копия для
# восстановления сначала целиком расшифровывается и читается.
# Адаптация AI Agent Capper deploy/backup/restore.sh.
#
#   restore.sh --list                       копии в папке и в S3
#   restore.sh latest                       самая свежая локальная копия
#   restore.sh daily/pgweb-20261112T014500Z.dump.age
#   restore.sh s3:monthly/pgweb-2026-11_20261101T014500Z.dump.age   скачать из S3
#   --yes                                   не спрашивать подтверждение
#   --no-safety-copy                        не снимать копию текущей базы (если она сломана)
#
# Запуск (из папки deploy на сервере, deploy/README.md, раздел «Бэкапы»):
#   docker compose stop api
#   docker compose exec backup restore.sh latest
#   docker compose run --rm migrate
#   docker compose start api
set -Eeuo pipefail
SCRIPT_NAME=restore
# shellcheck source=common.sh
. "$(dirname "$0")/common.sh"

list_copies() {
  local tier file
  for tier in "${TIERS[@]}"; do
    while IFS= read -r file; do
      [ -n "$file" ] && printf '%s/%s  %s\n' "$tier" "$(basename "$file")" "$(du -h "$file" | cut -f1)"
    done < <(list_tier "$tier")
  done
  if s3_enabled; then
    s3_setup
    echo "--- в S3 ($(s3_path "")):"
    for tier in "${TIERS[@]}"; do
      rclone lsf --files-only --include "$DUMP_PREFIX-*$DUMP_SUFFIX" "$(s3_path "$tier")" \
        2> /dev/null | sort | sed "s|^|s3:$tier/|"
    done
  fi
}

source_arg=""
assume_yes=0
safety_copy=1
for arg in "$@"; do
  case "$arg" in
    --list) list_copies; exit 0 ;;
    --yes) assume_yes=1 ;;
    --no-safety-copy) safety_copy=0 ;;
    -*) die "неизвестный ключ: $arg" ;;
    *) source_arg="$arg" ;;
  esac
done
[ -n "$source_arg" ] || die "какую копию восстановить? restore.sh --list покажет список"
has_identity || die "не задан BACKUP_AGE_IDENTITY: без секретного ключа age копию не расшифровать"

umask 077
work="$(mktemp -d /tmp/restore.XXXXXX)"
trap 'rm -rf -- "$work"' EXIT

case "$source_arg" in
  latest)
    file="$(latest_dump)"
    [ -n "$file" ] || die "в $BACKUP_DIR нет копий; копия из S3: restore.sh s3:<вид>/<файл>"
    ;;
  s3:*)
    s3_enabled || die "S3 не настроен (BACKUP_S3_*)"
    s3_setup
    remote="${source_arg#s3:}"
    [[ "$remote" =~ ^(daily|weekly|monthly|manual)/[A-Za-z0-9._-]+$ ]] \
      || die "ожидается s3:<вид>/<файл>, например s3:daily/$DUMP_PREFIX-...$DUMP_SUFFIX"
    file="$work/$(basename "$remote")"
    log "скачиваю $remote из S3"
    rclone copyto "$(s3_path "$(dirname "$remote")")/$(basename "$remote")" "$file"
    ;;
  *)
    if [ -f "$source_arg" ]; then
      file="$source_arg"
    elif [ -f "$BACKUP_DIR/$source_arg" ]; then
      file="$BACKUP_DIR/$source_arg"
    else
      die "копия $source_arg не найдена (restore.sh --list)"
    fi
    ;;
esac

log "расшифровываю ${file#"$BACKUP_DIR"/}"
age_decrypt "$file" > "$work/restore.dump"
pg_restore --list "$work/restore.dump" > /dev/null
log "копия цела: $(du -h "$work/restore.dump" | cut -f1) после расшифровки"

others="$(psql --no-psqlrc --tuples-only --no-align --dbname=postgres --command="
  SELECT count(*) FROM pg_stat_activity
  WHERE datname = '$PGDATABASE' AND pid <> pg_backend_pid()")"
if [ "$others" != 0 ]; then
  die "к базе $PGDATABASE подключено соединений: $others. Остановите приложение:" \
    "docker compose stop api"
fi

if [ "$assume_yes" != 1 ]; then
  printf 'База %s на %s будет стерта и заменена копией. Введите имя базы для подтверждения: ' \
    "$PGDATABASE" "$PGHOST"
  read -r answer
  [ "$answer" = "$PGDATABASE" ] || die "отменено"
fi

if [ "$safety_copy" = 1 ]; then
  log "копия текущей базы перед восстановлением (manual/)"
  "$(dirname "$0")/backup.sh" --manual
fi

exec 8> "$BACKUP_DIR/.lock"
acquire_lock 8 3600 || die "бэкап идет больше часа, восстановление отложено"

log "пересоздаю базу $PGDATABASE"
psql --no-psqlrc --quiet --set=ON_ERROR_STOP=1 --dbname=postgres \
  --command="DROP DATABASE IF EXISTS \"$PGDATABASE\" WITH (FORCE)" \
  --command="CREATE DATABASE \"$PGDATABASE\" OWNER \"$PGUSER\""
pg_restore --dbname="$PGDATABASE" --no-owner --exit-on-error --jobs=2 "$work/restore.dump"

log "база восстановлена из ${source_arg}: $(psql --no-psqlrc --tuples-only --no-align --command="
  SELECT 'пользователей ' || (SELECT count(*) FROM users)
    || ', приглашений ' || (SELECT count(*) FROM access_codes)
    || ', миграция ' || (SELECT string_agg(version_num, ',') FROM alembic_version)")"
log "дальше: docker compose run --rm migrate && docker compose start api." \
  "Файлы выпусков в копию базы не входят: при новом сервере внесите их заново (publish-release)"
