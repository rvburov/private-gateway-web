#!/usr/bin/env bash
# Подготовка сервера AI Agent Capper для Private Gateway Web. Запускается один раз от root
# на сервере, который уже настроил server-setup.sh capper (Docker, пользователь deploy,
# файрвол, обновления безопасности, общий вход Caddy — его Р31). Повторный запуск безопасен:
# сделанное пропускается, так можно позже добавить ключ GitHub Actions.
#
#   curl -fsSLO https://raw.githubusercontent.com/rvburov/private-gateway-web/master/deploy/server-setup.sh
#   bash server-setup.sh --domain private-gateway.duckdns.org \
#     --ci-key "ssh-ed25519 AAAA... pgweb-deploy"
#
#   --domain ДОМЕН       домен сайта (DNS A на IP этого сервера), попадет в deploy/.env
#   --ci-key КЛЮЧ        публичный ключ ed25519 только для деплоя из GitHub Actions: на сервере
#                        он может лишь запустить deploy.sh (command=..., restrict)
#   --capper-dir ПАПКА   где лежит AI Agent Capper (по умолчанию /opt/ai_agent_capper)
#   --repo URL           репозиторий (по умолчанию https://github.com/rvburov/private-gateway-web.git)
#
# Что делает: клон в /opt/private-gateway-web (владелец deploy), deploy/.env со случайными
# паролем базы и ключами; настройки бэкапа (ключи age и S3) — из deploy/.env capper, папка
# в бакете своя; папка файлов сайтов общего входа с правом записи для deploy; ключ CI.
# Пакеты, пользователи, файрвол и ssh не меняются: это уже сделал capper.
# Адаптация AI Agent Capper deploy/server-setup.sh (docs/sources/infra-reuse.md).
set -Eeuo pipefail

APP_DIR=/opt/private-gateway-web
CAPPER_DIR=/opt/ai_agent_capper
DEPLOY_USER=deploy
REPO_URL=https://github.com/rvburov/private-gateway-web.git

log() {
  printf '\n==> %s\n' "$*"
}

die() {
  printf 'ОШИБКА: %s\n' "$*" >&2
  exit 1
}

domain=""
ci_key=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --domain) domain="${2:?}"; shift ;;
    --ci-key) ci_key="${2:?}"; shift ;;
    --capper-dir) CAPPER_DIR="${2:?}"; shift ;;
    --repo) REPO_URL="${2:?}"; shift ;;
    *) die "неизвестный аргумент: $1" ;;
  esac
  shift
done

[ "$(id -u)" = 0 ] || die "запускать от root (sudo bash server-setup.sh ...)"
if [ -n "$domain" ]; then
  [[ "$domain" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$ ]] \
    || die "домен: строчные латинские буквы, цифры, точки и дефисы"
fi
if [ -n "$ci_key" ]; then
  [[ "$ci_key" =~ ^ssh-ed25519\ [A-Za-z0-9+/=]+(\ .*)?$ ]] || die "--ci-key: ожидается ключ ssh-ed25519"
fi
command -v docker > /dev/null || die "нет Docker: сначала server-setup.sh AI Agent Capper"
id "$DEPLOY_USER" > /dev/null 2>&1 || die "нет пользователя $DEPLOY_USER: сначала server-setup.sh AI Agent Capper"
id -nG "$DEPLOY_USER" | tr ' ' '\n' | grep -qx docker || die "$DEPLOY_USER не в группе docker"
[ -d "$CAPPER_DIR/deploy" ] || die "нет $CAPPER_DIR/deploy: укажите --capper-dir"
deploy_home="$(getent passwd "$DEPLOY_USER" | cut -d: -f6)"

as_deploy() {
  sudo -u "$DEPLOY_USER" -H "$@"
}

log "Репозиторий в $APP_DIR"
install -d -m 755 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$APP_DIR"
if [ ! -d "$APP_DIR/.git" ]; then
  as_deploy git clone --quiet --branch master "$REPO_URL" "$APP_DIR"
else
  echo "уже есть, не трогаю (обновляет deploy.sh)"
fi

