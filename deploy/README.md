# Рабочий сервер

Private Gateway Web работает на сервере AI Agent Capper (Hetzner, Хельсинки) по домену
`private-gateway.duckdns.org`. Процесс тот же, что у capper: push в `master` →
зеленые «Проверки приложения» → GitHub Actions заходит на сервер ключом, который может только
запустить `deploy.sh`, → копия базы, миграции, перезапуск, проверка здоровья, откат при сбое.
Решения — [docs/roadmap/DECISIONS.md](../docs/roadmap/DECISIONS.md), п. 8.

| Файл | Что делает |
|---|---|
| `compose.prod.yml` | Сервисы: postgres, api, web, backup; migrate и cli — разовые команды |
| `Caddyfile` | Caddy сайта: статика, `/api/*`, заголовки. Тот же файл, что локально |
| `.env.example` | Образец `deploy/.env` на сервере |
| `server-setup.sh` | Подготовка сервера capper под сайт, один раз от root |
| `deploy.sh` | Деплой: код, сборка, копия базы, миграции, перезапуск, общий вход, здоровье, откат |
| `backup/` | Образ бэкапов: `backup.sh`, `restore-check.sh`, `restore.sh`, расписание |
| `../.github/workflows/deploy.yml` | Деплой из GitHub Actions после успешных проверок master |

## Как устроено

```
Интернет ─ 443 ─▶ caddy AI Agent Capper ─┬─ ai-agent-capper.duckdns.org ─▶ capper
  (TLS, сертификат, HSTS)                 └─ private-gateway.duckdns.org
                                               │ сеть caddy-ingress
                                               ▼
                                   web (Caddy сайта) ─/api/*─▶ api ─▶ postgres
                                                                       ▲
                                                         backup ───────┘ ─▶ S3
```

- **Порты 80 и 443 одни на сервер**, их держит Caddy capper (его решение Р31). Сайт новых
  портов не открывает: `deploy.sh` кладет файл `private-gateway-web.caddy` в
  `/opt/ai_agent_capper/deploy/caddy-sites`, и Caddy capper передает запросы домена контейнеру
  `web` по внутренней сети `caddy-ingress`. Перед заменой файл проверяется вместе со всей
  конфигурацией Caddy capper в отдельном контейнере: ошибка в нем не может остановить capper.
- **IP посетителя.** Caddy capper ставит в `X-Forwarded-For` настоящий адрес. Caddy сайта верит
  этому заголовку только от подсети `caddy-ingress`, API — только от Caddy сайта. Без этого
  все посетители пришли бы с одного адреса, и лимит попыток входа закрыл бы вход всем.
- **Свое у сайта:** контейнеры, база PostgreSQL 18, секреты в `deploy/.env`, деплой, бэкапы
  (своя папка `private-gateway-web/` в том же бакете S3, тот же ключ age владельца). Деплой
  capper стек сайта не трогает; при перезапуске его Caddy сайт недоступен несколько секунд.
- API и Caddy сайта работают без root, файловая система только для чтения. PostgreSQL
  только во внутренней сети. После перезагрузки сервера все поднимается само
  (`restart: unless-stopped`).

Все команды `docker compose` ниже — от пользователя `deploy` из папки `deploy/`: тогда
`deploy/.env` подхватывается сам (в нем `COMPOSE_FILE=compose.prod.yml`).

```bash
sudo -iu deploy
cd /opt/private-gateway-web/deploy
```

## 1. Что должно быть до начала

- Сервер capper настроен его `server-setup.sh`: Docker, пользователь `deploy`, файрвол.
- Capper развернут с общим входом (коммит «Deploy: общий вход Caddy для других сайтов
  сервера»): есть сеть `docker network ls | grep caddy-ingress`.
- DNS: в DuckDNS у `private-gateway` тот же IP, что у домена capper. Проверка:
  `dig +short private-gateway.duckdns.org`. Без этой записи Caddy не получит сертификат.

## 2. Первичная настройка (один раз)

Отдельный ключ для деплоя из GitHub Actions — на своем компьютере, без пароля, только для
этого сайта:

