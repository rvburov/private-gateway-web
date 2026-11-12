#!/usr/bin/env bash
# Деплой на сервере AI Agent Capper. Запускает пользователь deploy (вручную или GitHub Actions
# по SSH). Адаптация AI Agent Capper deploy/deploy.sh (docs/sources/infra-reuse.md).
#   bash /opt/private-gateway-web/deploy/deploy.sh                 последний коммит master
#   bash /opt/private-gateway-web/deploy/deploy.sh --ref 3f2a9c1    конкретный коммит master (откат)
#   --no-fetch    не брать код из GitHub: развернуть то, что лежит в папке
#   --no-pull     не обновлять базовые образы (если Docker Hub недоступен)
#   --no-backup   не снимать копию базы перед миграциями
#
# Шаги: код из origin/master → образы работающей версии получают тег previous → сборка →
# PostgreSQL и бэкап → копия базы (manual/) → миграции отдельным контейнером → перезапуск →
# файл сайта для общего входа (Caddy capper, deploy/caddy-sites) → проверка
# https://<домен>/api/health с версией нового коммита. Сбой после начала сборки — откат на
# образы previous и код прежней версии. Миграции вниз не откатываются (deploy/README.md).
#
# Ключ GitHub Actions ограничен этой командой (authorized_keys: command="bash .../deploy.sh
# --ssh",restrict): SSH_ORIGINAL_COMMAND — "deploy <sha>", развернуть можно только коммит из
# истории master, не старше уже развернутого (старый пропускается с кодом 0).
set -Eeuo pipefail

BRANCH=master
HEALTH_ATTEMPTS=45
SITE_NAME=private-gateway-web
# Сервис → образ. Перед сборкой образ, на котором работает сервис, получает тег previous
SERVICE_IMAGES=(
  "api:private-gateway-web-api"
  "web:private-gateway-web-ui"
  "backup:private-gateway-web-backup"
)

DOMAIN=""
CODE_FROM_GIT=0
PREV_VERSION=""
ROLLBACK_READY=0

