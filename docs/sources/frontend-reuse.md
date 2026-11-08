# Реестр переноса интерфейса Private Gateway Web

Запись сделана перед переносом в React. Согласованная пользователем редакция 8 остается в
`mockup/`; рабочий интерфейс находится в `frontend/`.

| Источник | Что переносим | Лицензия и решение | Проверка |
| --- | --- | --- | --- |
| Локальные `mockup/style.css`, `auth.css`, `account.css`, `app.js`, `client-preview.js`, `assets/` (согласованная редакция 8) | Тема, раскладка, геометрия SVG, шрифты и протокол сообщений встроенного клиента | Проект пользователя; разрешено текущей задачей. Оболочка реализуется компонентами React, код демонстрационной авторизации не переносится | Сборка, тесты API/маршрутов и измерение геометрии в браузере |
| [AI Agent Capper frontend](https://github.com/rvburov/ai_agent_capper/tree/c38adcab3e136a80f6f85a796008661431f3acfa/frontend) | Версии из package-lock.json, структура компонентов, поток шагов входа; отдельные переносы форм записаны в соседних реестрах | Репозиторий того же пользователя; отдельной открытой лицензии в корне не найдено. Перенос внутри его проектов прямо запрошен | typecheck, Vitest и браузерный сценарий |
| [Private Gateway Client docs/design/html](https://github.com/rvburov/private-gateway-client/tree/536b70e848ce02f3fe1fa2a08db2542e2761aac2/docs/design/html) | Оригинальные доски и ресурсы из уже адаптированного `mockup/client/`, без кода VPN | Репозиторий пользователя. Демонстрация обозначена как демонстрация; исходные лицензии шрифтов сохранены | Постоянный iframe, корректная платформа и язык, отсутствие переполнения |
| [Font Awesome Free 6.7.2](https://github.com/FortAwesome/Font-Awesome/tree/6.7.2/svgs/brands) | Windows/Apple/Linux/Android SVG из согласованного макета | CC-BY-4.0, исходные атрибуции и `FONT-AWESOME-LICENSE.txt` сохранены | Пять подписанных платформ |
| [Private Gateway Client shared/countries/LICENSE-flags.txt](https://github.com/rvburov/private-gateway-client/blob/536b70e848ce02f3fe1fa2a08db2542e2761aac2/shared/countries/LICENSE-flags.txt) | Лицензия оригинальных SVG-флагов countryflags в демонстрации | MIT, Panayiotis Lipiridis. Полный текст рядом с SVG: `frontend/public/client/assets/countries/LICENSE-flags.txt` | Побайтовое сравнение с источником |

Секреты, аккаунты и настройки действующих серверов не переносятся. Главная использует React,
а оригинальный клиент изолирован в отдельном iframe. Основные страницы не используют
вставку HTML-строк вместо компонентов.
