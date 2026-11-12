# Инфраструктура: источники переноса

Запись сделана до переноса файлов. Пользователь разрешил использовать собственные
репозитории AI Agent Capper и Private Gateway Client как основу Private Gateway Web.
Ни адреса рабочих серверов, ни секреты, ни учетные данные из них не используются.

## AI Agent Capper

Срез: `c38adcab3e136a80f6f85a796008661431f3acfa`.
Публичная лицензия всего репозитория в этом срезе не найдена; перенос выполняется
по прямому указанию владельца, без утверждения о свободной лицензии его кода.

| Задача | Проверенный исходник | Решение | Проверка |
| --- | --- | --- | --- |
| Образ API | [backend/Dockerfile](https://github.com/rvburov/ai_agent_capper/blob/c38adcab3e136a80f6f85a796008661431f3acfa/backend/Dockerfile) | Адаптировать этап установки закрепленных зависимостей и запуск от отдельного пользователя; Python 3.12, только API сайта | Сборка образа и проверка пользователя/health |
| Образ интерфейса | [frontend/Dockerfile](https://github.com/rvburov/ai_agent_capper/blob/c38adcab3e136a80f6f85a796008661431f3acfa/frontend/Dockerfile) | Сохранить сборку Vite в отдельном этапе и отдачу готовой статики через Caddy | npm ci, TypeScript, production build, Caddy validate |
| HTTP-маршруты | [deploy/Caddyfile](https://github.com/rvburov/ai_agent_capper/blob/c38adcab3e136a80f6f85a796008661431f3acfa/deploy/Caddyfile) | Адаптировать /api proxy, SPA fallback и заголовки; разрешить только собственный демонстрационный iframe | Валидация Caddy и HTTP smoke |
| Контейнеры | [deploy/docker-compose.yml](https://github.com/rvburov/ai_agent_capper/blob/c38adcab3e136a80f6f85a796008661431f3acfa/deploy/docker-compose.yml) | Убрать AI workers, Redis и удаленные интеграции; внутренний PostgreSQL, отдельная миграция, локальный loopback-порт | Compose config, healthchecks, миграция |
| Проверки CI | [.github/workflows/ci.yml](https://github.com/rvburov/ai_agent_capper/blob/c38adcab3e136a80f6f85a796008661431f3acfa/.github/workflows/ci.yml) | Сохранить отдельные проверки backend/frontend с PostgreSQL и lock-файлами; исключить публикацию | Те же локальные команды, YAML и запуск CI после отправки |
| Команды разработки | [deploy/local.sh](https://github.com/rvburov/ai_agent_capper/blob/c38adcab3e136a80f6f85a796008661431f3acfa/deploy/local.sh) | Написать небольшие bash-скрипты под новый состав, без настоящих аккаунтов и секретов в аргументах | bash -n и локальный запуск |

### Рабочий сервер (2026-11-12)

Тот же срез `c38adcab3e136a80f6f85a796008661431f3acfa`, перенос по указанию владельца:
сайт разворачивается на сервере capper тем же процессом. Адреса сервера, секреты и данные
capper не переносятся; ключи бэкапа `server-setup.sh` читает на самом сервере.

| Задача | Проверенный исходник | Решение | Проверка |
| --- | --- | --- | --- |
| Деплой | [deploy/deploy.sh](https://github.com/rvburov/ai_agent_capper/blob/c38adcab3e136a80f6f85a796008661431f3acfa/deploy/deploy.sh) | Сохранить шаги, теги `previous`, откат, проверку версии через вход, режим `--ssh`; убрать Redis и worker; добавить файл сайта для Caddy capper с проверкой его конфигурации | shellcheck; функции на локальном стенде Docker с имитацией Caddy capper; CI «Рабочий стек за общим входом» |
| Подготовка сервера | [deploy/server-setup.sh](https://github.com/rvburov/ai_agent_capper/blob/c38adcab3e136a80f6f85a796008661431f3acfa/deploy/server-setup.sh) | Только клон, `deploy/.env`, папка файлов сайтов и ключ CI с `command=...,restrict`; пакеты, пользователи и файрвол уже настроил capper | shellcheck; CI на Ubuntu 24.04, повторный запуск |
| Бэкапы | [deploy/backup/](https://github.com/rvburov/ai_agent_capper/blob/c38adcab3e136a80f6f85a796008661431f3acfa/deploy/backup) | Те же `pg_dump`, age, rclone, хранение и проверка восстановления; имена `pgweb-*`, папка `private-gateway-web`, сверка пользователей, приглашений, выпусков и журнала | Копия, `restore-check.sh` и полное восстановление на локальном стенде; CI |
| Workflow деплоя | [.github/workflows/deploy.yml](https://github.com/rvburov/ai_agent_capper/blob/c38adcab3e136a80f6f85a796008661431f3acfa/.github/workflows/deploy.yml) | Тот же запуск после зеленых проверок master и пропуск без секретов; имя проверок сайта | YAML; срабатывает только на master |
| Сервисы сервера | [deploy/docker-compose.yml](https://github.com/rvburov/ai_agent_capper/blob/c38adcab3e136a80f6f85a796008661431f3acfa/deploy/docker-compose.yml) | `restart`, логирование, сервис backup; без портов наружу, вход через внешнюю сеть `caddy-ingress` | `docker compose config`, запуск на стенде |

## Private Gateway Client

Правила bash, облачной рабочей копии, явных результатов тестов и хранения секретов
адаптированы из [AGENTS.md](https://github.com/rvburov/private-gateway-client/blob/536b70e848ce02f3fe1fa2a08db2542e2761aac2/AGENTS.md).
Команды .NET, службы, TUN, DNS и брандмауэра не применимы к веб-проекту и не переносятся.

## Граница

Агент готовит код и проверки. Сервер настраивает и первый запуск делает владелец по
`deploy/README.md`; рабочий VPN-сервер и данные capper не меняются.

## Закрепленные образы и проверка

Digest индексов проверены через Docker registry; они записаны непосредственно в
Dockerfile и Compose. Образ бэкапов: `golang:1.26-alpine` (сборка age v1.3.2),
`rclone/rclone:1.75` (rclone 1.75.2) и тот же `postgres:18-alpine`, что у базы. `python:3.12-slim-bookworm` дает Python 3.12.16,
`caddy:2.11-alpine` — Caddy 2.11.9, `postgres:18-alpine` — PostgreSQL 18.6.
Сборочный образ — `node:24-bookworm-slim`, тот же major, что в CI.
По сравнению с Capper (Python 3.13 / Node 22) выбран Python 3.12 по нижней границе
его backend и Node 24 для текущей среды; версии библиотек закреплены отдельно.

Оба образа собраны; миграция и все три healthcheck проходят. Выполнены пять HTTP
проверок `deploy/smoke.py` и десять браузерных случаев на ширинах 320–1440 px в EN/RU
через настоящий Caddy. Подтверждены UID 10001 и read-only API, запись в отдельном
operator CLI и единственный опубликованный порт `127.0.0.1:8080`.
Шесть неудачных входов с разными поддельными `X-Forwarded-For` дали пять ответов 401
и один 429: Caddy не дает обойти лимит сменой этого заголовка. Счетчики этой проверки
удалены только из созданной для проверки пустой базы, учетные записи не создавались.

В managed cloud Caddy получает дополнение к `NO_PROXY` для имен `api,postgres`,
чтобы внутренние обращения не уходили во внешний прокси. Остальные настройки
прокси сохранены. Проверка здоровья BusyBox `wget` отключает прокси только для
фиксированного loopback URL. Секрет CA применяется только во время сборки.
