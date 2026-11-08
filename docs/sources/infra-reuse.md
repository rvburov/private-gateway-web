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

## Private Gateway Client

Правила bash, облачной рабочей копии, явных результатов тестов и хранения секретов
адаптированы из [AGENTS.md](https://github.com/rvburov/private-gateway-client/blob/536b70e848ce02f3fe1fa2a08db2542e2761aac2/AGENTS.md).
Команды .NET, службы, TUN, DNS и брандмауэра не применимы к веб-проекту и не переносятся.

## Граница этого этапа

Файлы Docker и Caddy — воспроизводимая локальная упаковка приложения. Публикация,
DNS, сертификаты публичного домена, рабочий VPN-сервер и production-данные не меняются.

## Закрепленные образы и проверка

Digest индексов проверены через Docker registry; они записаны непосредственно в
Dockerfile и Compose. `python:3.12-slim-bookworm` дает Python 3.12.16,
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