log() {
  printf '%s [deploy] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

die() {
  log "ОШИБКА: $*" >&2
  exit 1
}

compose() {
  docker compose --env-file .env -f compose.prod.yml "$@"
}

show_failure() {
  log "состояние сервисов:"
  compose ps -a || true
  log "последние строки логов:"
  compose logs --no-color --tail=80 api web || true
}

env_value() {
  # Значение переменной из deploy/.env без кавычек
  local value
  value="$(grep -E "^$1=" .env | tail -n 1 | cut -d= -f2- || true)"
  value="${value%\"}"
  value="${value#\"}"
  printf '%s\n' "$value"
}

check_health() {
  # Через общий вход по домену, как ходит браузер: TLS Caddy capper, файл сайта, Caddy сайта,
  # API, база. Пустая версия — подойдет любая (у прежнего образа ее могло не быть)
  local domain="$1" version="$2" attempt body tls_opts=()
  [ "$(env_value PGWEB_HEALTH_INSECURE)" = 1 ] && tls_opts=(--insecure)
  for ((attempt = 1; attempt <= HEALTH_ATTEMPTS; attempt++)); do
    if body="$(curl --silent --show-error --fail --max-time 5 --noproxy '*' "${tls_opts[@]}" \
      --resolve "$domain:443:127.0.0.1" "https://$domain/api/health" 2>&1)"; then
      if [ -z "$version" ] || [[ "$body" == *"\"version\":\"$version\""* ]]; then
        log "здоров: $body"
        return 0
      fi
      log "попытка $attempt: отвечает другая версия ($body)"
    else
      log "попытка $attempt: $body"
    fi
    sleep 4
  done
  return 1
}

image_version() {
  # PGWEB_VERSION из образа API: хеш коммита, из которого он собран
  docker image inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$1" 2> /dev/null \
    | sed -n 's/^PGWEB_VERSION=//p' | head -n 1
}

db_revisions() {
  compose exec -T postgres psql --username=pgweb --dbname=pgweb --no-align --tuples-only \
    --command 'SELECT version_num FROM alembic_version' 2> /dev/null || true
}

code_revisions() {
  compose run --rm --no-deps -T migrate python -c 'from alembic.config import Config
from alembic.script import ScriptDirectory
script = ScriptDirectory.from_config(Config("alembic.ini"))
print(*(revision.revision for revision in script.walk_revisions()))'
}

master_revisions() {
  git -C .. grep -h -o -E "^revision(: *str)? *= *[\"'][A-Za-z0-9_]+[\"']" "origin/$BRANCH" \
    -- backend/alembic/versions | sed -E "s/.*[\"']([A-Za-z0-9_]+)[\"']$/\1/"
}

missing_from() {
  # Слова из $1, которых нет среди слов $2
  local word words=" ${2//$'\n'/ } "
  for word in $1; do
    [[ "$words" == *" $word "* ]] || printf '%s ' "$word"
  done
}

migrate() {
  # alembic upgrade head. Ревизия базы, которой нет в коде (деплой прежнего коммита после
  # отката), — миграции пропускаются, если и она, и миграции кода есть в master
  local db_revs code_revs master_revs ahead
  db_revs="$(db_revisions)"
  if [ -n "$db_revs" ] && code_revs="$(code_revisions)" && [ -n "$code_revs" ]; then
    ahead="$(missing_from "$db_revs" "$code_revs")"
  fi
  if [ -z "${ahead:-}" ]; then
    compose run --rm --no-deps migrate
    return
  fi
  master_revs="$(master_revisions || true)"
  if [ -n "$(missing_from "$ahead $code_revs" "$master_revs")" ]; then
    log "в базе ревизия ${ahead% }: ее нет в этом коде, а в $BRANCH нет ее самой или миграций" \
      "этого кода (удален файл миграции?). Схему вернуть копией из manual/: deploy/README.md"
    return 1
  fi
  log "схема базы новее кода: ревизия ${ahead% } из более нового коммита $BRANCH." \
    "Миграции пропущены, вниз они не откатываются (deploy/README.md)"
}

remember_images() {
  local pair service image container id
  ROLLBACK_READY=1
  for pair in "${SERVICE_IMAGES[@]}"; do
    service="${pair%%:*}"
    image="${pair#*:}"
    id=""
    container="$(compose ps --all --quiet "$service" 2> /dev/null | head -n 1 || true)"
    if [ -n "$container" ]; then
      id="$(docker inspect --format '{{.Image}}' "$container" 2> /dev/null || true)"
    fi
    [ -n "$id" ] || id="$(docker image inspect --format '{{.Id}}' "$image:latest" 2> /dev/null || true)"
    if [ -z "$id" ] || ! docker tag "$id" "$image:previous" 2> /dev/null; then
      ROLLBACK_READY=0
    fi
  done
  if [ "$ROLLBACK_READY" = 1 ]; then
    PREV_VERSION="$(image_version private-gateway-web-api:previous)"
    log "образы прежней версии ${PREV_VERSION:-(версия неизвестна)} сохранены с тегом previous"
  else
    log "прежних образов нет (первый деплой): при сбое откатывать некуда"
  fi
}

ingress_subnet() {
  # Подсеть сети общего входа, которую создает docker-compose.yml AI Agent Capper
  docker network inspect --format '{{range .IPAM.Config}}{{println .Subnet}}{{end}}' caddy-ingress \
    2> /dev/null | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/[0-9]+$' | head -n 1
}

front_caddy() {
  # Контейнер Caddy AI Agent Capper (проект compose capper, сервис caddy)
  docker ps --quiet --filter "label=com.docker.compose.project=${PGWEB_FRONT_PROJECT:-capper}" \
    --filter label=com.docker.compose.service=caddy | head -n 1
}

site_config() {
  cat <<EOF
# Private Gateway Web: файл пишет /opt/private-gateway-web/deploy/deploy.sh, ручные правки
# перезапишутся. Общий вход сервера: Caddy AI Agent Capper (Р31), сеть caddy-ingress
$DOMAIN {
	header {
		Strict-Transport-Security "max-age=31536000"
		-Server
		-Via
		defer
	}
	reverse_proxy $SITE_NAME:8080
}
EOF
}

install_site() {
  # Файл сайта для общего входа: проверка всей конфигурации Caddy capper с новым файлом в
  # отдельном контейнере, затем замена файла и caddy reload. Не прошло — прежний файл
  # возвращается: ошибка в нем не должна остановить сайт capper
  local sites_dir target candidate cid image capper_domain check backup=""
  sites_dir="$(env_value PGWEB_CADDY_SITES_DIR)"
  sites_dir="${sites_dir:-/opt/ai_agent_capper/deploy/caddy-sites}"
  target="$sites_dir/$SITE_NAME.caddy"
  if [ ! -d "$sites_dir" ] || [ ! -w "$sites_dir" ]; then
    die "нет папки $sites_dir или нет права записи: запустите server-setup.sh (deploy/README.md)"
  fi
  candidate="$(site_config)"
  if [ -f "$target" ] && [ "$(cat "$target")" = "$candidate" ]; then
    log "файл сайта для общего входа не изменился"
    return 0
  fi
  cid="$(front_caddy)"
  [ -n "$cid" ] || die "Caddy AI Agent Capper не запущен: общий вход недоступен"
  image="$(docker inspect --format '{{.Image}}' "$cid")"
  capper_domain="$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$cid" \
    | sed -n 's/^CAPPER_DOMAIN=//p' | head -n 1)"
  check="$(mktemp -d /tmp/pgweb-site.XXXXXX)"
  find "$sites_dir" -maxdepth 1 -type f -name '*.caddy' ! -name "$SITE_NAME.caddy" \
    -exec cp -- {} "$check/" \;
  printf '%s\n' "$candidate" > "$check/$SITE_NAME.caddy"
  chmod -R a+rX "$check"
  if ! docker run --rm --network none -e "CAPPER_DOMAIN=${capper_domain:-localhost}" \
    -v "$check:/etc/caddy/sites:ro" --entrypoint caddy "$image" \
    validate --config /etc/caddy/Caddyfile --adapter caddyfile > "$check/validate.log" 2>&1; then
    tail -n 20 "$check/validate.log" >&2
    rm -rf -- "$check"
    return 1
  fi
  rm -rf -- "$check"
  if [ -f "$target" ]; then
    backup="$(mktemp /tmp/pgweb-site-prev.XXXXXX)"
    cp -- "$target" "$backup"
  fi
  printf '%s\n' "$candidate" > "$sites_dir/.$SITE_NAME.tmp"
  chmod 644 "$sites_dir/.$SITE_NAME.tmp"
  mv -f -- "$sites_dir/.$SITE_NAME.tmp" "$target"
  if docker exec "$cid" caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile > /dev/null 2>&1; then
    log "файл сайта для общего входа обновлен: $target"
    [ -z "$backup" ] || rm -f -- "$backup"
    return 0
  fi
  log "caddy reload не прошел, возвращаю прежний файл сайта"
  if [ -n "$backup" ]; then mv -f -- "$backup" "$target"; else rm -f -- "$target"; fi
  docker exec "$cid" caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile > /dev/null 2>&1 || true
  return 1
}

