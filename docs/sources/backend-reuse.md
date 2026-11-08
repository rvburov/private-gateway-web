# Перенос серверной части

Источник: авторский репозиторий пользователя [AI Agent Capper](https://github.com/rvburov/ai_agent_capper),
срез `c38adcab3e136a80f6f85a796008661431f3acfa`. Перенос разрешен прямым заданием владельца;
отдельная открытая лицензия в корне источника не найдена. Секреты, БД, реальные учетные записи,
`.env` и настройки рабочего сервера не переносятся.

| Задача | Проверенный источник (относительно commit) | Решение | Проверка |
| --- | --- | --- | --- |
| Случайные cookie и HMAC одноразовых кодов | `backend/app/core/security/tokens.py` | Прямой перенос, CAP -> PG, имя настройки изменено | Одноразовость, нормализация, отсутствие открытых кодов в БД |
| TOTP и QR | `backend/app/core/security/totp.py` | Прямой перенос, issuer Private Gateway | RFC шаги, повтор кода, QR |
| AES-GCM для TOTP | `backend/app/core/security/crypto.py` | Прямой перенос, удалены поля AI | AAD и зашифрованный секрет |
| Argon2id | `backend/app/core/security/passwords.py` | Перенос профиля и ограниченного пула; без внешнего запроса HIBP | Проверка пароля, лимит параллельных хешей |
| Cookie | `backend/app/core/cookies.py` | Прямой перенос, имена PG и настройки | HttpOnly, Secure, SameSite, удаление |
| Атомарное потребление TOTP/backup | `backend/app/services/two_factor.py` | Перенос условных UPDATE | Конкурирующие запросы и replay |
| Вход/регистрация/админка | `backend/app/services/{auth,registration,access_codes,sessions,admin_users}.py`, `backend/app/api/routes/auth.py` | Адаптация контрактов и правил; убраны теннис/AI/бюджеты, Redis заменен транзакциями PostgreSQL | Полные HTTP сценарии и отзыв доступа |
| Схемы и модели | `backend/app/{schemas/auth.py,schemas/me.py,db/models/auth.py}` | Сокращены до функций сайта | Валидация, уникальность, миграция |

Все пути проверены в локальном клоне указанного среза; URL файла получается как
`https://github.com/rvburov/ai_agent_capper/blob/c38adcab3e136a80f6f85a796008661431f3acfa/<путь>`.
Новая логика хранения скачиваний написана для этого проекта. Redis не требуется:
временные шаги, ограничения попыток и сеансы хранятся в PostgreSQL, фоновых очередей нет.