```bash
ssh-keygen -t ed25519 -N "" -C "pgweb-deploy" -f pgweb-deploy
```

На сервере от root (после `--ci-key` — содержимое файла `pgweb-deploy.pub` в кавычках):

```bash
ssh <ваш_пользователь>@<IP сервера>
curl -fsSLO https://raw.githubusercontent.com/rvburov/private-gateway-web/master/deploy/server-setup.sh
sudo bash server-setup.sh --domain private-gateway.duckdns.org \
  --ci-key "ssh-ed25519 AAAA... pgweb-deploy"
```

Скрипт клонирует репозиторий в `/opt/private-gateway-web`, создает `deploy/.env` со
случайными паролем базы и ключами, берет настройки бэкапа (ключи age и S3) из
`/opt/ai_agent_capper/deploy/.env`, дает пользователю `deploy` право писать файл сайта для
общего входа и добавляет ключ CI с ограничением `command="... deploy.sh --ssh",restrict`.
Пакеты, пользователи, ssh и файрвол не меняются. В конце печатает значения для секретов
GitHub.

**Сохраните `PGWEB_MASTER_KEYS` из `/opt/private-gateway-web/deploy/.env` в менеджер
паролей.** Без этой строки копия базы не расшифрует 2FA администраторов.

## 3. Секреты GitHub

Репозиторий `private-gateway-web` → Settings → Secrets and variables → Actions:

| Секрет | Значение |
|---|---|
| `DEPLOY_HOST` | IP сервера (печатает `server-setup.sh`) |
| `DEPLOY_USER` | `deploy` |
| `DEPLOY_SSH_KEY` | содержимое файла `pgweb-deploy` (секретная часть) |
| `DEPLOY_KNOWN_HOSTS` | строка `<IP>,private-gateway.duckdns.org ssh-ed25519 AAAA...` из вывода `server-setup.sh` |

Пока секретов нет, workflow «Деплой» пишет «Сервер еще не настроен» и завершается успешно.

## 4. Первый запуск и администратор

```bash
sudo -iu deploy
bash /opt/private-gateway-web/deploy/deploy.sh
```

Первая сборка идет 5–10 минут. В конце `https://private-gateway.duckdns.org/api/health`
отвечает `ok` с версией коммита. Первый администратор (пароль вводится скрыто, в историю
команд не попадает):

```bash
cd /opt/private-gateway-web/deploy
docker compose run --rm cli bootstrap-admin --email ВАШ_EMAIL
```

Затем вход на сайте, настройка 2FA (она нужна только администраторам) и сохранение резервных
кодов. Готовых аккаунтов нет.

## 5. Файлы клиента

**Автоматически.** После выпуска клиента (тег `vX.Y.Z` в `private-gateway-client`, workflow
«Выпуск на GitHub») workflow «Выпуск на сайт» того репозитория скачивает файлы выпуска, сверяет
их с `SHA256SUMS` и отправляет на сервер: Windows — `.msi`, macOS — `.dmg`, Linux — `.deb`,
Android — `.apk`. Бета-выпуски (версия с `-`) на сайт не попадают. На сервере файл принимает
`import-release.sh`: отдельный ключ может только он, файл проверяется по размеру и SHA-256 и
вносится командой `publish-release`. Ссылки закрытого репозитория участникам не нужны: файл
лежит на сервере и выдается после входа.

**Лента обновлений программы.** Программа берет обновления с сайта: `GET /api/app/updates` по
токену устройства, файлы — по ссылкам-билетам на 30 минут ([API](../docs/api-contract.md)).
Вслед за установщиками workflow присылает `.rpm`, подпись `update.json.sig` и последним манифест
`update.json`. Команды ключа выпусков (файл — в stdin, размер и SHA-256 сверяются):

| Команда | Что делает |
|---|---|
| `import <платформа> <версия> <файл> <sha256>` | Установщик: хранилище и каталог «Скачать клиент» (`publish-release`) |
| `asset <версия> <файл> <sha256>` | Файл ленты (`.rpm`): только хранилище по SHA-256, в каталог не попадает (`store-file`) |
| `update-sig <версия> update.json.sig <sha256>` | Подпись манифеста: ждет `update` в `imports/` |
| `update <версия> update.json <sha256>` | Манифест в ленту (`publish-update`) |

