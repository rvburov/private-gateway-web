# API Private Gateway Web

Все адреса относительные, JSON, один origin. Cookie отправляются с `credentials: include`.
Сначала `GET /api/auth/csrf` -> `{csrf_token}`; все POST/PATCH/DELETE требуют этот токен
в `X-CSRF-Token` и cookie. При 403 `csrf_failed` обновить токен и предложить повторить действие.
Ошибка: `{error: {code: string}}`. Ошибка валидации: HTTP 422 с тем же форматом (`validation_error`).
Пароль при создании/сбросе: 12–128 символов. Email нормализуется в нижний регистр.
Код 2FA: 6 цифр. Реальные секреты никогда не помещаются в URL или localStorage.

## Пользователь

`User = {id: number, email: string, display_name: string, role: 'admin'|'member',
status: 'active'|'blocked', totp_enabled: boolean, device_limit: number|null, created_at: ISO8601}`.
`GET /api/me` -> User; без завершенного входа HTTP 401.

Двухфакторная проверка — только у администратора (DECISIONS п. 11). Участник входит по email и
паролю, `totp_enabled` у него всегда `false`. Администратор без настроенной 2FA сеанса не
получает: после пароля — настройка приложения-аутентификатора (`totp_setup_required`).

## Вход и регистрация

- `POST /api/auth/login` `{email,password}` -> `{status:'ok'|'totp_required'|'totp_setup_required',user:User|null}`.
  Участник — сразу `ok` и сеанс. Администратор — `totp_required` (или `ok` с запомненного браузера)
  либо `totp_setup_required`, если 2FA еще нет.
- `POST /api/auth/2fa` `{code?:string,recovery_code?:string,remember_device:boolean}` -> тот же ответ. Ровно один код. Только администратор.
- `POST /api/auth/register` `{invite_code,email,display_name,password}` -> приглашение участника: `{status:'ok',user}` и сеанс;
  приглашение администратора: `totp_setup_required`. Приглашение одноразовое и привязано к email. Никакого выбора роли.
- `POST /api/auth/2fa/setup` `{}` -> `{secret,otpauth_uri,qr_svg}`. Только при незавершенном входе администратора, если 2FA еще нет. QR создан сервером, без сторонних URL.
- `POST /api/auth/2fa/setup/confirm` `{code}` -> `{status:'ok',user:User,recovery_codes:string[]}`. Коды показать один раз, затем переход в кабинет.
- `POST /api/auth/logout` `{}` -> 204; cookie и текущий сеанс отзываются.
- `POST /api/auth/reset` `{email,code,new_password}` -> `{status:'ok'}`. Код сброса дает администратор; 2FA администратора остается, все сеансы/доверенные браузеры/устройства приложения отзываются.

Незавершенный вход и готовый сеанс находятся только в HttpOnly cookie. `remember_device` пропускает
2FA администратора после верного пароля до 30 дней. Истекший шаг -> 401 `login_expired`, вернуться к паролю.
Шаг кода, открытый для участника (до перехода на вход по паролю), тоже отвечает `login_expired`.
Коды ошибок: `invalid_credentials`, `invalid_code`, `invalid_invite`, `invalid_reset`,
`rate_limited` (429 с Retry-After), `password_too_short`, `password_too_long`,
`account_exists`, `login_expired`, `setup_required`, `already_configured`,
`unauthorized`, `forbidden`, `csrf_failed`, `validation_error`, `busy`.

## Свой аккаунт

Оба действия завершают остальные входы на сайт, доверенные браузеры и все устройства приложения;
текущий браузер получает новый сеанс (новая cookie). Администратор передает `code` (TOTP), участник — нет.

- `POST /api/me/password` `{current_password,new_password,code?}` -> `{status:'ok'}`. Неверный текущий
  пароль -> 400 `invalid_password` (не 401: сеанс остается), не больше 5 попыток за 15 минут (429).
  Политика пароля как при регистрации. Невыполненные коды сброса участника отзываются.
- `POST /api/me/sign-out-everywhere` `{code?}` -> `{status:'ok'}`. Пароль не меняется.
- Администратор без `code` -> 400 `code_required`, неверный код -> 400 `invalid_code`.

