"""Устройства участника: входы на сайт (сеансы) и приложения Private Gateway (токены устройств).

Сайт — источник решения о доступе для приложения: клиент входит аккаунтом сайта (пароль и 2FA),
получает токен устройства и регулярно проверяет его здесь. Отзыв устройства, блокировка участника
или смена пароля (auth_version) гасят токен при следующей проверке. VPN-сервер здесь не
затрагивается: подписки и профили подключения по-прежнему выдает Private Gateway.
"""

import re
from datetime import datetime, timedelta

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.cookies import cookie_name
from app.core.errors import AppError
from app.core.net import device_label, mask_ip
from app.core.security import passwords, tokens
from app.db.models import AppDevice, User, UserSession, utcnow
from app.services import auth, limits

APP_PLATFORMS = ("windows", "macos", "linux", "android", "ios")
BEARER = re.compile(r"Bearer ([A-Za-z0-9_-]{32,128})")


def device_limit_for(user: User) -> int:
    return user.device_limit or get_settings().device_limit


def session_active(now: datetime):
    return (
        UserSession.revoked_at.is_(None),
        UserSession.expires_at > now,
        UserSession.last_seen_at > now - timedelta(days=get_settings().session_idle_days),
    )


def _device_active(user: User, now: datetime):
    return (
        AppDevice.user_id == user.id,
        AppDevice.revoked_at.is_(None),
        AppDevice.expires_at > now,
        AppDevice.auth_version == user.auth_version,
    )


def _session_out(row: UserSession, current_hash: str | None) -> dict:
    return {
        "id": row.id,
        "label": device_label(row.user_agent),
        "ip_masked": row.ip_masked,
        "created_at": row.created_at,
        "last_seen_at": row.last_seen_at,
        "current": current_hash is not None and row.id_hash == current_hash,
    }


def _device_out(row: AppDevice) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "platform": row.platform,
        "app_version": row.app_version,
        "ip_masked": row.ip_masked,
        "created_at": row.created_at,
        "last_seen_at": row.last_seen_at,
    }


async def overview(db: AsyncSession, user: User, request: Request | None = None) -> dict:
    now = utcnow()
    current = None
    if request is not None:
        cookie = request.cookies.get(cookie_name("session"), "")
        current = tokens.hash_token(cookie) if cookie else None
    sessions = (
        await db.scalars(
            select(UserSession)
            .where(
                UserSession.user_id == user.id,
                UserSession.auth_version == user.auth_version,
                *session_active(now),
            )
            .order_by(UserSession.last_seen_at.desc())
        )
    ).all()
    apps = (
        await db.scalars(
            select(AppDevice)
            .where(*_device_active(user, now))
            .order_by(AppDevice.last_seen_at.desc())
        )
    ).all()
    return {
        "sessions": [_session_out(row, current) for row in sessions],
        "devices": [_device_out(row) for row in apps],
        "session_limit": get_settings().session_limit,
        "device_limit": device_limit_for(user),
    }


async def _lock_user(db: AsyncSession, user_id: int) -> None:
    # Порядок блокировок как у входа и отзыва доступа: сначала участник, потом его сеансы и
    # устройства. Иначе запись в журнал (ссылка на users) и отзыв доступа ждут друг друга.
    await db.execute(select(User.id).where(User.id == user_id).with_for_update())


async def revoke_session(db: AsyncSession, user: User, session_id: int, actor_id: int) -> None:
    await _lock_user(db, user.id)
    row = await db.scalar(
        select(UserSession)
        .where(UserSession.id == session_id, UserSession.user_id == user.id)
        .with_for_update()
    )
    if not row or row.revoked_at is not None:
        raise AppError(404, "not_found")
    await auth.end_sessions(db, [row.id])
    auth.audit(db, "session.revoked", actor_id, user.id)
    await db.commit()


async def revoke_device(db: AsyncSession, user: User, device_id: int, actor_id: int) -> None:
    await _lock_user(db, user.id)
    row = await db.scalar(
        select(AppDevice)
        .where(AppDevice.id == device_id, AppDevice.user_id == user.id)
        .with_for_update()
    )
    if not row or row.revoked_at is not None:
        raise AppError(404, "not_found")
    row.revoked_at = utcnow()
    auth.audit(db, "app_device.revoked", actor_id, user.id)
    await db.commit()


# --- Приложение: вход по аккаунту сайта, токен устройства, проверка доступа ---


