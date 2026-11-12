# shellcheck shell=bash
# Общие функции скриптов бэкапа. Подключается из backup.sh, restore.sh, restore-check.sh,
# healthcheck.sh и entrypoint.sh. Адаптация AI Agent Capper deploy/backup/common.sh
# (docs/sources/infra-reuse.md): другое имя копий и своя папка в бакете.
#
# Настройки — переменные окружения контейнера backup (deploy/compose.prod.yml, значения
# из deploy/.env):
#   PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE   рабочая база
#   BACKUP_AGE_RECIPIENTS   публичные ключи age (age1...), через запятую или пробел
#   BACKUP_AGE_IDENTITY     секретный ключ age сервера (AGE-SECRET-KEY-1...): нужен для
#                           проверки восстановления и для restore.sh
#   BACKUP_KEEP_DAILY / _WEEKLY / _MONTHLY / _MANUAL   сколько копий хранить
#   BACKUP_S3_*             S3-совместимое хранилище (необязательно); BACKUP_S3_PREFIX —
#                           папка в бакете, по умолчанию private-gateway-web

BACKUP_DIR="${BACKUP_DIR:-/backups}"
STATUS_DIR="$BACKUP_DIR/.status"
TIERS=(daily weekly monthly manual)
DUMP_PREFIX="pgweb"
DUMP_SUFFIX=".dump.age"
S3_REMOTE="s3backup"

# Сообщения — в stderr: stdout остается для данных (restore.sh --list, age-keygen)
log() {
  printf '%s [%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${SCRIPT_NAME:-backup}" "$*" >&2
}

warn() {
  log "ВНИМАНИЕ: $*"
}

die() {
  log "ОШИБКА: $*"
  exit 1
}

keep_count() {
  case "$1" in
    daily) echo "${BACKUP_KEEP_DAILY:-7}" ;;
    weekly) echo "${BACKUP_KEEP_WEEKLY:-4}" ;;
    monthly) echo "${BACKUP_KEEP_MONTHLY:-6}" ;;
    manual) echo "${BACKUP_KEEP_MANUAL:-5}" ;;
    *) die "неизвестный вид копий: $1" ;;
  esac
}