log "Настройки deploy/.env"
env_file="$APP_DIR/deploy/.env"
capper_env="$CAPPER_DIR/deploy/.env"
if [ ! -f "$env_file" ]; then
  [ -n "$domain" ] || die "для первого запуска нужен --domain"
  tmp="$(mktemp)"
  chmod 600 "$tmp"
  {
    echo "# Создан server-setup.sh $(date -u +%Y-%m-%d). Образец и пояснения — deploy/.env.example"
    echo "COMPOSE_FILE=compose.prod.yml"
    echo "COMPOSE_PROJECT_NAME=private-gateway-web"
    echo "PGWEB_DOMAIN=$domain"
    echo "POSTGRES_PASSWORD=$(openssl rand -hex 24)"
    echo "PGWEB_SECRET_KEY=$(openssl rand -hex 32)"
    echo "PGWEB_MASTER_KEYS=1:$(openssl rand -hex 32)"
    echo "PGWEB_CADDY_SITES_DIR=$CAPPER_DIR/deploy/caddy-sites"
    echo "# Бэкапы: тот же ключ age и бакет, что у AI Agent Capper, своя папка"
    echo "BACKUP_S3_PREFIX=private-gateway-web"
    if [ -f "$capper_env" ]; then
      # Значения переносятся строками как есть, без вывода на экран
      grep -E '^(BACKUP_AGE_RECIPIENTS|BACKUP_AGE_IDENTITY|BACKUP_S3_ENDPOINT|BACKUP_S3_REGION|BACKUP_S3_PROVIDER|BACKUP_S3_BUCKET|BACKUP_S3_ACCESS_KEY_ID|BACKUP_S3_SECRET_ACCESS_KEY)=' \
        "$capper_env" || true
    fi
  } > "$tmp"
  install -m 600 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$tmp" "$env_file"
  rm -f "$tmp"
  echo "создан $env_file: пароль базы, PGWEB_SECRET_KEY и PGWEB_MASTER_KEYS заполнены"
  if grep -qE '^BACKUP_AGE_RECIPIENTS=.+' "$env_file"; then
    echo "настройки бэкапа взяты из $capper_env"
  else
    echo "ВНИМАНИЕ: в $capper_env нет ключей бэкапа: заполните BACKUP_* в $env_file сами"
  fi
else
  echo "$env_file уже есть, не трогаю"
fi

log "Папки сервера"
sites_dir="$CAPPER_DIR/deploy/caddy-sites"
install -d -m 755 "$sites_dir"
chown "$DEPLOY_USER:$DEPLOY_USER" "$sites_dir"
install -d -m 755 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$APP_DIR/deploy/imports"
echo "файлы сайтов общего входа: $sites_dir; входящие файлы выпусков: $APP_DIR/deploy/imports"

if [ -n "$ci_key" ]; then
  log "Ключ GitHub Actions (только deploy.sh)"
  install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$deploy_home/.ssh"
  touch "$deploy_home/.ssh/authorized_keys"
  key_body="$(printf '%s\n' "$ci_key" | cut -d' ' -f2)"
  if ! grep -qF "$key_body" "$deploy_home/.ssh/authorized_keys"; then
    echo "command=\"bash $APP_DIR/deploy/deploy.sh --ssh\",restrict $ci_key" \
      >> "$deploy_home/.ssh/authorized_keys"
    echo "ключ добавлен"
  else
    echo "ключ уже есть"
  fi
  chown "$DEPLOY_USER:$DEPLOY_USER" "$deploy_home/.ssh/authorized_keys"
  chmod 600 "$deploy_home/.ssh/authorized_keys"
fi

[ -n "$domain" ] || domain="$(grep -E '^PGWEB_DOMAIN=' "$env_file" | tail -n 1 | cut -d= -f2-)"
host_key="$(cut -d' ' -f1-2 /etc/ssh/ssh_host_ed25519_key.pub 2> /dev/null \
  || echo '<нет ключа ed25519 сервера: ssh-keyscan -t ed25519 IP>')"
ip="$(hostname -I | awk '{print $1}')"
log "Готово"
cat <<EOF
Дальше (подробно — deploy/README.md):
  1. Сохраните строку PGWEB_MASTER_KEYS из $env_file в менеджер паролей.
  2. Первый запуск от пользователя $DEPLOY_USER:
       sudo -iu $DEPLOY_USER
       bash $APP_DIR/deploy/deploy.sh
  3. Администратор (пароль вводится скрыто):
       cd $APP_DIR/deploy
       docker compose run --rm cli bootstrap-admin --email ВАШ_EMAIL

Секреты GitHub Actions репозитория private-gateway-web (Settings → Secrets and variables → Actions):
  DEPLOY_HOST          $ip
  DEPLOY_USER          $DEPLOY_USER
  DEPLOY_KNOWN_HOSTS   $ip${domain:+,$domain} $host_key
  DEPLOY_SSH_KEY       секретная часть ключа, публичную часть передайте сюда через --ci-key
EOF