async def app_login(db: AsyncSession, request: Request, body) -> dict:
    ip = auth.client_ip(request)
    identity = body.email.strip().lower()
    await limits.attempt("login-ip", ip)
    await limits.attempt("login-user", identity + ":" + ip)
    row = (
        await db.execute(select(User.id, User.password_hash).where(User.email == identity))
    ).one_or_none()
    await db.rollback()
    stored_hash = row.password_hash if row else None
    if not await passwords.verify_password_async(stored_hash, body.password) or not row:
        raise AppError(401, "invalid_credentials")
    user = await db.scalar(select(User).where(User.id == row.id).with_for_update())
    if not user or user.status != "active" or user.password_hash != stored_hash:
        raise AppError(401, "invalid_credentials")
    # Пароль верный: дальнейшие отказы (нет 2FA, лимит устройств) не должны копить попытки,
    # общие с входом на сайт, — там участник освобождает место
    await limits.clear("login-user", identity + ":" + ip)
    await limits.clear("login-ip", ip)
    # Вход в приложение — только для аккаунта с настроенной 2FA (настраивается на сайте)
    if not user.totp_enabled:
        raise AppError(403, "setup_required")
    await limits.attempt("factor-user", str(user.id))
    await auth.consume_factor(db, user, body.code, body.recovery_code)
    await limits.clear("factor-user", str(user.id))
    now = utcnow()
    device = body.device
    # Повторный вход с того же устройства заменяет его токен, поэтому место он не занимает
    others = await db.scalar(
        select(func.count())
        .select_from(AppDevice)
        .where(*_device_active(user, now), AppDevice.device_uid != device.uid)
    )
    if others >= device_limit_for(user):
        # Код 2FA уже израсходован: фиксируем это, иначе тот же код сработал бы повторно
        auth.audit(db, "app.device_limit", user.id, user.id)
        await db.commit()
        raise AppError(409, "device_limit")
    existing = await db.scalar(
        select(AppDevice)
        .where(
            AppDevice.user_id == user.id,
            AppDevice.device_uid == device.uid,
            AppDevice.revoked_at.is_(None),
        )
        .with_for_update()
    )
    if existing is not None:
        # Прежний токен этого устройства перестает действовать
        existing.revoked_at = now
        await db.flush()
    value = tokens.new_token()
    record = AppDevice(
        user_id=user.id,
        device_uid=device.uid,
        name=device.name,
        platform=device.platform,
        app_version=device.app_version,
        token_hash=tokens.hash_token(value),
        auth_version=user.auth_version,
        ip_masked=mask_ip(ip),
        last_seen_at=now,
        expires_at=now + timedelta(days=get_settings().app_token_days),
    )
    db.add(record)
    auth.audit(db, "app.login", user.id, user.id)
    await db.commit()
    return {
        "token": value,
        "expires_at": record.expires_at,
        "user": {"email": user.email, "display_name": user.display_name},
        "device": _device_out(record),
    }


def _bearer(request: Request) -> str:
    # Только заголовок Authorization: cookie сайта приложению доступа не дают
    match = BEARER.fullmatch(request.headers.get("authorization", ""))
    if not match:
        raise AppError(401, "unauthorized")
    return tokens.hash_token(match.group(1))


async def _app_device(
    db: AsyncSession, token_hash: str, *, lock: bool = True
) -> tuple[AppDevice, User]:
    now = utcnow()
    query = (
        select(AppDevice, User)
        .join(User, User.id == AppDevice.user_id)
        .where(
            AppDevice.token_hash == token_hash,
            AppDevice.revoked_at.is_(None),
            AppDevice.expires_at > now,
            AppDevice.auth_version == User.auth_version,
            User.status == "active",
            User.totp_enabled.is_(True),
        )
    )
    pair = (await db.execute(query.with_for_update(of=AppDevice) if lock else query)).one_or_none()
    if not pair:
        raise AppError(401, "unauthorized")
    return pair[0], pair[1]


async def app_status(db: AsyncSession, request: Request) -> dict:
    device, user = await _app_device(db, _bearer(request))
    now = utcnow()
    device.last_seen_at = now
    device.ip_masked = mask_ip(auth.client_ip(request))
    device.expires_at = now + timedelta(days=get_settings().app_token_days)
    expires_at = device.expires_at
    out = _device_out(device)
    await db.commit()
    return {
        "status": "ok",
        "expires_at": expires_at,
        "user": {"email": user.email, "display_name": user.display_name},
        "device": out,
    }


async def app_logout(db: AsyncSession, request: Request) -> None:
    token_hash = _bearer(request)
    _, owner = await _app_device(db, token_hash, lock=False)
    await _lock_user(db, owner.id)
    device, user = await _app_device(db, token_hash)
    device.revoked_at = utcnow()
    auth.audit(db, "app.logout", user.id, user.id)
    await db.commit()