## Администрирование

Только реальная роль admin. Списки: `{items: T[], total:number}`.

Все `/api/admin/*` требуют роль admin с настроенной 2FA (иначе 403 `forbidden` или `setup_required`).

- `GET /api/admin/members?q=&status=&limit=50&offset=0` -> User[]. Предел limit 100.
- `PATCH /api/admin/members/{id}` `{status?:'active'|'blocked',role?:'admin'|'member',code:string}` -> User. Текущий код TOTP администратора обязателен. Нельзя блокировать/понижать себя и последнего администратора. Блокировка и смена роли сразу отзывают все сеансы и устройства участника. Понижение до участника удаляет его 2FA (секрет, резервные коды, доверенные браузеры); назначенный администратор настраивает 2FA при следующем входе.
- `POST /api/admin/members/{id}/delete` `{code:string}` -> 204. Полное удаление: аккаунт, входы, доверенные браузеры, шаги входа, резервные коды, устройства приложения, коды сброса и приглашения на его email. Журнал скачиваний сохраняет записи с `user: null` («Удаленный участник»), журнал действий — событие `member.deleted` только с номерами. Себя -> 400 `self_change_forbidden`, последнего активного администратора -> 400 `last_admin`.
- `POST /api/admin/members/{id}/reset-code` `{code:string}` -> `{code:string,expires_at:ISO8601}`. Одноразовый код сброса показывается только в этом ответе.
- `GET /api/admin/invites?limit=50&offset=0` -> Invite[].
- `POST /api/admin/invites` `{email,role:'member'|'admin',expires_in_days:1..30,code:string}` -> `{invite:Invite,code:string}`. Текущий TOTP администратора обязателен. Одноразовый код приглашения показывается только в этом ответе.
- `POST /api/admin/invites/{id}/revoke` `{code:string}` -> Invite.
- `POST /api/admin/invites/{id}/delete` `{code:string}` -> 204. Любое состояние; действующее приглашение сразу перестает работать.

`Invite = {id:number,email:string,role:'admin'|'member',created_at:ISO8601,
expires_at:ISO8601,used_at:ISO8601|null,revoked_at:ISO8601|null}`.
Коды ошибок дополнительно: `not_found`, `self_change_forbidden`, `last_admin`, `no_changes`.
2FA при админ-действиях также одноразовая: следующий код через 30 секунд, повтор -> `invalid_code`.

## Скачивание

`GET /api/downloads` -> `{items: Download[]}` только после входа.
`Download = {platform:'windows'|'macos'|'ios'|'linux'|'android',available:boolean,
version:string|null,filename:string|null,size_bytes:number|null,sha256:string|null,
url:string|null}`. По умолчанию все unavailable, без выдуманных версий/ссылок.
Для опубликованного файла URL `/api/downloads/{platform}/file`, снова проверяющий сеанс и доступ.
Ответ: тип по расширению (`.apk` — `application/vnd.android.package-archive`, `.msi`, `.dmg`, `.deb`
— свои, иначе `application/octet-stream`), `Content-Disposition: attachment; filename="<ASCII>";
filename*=UTF-8''<имя>`, точный `Content-Length`, `X-Checksum-SHA256`, `Cache-Control: no-store`,
без сжатия. Cookie сеанса `SameSite=Lax`: обычный переход по ссылке на телефоне ее передает.
iOS только проверенная ссылка App Store, когда администратор внесет ее через CLI; до этого null.
Кнопки недоступных платформ отключены. Клиент сам не строит ссылки на GitHub Releases.

Каждое отданное скачивание записывается в журнал: участник, время, платформа, версия, имя файла,
IP без последних октетов (`/24` для IPv4, `/48` для IPv6) и User-Agent.
`GET /api/admin/downloads?user_id=&limit=&offset=` (только администратор) ->
`{items: DownloadEvent[], total:number}`, новые сверху.
`DownloadEvent = {id,at:ISO8601,platform,version,filename|null,ip_masked|null,device:string,
user:{id,email,display_name}|null}`; `device` — «браузер · ОС».

## Устройства

