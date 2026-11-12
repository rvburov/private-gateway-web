# Реестр источников

Записи добавляются до переноса. Пользователь владеет тремя исходными репозиториями и явно
поручил использовать их решения в Private Gateway Web. В корне исходных репозиториев открытая
лицензия не найдена: перенос выполняется по этому поручению, без заявления об открытой лицензии
всего исходного проекта. Лицензии сторонних компонентов и ресурсов сохраняются отдельно.

| Источник | Commit | Использование |
| --- | --- | --- |
| [Private Gateway Client, AGENTS.md](https://github.com/rvburov/private-gateway-client/blob/cff4c9cb4c3bda2841eb1cafdf8d28fd4cfd5ea5/AGENTS.md) | `cff4c9cb4c3bda2841eb1cafdf8d28fd4cfd5ea5` | Процесс, учет решений и источников, Git, секреты и проверки; адаптация в корневом AGENTS.md. |
| [AI Agent Capper](https://github.com/rvburov/ai_agent_capper/tree/c38adcab3e136a80f6f85a796008661431f3acfa) | `c38adcab3e136a80f6f85a796008661431f3acfa` | Детали переноса backend, frontend и инфраструктуры, включая деплой и бэкапы рабочего сервера, — в соседних файлах `*-reuse.md`. |
| [Private Gateway Client, HTML](https://github.com/rvburov/private-gateway-client/tree/536b70e848ce02f3fe1fa2a08db2542e2761aac2/docs/design/html) | `536b70e848ce02f3fe1fa2a08db2542e2761aac2` | Согласованный интерактивный эталон клиента; история адаптаций в `../REFERENCE-REVIEW.md`. |
| [Private Gateway](https://github.com/rvburov/private-gateway/tree/8d73025eae365e426e0d2080d9f81f15ec267b10) | `8d73025eae365e426e0d2080d9f81f15ec267b10` | Знак и палитра уже согласованного макета; сетевой и серверный код не переносится. |
| [Лицензия флагов](https://github.com/rvburov/private-gateway-client/blob/536b70e848ce02f3fe1fa2a08db2542e2761aac2/shared/countries/LICENSE-flags.txt) | `536b70e848ce02f3fe1fa2a08db2542e2761aac2` | Исходное MIT-уведомление рядом с изображениями флагов в макете и React-приложении. |

Согласованный макет, шрифты и значки уже имеют историю происхождения в
`../REFERENCE-REVIEW.md`. Файлы реальных пользователей и серверов не копируются.