rollback() {
  local pair commit
  if [ "$ROLLBACK_READY" != 1 ]; then
    log "откат невозможен: прежних образов нет"
    return 1
  fi
  log "откат на прежнюю версию ${PREV_VERSION:-(версия неизвестна)}"
  for pair in "${SERVICE_IMAGES[@]}"; do
    docker tag "${pair#*:}:previous" "${pair#*:}:latest" || return 1
  done
  if [ "$CODE_FROM_GIT" = 1 ] && [[ "$PREV_VERSION" =~ ^[0-9a-f]{7,40}$ ]] \
    && commit="$(git rev-parse --verify --quiet "$PREV_VERSION^{commit}")"; then
    git reset --hard --quiet "$commit"
  else
    log "ВНИМАНИЕ: код в папке не возвращен (нет коммита прежней версии или --no-fetch)"
  fi
  if compose up -d --no-build --remove-orphans \
    && compose up -d --no-build --wait --wait-timeout 180 api web \
    && check_health "$DOMAIN" "$PREV_VERSION"; then
    log "откат выполнен: работает ${PREV_VERSION:-прежняя версия}"
    return 0
  fi
  show_failure
  log "ОШИБКА: откат не помог, сайт может не работать. Логи выше; дальше — deploy/README.md"
  return 1
}

fail() {
  rollback || true
  die "$@"
}