Входы на сайт ограничены `PGWEB_SESSION_LIMIT` (по умолчанию 3): новый вход сверх лимита
завершает самый давний сеанс участника. Устройства приложения ограничены `PGWEB_DEVICE_LIMIT`
(по умолчанию 3) или личным `device_limit` участника. Смена устройств: не больше
`PGWEB_DEVICE_CHANGES` (3) новых установок за `PGWEB_DEVICE_CHANGE_DAYS` (30) дней; если личный
лимит устройств больше — не больше его. Новая установка — `uid`, который в этом аккаунте еще
не входил; повторный вход того же `uid` (даже после удаления) не считается, удаленные
администратором устройства — тоже.

- `GET /api/me/devices` -> `Devices`; `POST /api/me/sessions/{id}/revoke`,
  `POST /api/me/devices/{id}/revoke` -> 204 (CSRF как у остальных изменений; чужие -> 404).
- `GET /api/admin/members/{id}/devices` -> `Devices`; `POST /api/admin/members/{id}/sessions/{sid}/revoke`,
  `POST /api/admin/members/{id}/devices/{did}/revoke` -> 204. Завершение входа защищает
  участника, поэтому без повторного кода 2FA.
- Завершенный вход (вручную или вытеснением сверх лимита) гасит и «запомненный» браузер,
  который к нему привязан: с него снова нужен код 2FA.
- `PATCH /api/admin/members/{id}` принимает `device_limit: 1..50 | null` (null — общий лимит);
  с кодом 2FA, сеансы участника не завершаются.

`Devices = {sessions: Session[], devices: AppDevice[], session_limit:number, device_limit:number,
device_changes:{used:number, limit:number, days:number}}`,
`Session = {id,label,ip_masked|null,created_at,last_seen_at,current:boolean}`,
`AppDevice = {id,name,platform,app_version,ip_masked|null,created_at,last_seen_at}`.

## Приложение Private Gateway

Вход в приложение — аккаунтом сайта. Маршруты `/api/app/*` не читают cookie сайта, поэтому
CSRF к ним не применяется; доступ — только по заголовку `Authorization: Bearer <токен>`.

- `POST /api/app/login` `{email,password,code?,recovery_code?,device:{uid,name,platform,app_version}}` ->
  `{token, expires_at, user:{email,display_name}, device: AppDevice}`. `uid` — постоянный
  идентификатор установки (`[A-Za-z0-9_-]{16,64}`), `platform` — `windows|macos|linux|android|ios`.
  `code` (6 цифр) и `recovery_code` необязательны, оба сразу — 422. **Участник**: присланный код
  не проверяется и не тратится (клиенты 0.2.0 присылают шесть цифр всегда). **Администратор**:
  без кода после верного пароля — 401 `code_required` (ничего не тратится), неверный — 400
  `invalid_code`, 2FA еще не настроена — 403 `setup_required`.
  Ошибки: `invalid_credentials` (401), `code_required` (401), `invalid_code` (400),
  `setup_required` (403), `device_limit` (409, все места заняты), `device_change_limit` (409,
  исчерпана смена устройств — освобождение места не поможет), `rate_limited` (429). Клиенты 0.2.0
  показывают на любой 409 текст о лимите устройств. Повторный вход того же `uid` выдает новый
  токен, прежний гаснет, место и смена не тратятся. При 409 предъявленный код 2FA администратора
  все равно израсходован. Отказы после верного пароля не копят попытки входа на сайт.
- `GET /api/app/status` -> `{status:'ok', expires_at, user, device}`; продлевает токен на
  `PGWEB_APP_TOKEN_DAYS` (30 дней). 401 — токен отозван, устройство удалено, участник
  заблокирован или сменил пароль: приложение выходит из аккаунта.
- `POST /api/app/logout` -> 204, устройство удаляется.

Токен хранится на сервере только хешем. Решение о доступе принимает сайт, а не приложение.

## Обновления программы

Выпуск клиента присылает workflow «Выпуск на сайт» (`deploy/import-release.sh`,
[deploy/README.md](../deploy/README.md), раздел 5). Сайт хранит манифест `update.json` байт в байт
и его подпись `update.json.sig`. Подпись (ECDSA P-256 над точными байтами манифеста) и SHA-256
файлов проверяет сама программа встроенным ключом: подделать обновление сайт не может, может
только не показать его.