# Аргументы -r для age из BACKUP_AGE_RECIPIENTS (через запятую, пробел или перевод строки)
age_recipient_args() {
  local raw="${BACKUP_AGE_RECIPIENTS:-}" item
  AGE_RECIPIENT_ARGS=()
  for item in ${raw//,/ }; do
    AGE_RECIPIENT_ARGS+=(-r "$item")
  done
  [ "${#AGE_RECIPIENT_ARGS[@]}" -gt 0 ]
}

has_identity() {
  [ -n "${BACKUP_AGE_IDENTITY:-}" ]
}

# Расшифровка в stdout. Секретный ключ передается age через дескриптор, не через файл
age_decrypt() {
  age --decrypt --identity <(printf '%s\n' "$BACKUP_AGE_IDENTITY") "$1"
}

# Метка времени копии из имени файла: pgweb-20261112T013000Z.dump.age и
# pgweb-2026-W46_20261112T013000Z.dump.age дают 20261112T013000Z
dump_stamp() {
  local base
  base="$(basename "$1" "$DUMP_SUFFIX")"
  printf '%s\n' "${base##*[-_]}"
}

# 20261112T013000Z → 2026-11-12T01:30:00Z (для SQL)
stamp_to_iso() {
  local s="$1"
  printf '%s-%s-%sT%s:%s:%sZ\n' "${s:0:4}" "${s:4:2}" "${s:6:2}" "${s:9:2}" "${s:11:2}" "${s:13:2}"
}

# Файлы копий вида копий, старые первыми
list_tier() {
  local dir="$BACKUP_DIR/$1"
  [ -d "$dir" ] || return 0
  find "$dir" -maxdepth 1 -type f -name "$DUMP_PREFIX-*$DUMP_SUFFIX" | sort
}

# Самая свежая копия среди всех видов (по метке времени в имени)
latest_dump() {
  local tier file best="" best_stamp="" stamp
  for tier in "${TIERS[@]}"; do
    while IFS= read -r file; do
      [ -n "$file" ] || continue
      stamp="$(dump_stamp "$file")"
      if [[ -z "$best" || "$stamp" > "$best_stamp" ]]; then
        best="$file"
        best_stamp="$stamp"
      fi
    done < <(list_tier "$tier")
  done
  printf '%s\n' "$best"
}

# Удаляет старые локальные копии сверх лимита
prune_local() {
  local tier="$1" keep files count i
  keep="$(keep_count "$tier")"
  mapfile -t files < <(list_tier "$tier")
  count="${#files[@]}"
  for ((i = 0; i < count - keep; i++)); do
    rm -f -- "${files[$i]}"
    log "удалена старая копия $tier/$(basename "${files[$i]}")"
  done
}

s3_enabled() {
  [ -n "${BACKUP_S3_BUCKET:-}" ] && [ -n "${BACKUP_S3_ENDPOINT:-}" ] \
    && [ -n "${BACKUP_S3_ACCESS_KEY_ID:-}" ] && [ -n "${BACKUP_S3_SECRET_ACCESS_KEY:-}" ]
}

# rclone настраивается переменными окружения, без файла с ключами на диске
s3_setup() {
  export RCLONE_CONFIG=/dev/null
  export RCLONE_CONFIG_S3BACKUP_TYPE=s3
  export RCLONE_CONFIG_S3BACKUP_PROVIDER="${BACKUP_S3_PROVIDER:-Other}"
  export RCLONE_CONFIG_S3BACKUP_ENDPOINT="$BACKUP_S3_ENDPOINT"
  export RCLONE_CONFIG_S3BACKUP_REGION="${BACKUP_S3_REGION:-}"
  export RCLONE_CONFIG_S3BACKUP_ACCESS_KEY_ID="$BACKUP_S3_ACCESS_KEY_ID"
  export RCLONE_CONFIG_S3BACKUP_SECRET_ACCESS_KEY="$BACKUP_S3_SECRET_ACCESS_KEY"
  # Бакет уже существует (общий с AI Agent Capper), создавать его не нужно
  export RCLONE_CONFIG_S3BACKUP_NO_CHECK_BUCKET=true
  export RCLONE_STATS_LOG_LEVEL=DEBUG
}

# Путь в хранилище: s3backup:<бакет>/<папка>/<вид>. Папка своя: в том же бакете лежат
# копии AI Agent Capper (папка capper), и каждый проект удаляет старые копии только у себя
s3_path() {
  local prefix="${BACKUP_S3_PREFIX:-private-gateway-web}"
  prefix="${prefix#/}"
  [ -n "${prefix%/}" ] || die "BACKUP_S3_PREFIX не может быть пустым: копии смешались бы с чужими"
  printf '%s:%s/%s/%s\n' "$S3_REMOTE" "$BACKUP_S3_BUCKET" "${prefix%/}" "$1"
}

# Удаляет старые копии в хранилище сверх лимита. Считает по списку в своей папке
# хранилища, поэтому потеря локальной папки не стирает копии в S3
prune_s3() {
  local tier="$1" keep files count i
  keep="$(keep_count "$tier")"
  mapfile -t files < <(rclone lsf --files-only --include "$DUMP_PREFIX-*$DUMP_SUFFIX" \
    "$(s3_path "$tier")" | sort)
  count="${#files[@]}"
  for ((i = 0; i < count - keep; i++)); do
    rclone deletefile "$(s3_path "$tier")/${files[$i]}"
    log "удалена старая копия в S3: $tier/${files[$i]}"
  done
}

# Блокировка: копия, проверка и восстановление не идут одновременно.
# acquire_lock <номер дескриптора> <сколько секунд ждать>; дескриптор открыт заранее
acquire_lock() {
  local fd="$1" limit="$2" waited=0
  until flock -n "$fd"; do
    [ "$waited" -lt "$limit" ] || return 1
    sleep 5
    waited=$((waited + 5))
  done
}

mark_status() {
  # mark_status <backup|restore-check> <ok|failed> <текст>
  mkdir -p "$STATUS_DIR"
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$3" > "$STATUS_DIR/$1.$2"
}

# Сводка данных для сверки копии с рабочей базой: строки не новее момента копии.
# Журнал действий сверяется за 30 дней до копии: старые записи удаляет команда prune
summary_sql() {
  local at="$1"
  cat <<SQL
SELECT concat_ws(' | ',
  'пользователей ' || (SELECT count(*) FROM users WHERE created_at <= '$at'),
  'приглашений ' || (SELECT count(*) FROM access_codes WHERE created_at <= '$at'),
  'событий журнала ' || (SELECT count(*) FROM audit_events
    WHERE at <= '$at' AND at > '$at'::timestamptz - interval '30 days'),
  'выпусков ' || (SELECT count(*) FROM releases WHERE created_at <= '$at'),
  'миграция ' || (SELECT string_agg(version_num, ',') FROM alembic_version)
)
SQL
}