`publish-update` принимает манифест, только если версия совпадает, канал `stable` и все файлы
ленты из него (`.msi`, `.deb`, `.rpm`, `.dmg`, `.apk`) уже лежат на сайте; иначе отказ, лента не
меняется. Подпись действует для одного следующего `update` той же версии и не дольше часа. Сайт
хранит манифест байт в байт: подпись и SHA-256 файлов проверяет программа, подделать обновление
сайт не может. Раскатка (`release-rollout.yml` клиента) повторяет `update-sig` и `update`: новая
доля заменяет манифест и подпись той же версии.

Настройка, один раз. **На компьютере** — ключ:

```bash
ssh-keygen -t ed25519 -C "pgweb-releases" -f pgweb-releases
```

**На сервере** — открытая часть ключа (свежий `server-setup.sh` из `master`):

```bash
sudo bash server-setup.sh --release-key "СТРОКА_ИЗ_pgweb-releases.pub"
```

**В GitHub** `private-gateway-client` → Settings → Secrets and variables → Actions: `WEBSITE_HOST`,
`WEBSITE_USER` (`deploy`), `WEBSITE_KNOWN_HOSTS` — те же значения, что `DEPLOY_*` этого
репозитория, `WEBSITE_SSH_KEY` — содержимое файла `pgweb-releases`. Проверка — Actions →
«Выпуск на сайт» → Run workflow с тегом последнего выпуска.

**Вручную.** Проверенный выпуск — в `/opt/private-gateway-web/deploy/imports` (файл должен читаться всеми:
`chmod 644`), затем:

```bash
docker compose run --rm cli publish-release --platform windows --version 1.2.3 --file /imports/ИМЯ_ФАЙЛА
docker compose run --rm cli set-ios --version 1.2.3 --url URL_APP_STORE
docker compose run --rm cli disable-release --platform android
docker compose run --rm cli store-file --file /imports/ИМЯ_ФАЙЛА.rpm
docker compose run --rm cli publish-update --version 1.2.3 --manifest /imports/update.json \
  --signature /imports/update.json.sig
```

Файлы лежат в томе `releases`, API выдает их только вошедшим участникам и устройствам по
билетам ленты. В бэкап базы файлы не входят: исходники выпусков храните у себя, на новом сервере
их вносят заново. Манифесты ленты — в базе и в бэкапе; пока файлы не внесены заново, у выпуска
в ленте нет файлов.

### Лимиты входов и устройств

В `deploy/.env` можно изменить `PGWEB_SESSION_LIMIT` (входов на сайт, по умолчанию 3),
`PGWEB_DEVICE_LIMIT` (устройств с приложением, по умолчанию 3), `PGWEB_APP_TOKEN_DAYS` (сколько
дней приложение работает без проверки, 30) и смену устройств: `PGWEB_DEVICE_CHANGES` новых
установок приложения за `PGWEB_DEVICE_CHANGE_DAYS` дней (3 за 30). Применяются после
`bash deploy.sh`. Личный лимит устройств участника меняется в его карточке на сайте.

### Очистка данных

API раз в сутки в `PGWEB_PURGE_TIME` (UTC, по умолчанию 03:30 — после бэкапа и проверки
восстановления) удаляет то, что больше не нужно: закончившиеся входы и доверенные браузеры,
использованные, отозванные и истекшие приглашения и коды сброса — через `PGWEB_PURGE_AFTER_DAYS`
дней (30), журнал действий старше `PGWEB_AUDIT_DAYS` (180), журнал скачиваний старше
`PGWEB_DOWNLOAD_LOG_DAYS` (365). Вручную — `docker compose run --rm cli purge`.

## 6. Бэкапы

| Что | Когда (UTC) | Где |
|---|---|---|
| `pg_dump -Fc`, зашифрованный age | каждую ночь в 01:45 | `deploy/backups/daily/` и S3 `private-gateway-web/daily/` |
| первая копия недели и месяца | вместе с ночной | `weekly/`, `monthly/` |
| копия перед деплоем и восстановлением | при `deploy.sh` и `restore.sh` | `manual/` |
| проверка восстановления | 1-го числа в 02:45 | временная база в контейнере backup |