- `GET /api/app/updates?platform=windows|macos|linux|android&channel=stable|beta`, заголовок
  `Authorization: Bearer <токен устройства>` (проверка как у `/api/app/status`, но токен не
  продлевается) -> `{releases: Release[]}`. `channel` по умолчанию `stable`. 401 `unauthorized` —
  токена нет или доступ устройства закончился; 422 `validation_error` — неверные `platform` или
  `channel` (ленты для iOS нет).
- `Release = {version, channel:'stable'|'beta', manifest:string, signature:string,
  files:{[kind]: {url:string, expires_at:ISO8601}}}`. `manifest` — base64 точных байт
  `update.json`, `signature` — текст `update.json.sig` без пробелов по краям. Не больше 5
  выпусков, новые версии сверху (порядок SemVer: `1.10.0` выше `1.9.0`): программа выбирает
  обновление и версию для отката. Канал `stable` — только стабильные выпуски, `beta` — и бета
  (сайт пока принимает только стабильные).
- `files` — только виды своей платформы, которые есть в манифесте и лежат на сайте: windows —
  `win-x64-msi`; linux — `linux-x64-deb`, `linux-x64-rpm`; macos — `osx-arm64-dmg`; android —
  `android-apk`. Выпуск без файлов своей платформы остается в списке с пустым `files`.
  Стоп-кран — доля раскатки 0 в текущем манифесте версии — держит и сайт: такой выпуск остается
  в списке (манифест и подпись нужны программе), но `files` у него всегда пустой. Манифест с
  долей больше 0 сайт принимает, только когда все файлы ленты из него уже на сайте; долю 0 — и
  без них, например после восстановления сервера, пока файлы не внесены заново. `url` —
  абсолютная ссылка `https://<домен>/api/app/updates/files/<билет>`, действует 30 минут
  (`expires_at`): перед загрузкой программа берет ленту заново.
- `GET /api/app/updates/files/{билет}` — без `Authorization`: билет сам дает право (служба
  десктопа токена не знает, ленту ей передает окно). Билет —
  `base64url(device_id|version|kind|sha256|exp).base64url(HMAC-SHA256)` секретом сайта
  `PGWEB_SECRET_KEY`; в базе не хранится и в пределах срока работает повторно. Ответ — файл как у
  `/api/downloads/{platform}/file`: тип по расширению (`.apk` —
  `application/vnd.android.package-archive`), `Content-Disposition` с именем файла из манифеста,
  точный `Content-Length`, `X-Checksum-SHA256`, `Cache-Control: no-store`, без сжатия. Каждая
  отдача — запись в журнал скачиваний (участник, платформа, версия, файл, сеть, User-Agent).
  Ошибки: 403 `invalid_ticket` — билет подделан или испорчен; 403 `ticket_expired` — срок вышел;
  403 `forbidden` — устройство удалено или вышло из аккаунта, участник заблокирован, удален или
  сменил пароль; 403 `rollout_stopped` — раскатка версии остановлена (в текущем манифесте доля
  0), в том числе для билета, выданного до остановки; новая доля больше 0 снова открывает файл
  по тем же билетам, пока не вышел их срок; 404 `not_found` — файла больше нет на сайте или в
  манифесте этой версии.

## Служебные адреса

`GET /api/health` -> `{status:'ok', version:'<коммит сборки>'}` (liveness; `dev` вне сборки `deploy.sh`), `GET /api/ready` проверяет БД -> 200 или 503.

## Хранение данных

Раз в сутки (`PGWEB_PURGE_TIME`, UTC, 03:30) API удаляет ненужные записи; вручную —
`python -m app.cli purge`. Шаги входа и счетчики попыток — сразу после истечения; закончившиеся
входы, доверенные браузеры, использованные/отозванные/истекшие приглашения и коды сброса — через
`PGWEB_PURGE_AFTER_DAYS` (30) дней; устройства приложения — так же, но не раньше окна смены
устройств; журнал действий — старше `PGWEB_AUDIT_DAYS` (180), журнал скачиваний — старше
`PGWEB_DOWNLOAD_LOG_DAYS` (365) дней.