main() {
  local ref="origin/$BRANCH" fetch=1 pull=1 backup=1 ssh_mode=0
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --ref) ref="${2:?после --ref нужен коммит}"; shift ;;
      --no-fetch) fetch=0 ;;
      --no-pull) pull=0 ;;
      --no-backup) backup=0 ;;
      --ssh) ssh_mode=1 ;;
      *) die "неизвестный аргумент: $1" ;;
    esac
    shift
  done

  if [ "$ssh_mode" = 1 ]; then
    # Команда от GitHub Actions: "deploy" или "deploy <sha>"; другое не принимается
    local words=()
    read -r -a words <<< "${SSH_ORIGINAL_COMMAND:-deploy}"
    if [ "${words[0]:-}" != deploy ] || [ "${#words[@]}" -gt 2 ]; then
      die "разрешена только команда deploy"
    fi
    if [ -n "${words[1]:-}" ]; then
      [[ "${words[1]}" =~ ^[0-9a-f]{7,40}$ ]] || die "ожидается хеш коммита"
      ref="${words[1]}"
    fi
  fi

  cd "$(dirname "$(readlink -f "$0")")/.."
  [ -f deploy/.env ] || die "нет deploy/.env: запустите server-setup.sh (deploy/README.md)"
  if [ "$fetch" = 1 ] || [ "${PGWEB_DEPLOY_REEXEC:-}" = 1 ]; then
    CODE_FROM_GIT=1
  fi

  exec 9> /tmp/pgweb-deploy.lock
  flock -n 9 || die "деплой уже идет"

  if [ "$fetch" = 1 ]; then
    local before target
    before="$(git rev-parse HEAD)"
    log "код из GitHub"
    git fetch --prune --quiet origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH"
    target="$(git rev-parse --verify --quiet "$ref^{commit}")" || die "коммит $ref не найден"
    git merge-base --is-ancestor "$target" "origin/$BRANCH" \
      || die "коммит $ref не из истории $BRANCH: такой не разворачиваем"
    # Из GitHub Actions — только вперед. Строку «деплой пропущен» ищет workflow деплоя
    if [ "$ssh_mode" = 1 ] && [ "$target" != "$before" ] \
      && git merge-base --is-ancestor "$target" "$before"; then
      log "деплой пропущен: на сервере уже более новый коммит $(git rev-parse --short=12 "$before")," \
        "а $(git rev-parse --short=12 "$target") старше. Откат — вручную: bash deploy.sh --ref <хеш>"
      exit 0
    fi
    git reset --hard --quiet "$target"
    # Новая версия этого скрипта сама доделывает деплой
    if [ "${PGWEB_DEPLOY_REEXEC:-}" != 1 ] && ! git diff --quiet "$before" "$target" -- deploy/deploy.sh; then
      log "deploy.sh изменился, запускаю новую версию"
      local rest=()
      [ "$pull" = 1 ] || rest+=(--no-pull)
      [ "$backup" = 1 ] || rest+=(--no-backup)
      PGWEB_DEPLOY_REEXEC=1 exec bash deploy/deploy.sh --no-fetch "${rest[@]}"
    fi
  fi

  local version
  version="$(git rev-parse --short=12 HEAD)"
  export PGWEB_VERSION="$version"
  log "разворачиваю $version: $(git log -1 --format=%s)"

  cd deploy
  DOMAIN="$(env_value PGWEB_DOMAIN)"
  [[ "$DOMAIN" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$ ]] \
    || die "в deploy/.env не задан PGWEB_DOMAIN или он не похож на домен"
  PGWEB_INGRESS_SUBNET="$(ingress_subnet)"
  [ -n "$PGWEB_INGRESS_SUBNET" ] \
    || die "нет сети caddy-ingress: сначала разверните AI Agent Capper с общим входом (его Р31)"
  export PGWEB_INGRESS_SUBNET

  remember_images

  log "сборка образов"
  local build_args=()
  [ "$pull" = 1 ] && build_args+=(--pull)
  compose build "${build_args[@]}" api web backup || fail "сборка образов не удалась"
  if [ "$pull" = 1 ]; then
    compose pull --quiet postgres || fail "не удалось скачать образ postgres (повторите с --no-pull)"
  fi

  log "PostgreSQL и бэкап"
  compose up -d --wait postgres || fail "PostgreSQL не запустился"
  # Копию перед миграциями снимает уже новый контейнер backup. Его здоровья не ждем
  compose up -d --no-deps backup || fail "контейнер backup не запустился"

  if [ "$backup" = 1 ] && [ -z "$(env_value BACKUP_AGE_RECIPIENTS)" ]; then
    log "ВНИМАНИЕ: бэкапы не настроены (BACKUP_AGE_RECIPIENTS в deploy/.env)," \
      "копия перед миграциями не снимается"
  elif [ "$backup" = 1 ]; then
    log "копия базы перед миграциями"
    compose exec -T backup backup.sh --manual \
      || fail "копия базы не создана, деплой остановлен (без копии: --no-backup)"
  fi

  log "миграции"
  if ! migrate; then
    show_failure
    fail "миграции не применились"
  fi

  log "перезапуск сервисов"
  if ! compose up -d --remove-orphans \
    || ! compose up -d --wait --wait-timeout 180 api web; then
    show_failure
    fail "сервисы не стали здоровыми за 3 минуты"
  fi

  log "общий вход: файл сайта для Caddy AI Agent Capper"
  install_site || fail "файл сайта для общего входа не принят Caddy, сайт capper не тронут"

  log "проверка https://$DOMAIN/api/health"
  if ! check_health "$DOMAIN" "$version"; then
    show_failure
    fail "сайт не отвечает через общий вход. Проверьте DNS домена и сертификат:" \
      "логи caddy в /opt/ai_agent_capper/deploy (docker compose logs caddy)"
  fi

  local backup_health
  backup_health="$(docker inspect --format '{{.State.Health.Status}}' "$(compose ps -q backup)" \
    2> /dev/null || true)"
  if [ "$backup_health" = unhealthy ]; then
    log "ВНИМАНИЕ: контейнер backup нездоров (последний бэкап или проверка упали):" \
      "docker compose logs backup"
  fi

  # Висящие слои и кэш сборки старше недели занимают место на диске
  docker image prune --force > /dev/null
  docker builder prune --force --filter until=168h > /dev/null
  log "готово: $version"
}

main "$@"
