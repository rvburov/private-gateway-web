# Private Gateway Web API

Сервер сайта на Python 3.12+ и FastAPI. PostgreSQL хранит пользователей, приглашения,
сеансы, ограничения попыток и каталог выпусков. Сервер ничего не знает о VPN-профилях,
ссылках подключения и работающем VPN-сервере. Redis не нужен: фоновых очередей нет,
временное состояние и атомарные операции находятся в PostgreSQL.

## Запуск

Из корня `backend`, после настройки переменных окружения по `../.env.example`:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
.venv/bin/alembic upgrade head
.venv/bin/python -m app.cli bootstrap-admin --email owner@example.com
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Первый администратор создается только в пустой базе; пароль читается скрыто из терминала.
При первом входе он настраивает настоящий TOTP. В автоматизированном локальном запуске
допустим `--password-stdin`; пароль никогда не передается аргументом процесса.
Следующие учетные записи создаются по приглашению из админки.

`PGWEB_SECRET_KEY` — 32 случайных байта в hex для HMAC кодов. `PGWEB_MASTER_KEYS` —
`1:<64 hex-символа>` для AES-GCM. При ротации добавить `,2:<новый ключ>`, сохраняя старый
для чтения существующих секретов. Новые записи используют последний ключ. Нельзя удалять
старый ключ до отдельной миграции зашифрованных записей. Значений по умолчанию нет.
`PGWEB_COOKIE_SECURE=true` требует HTTPS в `PGWEB_PUBLIC_ORIGIN`; локальный HTTP явно
использует `false`. Не включать доверие произвольному X-Forwarded-For: в контейнерах
доверенным источником служит только Caddy в закрытой сети.

## Каталог выпусков

После установки каталог пуст и все пять платформ честно недоступны. Публиковать можно
только реально полученный и проверенный файл приложения:

```bash
.venv/bin/python -m app.cli publish-release --platform windows --version 1.2.3 --file /path/to/verified-installer.exe
.venv/bin/python -m app.cli disable-release --platform windows
.venv/bin/python -m app.cli prune
```

Версия и путь выше — пример команды, выпуск 1.2.3 этим проектом не объявляется. Файл
копируется под SHA-256 именем в `PGWEB_DOWNLOAD_ROOT`; размер и хеш вычисляются из его
байтов. Хранилище не раздается Caddy и не находится в публичной папке frontend.
Каждое скачивание повторно проверяет завершенный вход и активный доступ. После отзыва
доступа новые запросы недоступны. Уже переданные пользователю байты отозвать невозможно.
Для iOS команда `set-ios --version ... --url ...` принимает только HTTPS apps.apple.com
с идентификатором приложения; URL указывается после реальной публикации.

## Проверки

Нужна отдельная PostgreSQL база с `test` в имени. Тесты удаляют ее таблицы.
`PGWEB_TEST_DATABASE_URL` указывает только на эту базу; реальные ключи не нужны —
тестовые ключи создаются процессом.

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest -q
.venv/bin/alembic check
```

Основные зависимости и транзитивные версии закреплены по изученному
`ai_agent_capper` commit `c38adcab3e136a80f6f85a796008661431f3acfa` в lock-файлах с хешами.
Обновлять оба lock-файла вместе и выполнять проверки. Источники переноса:
[backend-reuse.md](../docs/sources/backend-reuse.md). Контракт:
[api-contract.md](../docs/api-contract.md).
