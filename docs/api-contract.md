# API Private Gateway Web

Все адреса относительные, JSON, один origin. Cookie отправляются с `credentials: include`.
Сначала `GET /api/auth/csrf` -> `{csrf_token}`; все POST/PATCH/DELETE требуют этот токен
в `X-CSRF-Token` и cookie. При 403 `csrf_failed` обновить токен и предложить повторить действие.
Ошибка: `{error: {code: string}}`. Ошибка валидации: HTTP 422 с тем же форматом (`validation_error`).
Пароль при создании/сбросе: 12–128 символов. Email нормализуется в нижний регистр.
Код 2FA: 6 цифр. Реальные секреты никогда не помещаются в URL или localStorage.

## Пользователь

`User = {id: number, email: string, display_name: string, role: 'admin'|'member',
status: 'active'|'blocked', totp_enabled: boolean, created_at: ISO8601}`.
`GET /api/me` -> User; без завершенного входа HTTP 401.

## Вход и регистрация

- `POST /api/auth/login` `{email,password}` -> `{status:'ok'|'totp_required'|'totp_setup_required',user:User|null}`.
- `POST /api/auth/2fa` `{code?:string,recovery_code?:string,remember_device:boolean}` -> тот же ответ. Ровно один код.
- `POST /api/auth/register` `{invite_code,email,display_name,password}` -> status `totp_setup_required`. Приглашение одноразовое и привязано к email. Никакого выбора роли.
- `POST /api/auth/2fa/setup` `{}` -> `{secret,otpauth_uri,qr_svg}`. Только при незавершенном входе, если 2FA еще нет. QR создан сервером, без сторонних URL.
- `POST /api/auth/2fa/setup/confirm` `{code}` -> `{status:'ok',user:User,recovery_codes:string[]}`. Коды показать один раз, затем переход в кабинет.
- `POST /api/auth/logout` `{}` -> 204; cookie и текущий сеанс отзываются.
- `POST /api/auth/reset` `{email,code,new_password}` -> `{status:'ok'}`. Код сброса дает администратор; 2FA остается включенной, все сеансы/доверенные устройства отзываются.

Незавершенный вход и готовый сеанс находятся только в HttpOnly cookie. `remember_device` пропускает
2FA после верного пароля до 30 дней. Истекший шаг -> 401 `login_expired`, вернуться к паролю.
Коды ошибок: `invalid_credentials`, `invalid_code`, `invalid_invite`, `invalid_reset`,
`rate_limited` (429 с Retry-After), `password_too_short`, `password_too_long`,
`account_exists`, `login_expired`, `setup_required`, `already_configured`,
`unauthorized`, `forbidden`, `csrf_failed`, `validation_error`, `busy`.

## Администрирование

Только реальная роль admin. Списки: `{items: T[], total:number}`.

- `GET /api/admin/members?q=&status=&limit=50&offset=0` -> User[]. Предел limit 100.
- `PATCH /api/admin/members/{id}` `{status?:'active'|'blocked',role?:'admin'|'member',code:string}` -> User. Текущий код TOTP администратора обязателен. Нельзя блокировать/понижать себя и последнего администратора. Блокировка сразу отзывает все сеансы и устройства участника.
- `POST /api/admin/members/{id}/reset-code` `{code:string}` -> `{code:string,expires_at:ISO8601}`. Одноразовый код сброса показывается только в этом ответе.
- `GET /api/admin/invites?limit=50&offset=0` -> Invite[].
- `POST /api/admin/invites` `{email,role:'member'|'admin',expires_in_days:1..30,code:string}` -> `{invite:Invite,code:string}`. Текущий TOTP администратора обязателен. Одноразовый код приглашения показывается только в этом ответе.
- `POST /api/admin/invites/{id}/revoke` `{code:string}` -> Invite.

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
iOS только проверенная ссылка App Store, когда администратор внесет ее через CLI; до этого null.
Кнопки недоступных платформ отключены. Клиент сам не строит ссылки на GitHub Releases.

## Служебные адреса

`GET /api/health` -> `{status:'ok'}` (liveness), `GET /api/ready` проверяет БД -> 200 или 503.