Время сдвинуто на 15 минут от бэкапов capper. Хранится 7 ежедневных, 4 еженедельных,
6 ежемесячных и 5 ручных копий. Ключи и бакет — те же, что у capper: расшифровать копию
можно секретным ключом владельца из менеджера паролей.

```bash
docker compose ps backup                    # healthy — последние бэкап и проверка прошли
docker compose logs --tail=50 backup
docker compose exec backup backup.sh        # копия сейчас
docker compose exec backup restore-check.sh # проверка восстановления сейчас
docker compose exec backup restore.sh --list
```

Проверка восстановления сверяет с рабочей базой число пользователей, приглашений, выпусков
и событий журнала за 30 дней до копии. Восстановление стирает рабочую базу и заменяет ее
копией, перед этим снимается копия текущей базы в `manual/`:

```bash
docker compose stop api
docker compose exec backup restore.sh latest      # или daily/<файл>, или s3:monthly/<файл>
docker compose run --rm migrate
docker compose start api
```

Новый сервер после потери старого: настройка capper, затем разделы 1–3. В `deploy/.env` —
прежние `PGWEB_MASTER_KEYS` и `PGWEB_SECRET_KEY` из менеджера паролей. Затем:

```bash
docker compose up -d postgres backup
docker compose exec backup restore.sh s3:daily/<файл> --no-safety-copy
bash deploy.sh
```

## 7. Обновление и откат

**Автоматически:** после push в `master` и зеленых «Проверок приложения» workflow «Деплой»
запускает на сервере `deploy.sh` для этого коммита. Вручную — кнопка Run workflow или на
сервере `bash deploy.sh`.

**Откат.** Неудачный деплой (сборка, копия, миграции, запуск, здоровье) откатывается на
прежние образы сам: в выводе «откат выполнен: работает <хеш>». Вручную на прежний коммит
master — `bash deploy.sh --ref <хеш>`. Миграции назад не откатываются: новые миграции пишутся
так, чтобы прежний код работал на новой схеме; ошибку исправляет следующий коммит.
Если схему все же нужно вернуть — копия из `manual/`, которую снял этот деплой:

```bash
docker compose stop api
docker compose exec backup restore.sh manual/<файл>
bash deploy.sh --ref <прежний хеш>
```

## 8. Если что-то сломалось

| Признак | Что смотреть и делать |
|---|---|
| Сайт не открывается | `docker compose ps`: все ли `Up`/`healthy`; `docker compose logs --tail=100 web api`. Файл сайта: `cat /opt/ai_agent_capper/deploy/caddy-sites/private-gateway-web.caddy` |
| Ошибка сертификата | DNS указывает на сервер (`dig +short private-gateway.duckdns.org`). Логи Caddy capper: `cd /opt/ai_agent_capper/deploy && docker compose logs caddy` |
| `deploy.sh`: нет сети caddy-ingress | Capper еще не развернут с общим входом: задеплойте capper, затем снова `deploy.sh` |
| `deploy.sh`: файл сайта не принят Caddy | Прежний файл возвращен, capper не тронут. Причина — в выводе (`caddy validate`) |
| Деплой упал на миграции | Работает прежняя версия. Исправить миграцию новым коммитом |
| Деплой упал на проверке здоровья | `deploy.sh` печатает логи и откатывается. «Откат не помог» — раздел 7 |
| `backup` unhealthy | `docker compose logs backup`; после исправления — `docker compose exec backup backup.sh` |
| Все посетители получают 429 на входе | Подсеть `caddy-ingress` не совпала с доверенной: `docker network inspect caddy-ingress`, затем `bash deploy.sh` (подсеть берется заново) |
| Кончается диск | `df -h`, `docker system df`; `docker builder prune` и `docker image prune` |
| Потерян доступ администратора | Новый администратор только на пустой базе; иначе — восстановление из копии или команды `docker compose run --rm cli --help` |
