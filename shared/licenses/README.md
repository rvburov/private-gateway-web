# Сторонние компоненты

`components.json` и `texts/` создаются командой `python3 scripts/generate-licenses.py`
после установки зависимостей из lock-файлов в `backend/.venv` и `frontend/node_modules`.
В реестре — название, версия, авторство, исходник, данные о лицензии и пути к оригинальным
текстам лицензий. Он включает установленные транзитивные и инструменты разработки.
Платформенные optional-пакеты других ОС остаются перечислены в npm lock-файле.

Ресурсы согласованного дизайна сохраняют лицензии рядом с файлами:

- Geologica и Golos Text: `frontend/public/assets/fonts/*LICENSE` (SIL OFL 1.1).
- Inter и JetBrains Mono: лицензии внутри `frontend/public/client/assets/fonts/`.
- Font Awesome Free 6.7.2: `frontend/public/assets/FONT-AWESOME-LICENSE.txt` (значки CC BY 4.0).
- Флаги стран: исходные сведения в `frontend/public/client/assets/countries/`.

Инфраструктура: PostgreSQL (PostgreSQL License), Caddy (Apache-2.0), Python (PSF-2.0),
Node.js (MIT и лицензии включенных компонентов). Их дистрибутивы и контейнеры сохраняют
собственные notices. Gitleaks 8.30.1 (MIT) используется только для проверки репозитория;
официальный архив сверяется с опубликованной SHA-256, в приложение он не входит.

Основание переноса собственного кода пользователя описано в
`docs/sources/REUSE_REGISTER.md`; проект не присваивает ему открытую лицензию.
