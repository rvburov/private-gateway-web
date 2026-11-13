"""Очистка данных, которые больше не нужны: сайт не хранит лишнего (DECISIONS п. 11).

Запускается раз в сутки внутри API (PGWEB_PURGE_TIME, UTC) и вручную командой
`python -m app.cli purge`. Время по умолчанию — после ночного бэкапа и проверки его
восстановления: проверка сверяет число записей копии и рабочей базы.

| Данные | Удаляются |
| --- | --- |
| Шаги входа, счетчики попыток | сразу после истечения |
| Входы на сайт, доверенные браузеры | через PGWEB_PURGE_AFTER_DAYS после конца |
| Приглашения и коды сброса | через PGWEB_PURGE_AFTER_DAYS после использования, отзыва, срока |
| Устройства приложения | через PGWEB_PURGE_AFTER_DAYS после конца, но не раньше окна смены |
| Журнал действий | старше PGWEB_AUDIT_DAYS |
| Журнал скачиваний | старше PGWEB_DOWNLOAD_LOG_DAYS |
"""

import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import (
    AccessCode,
    AppDevice,
    AuditEvent,
    DownloadEvent,
    LoginChallenge,
    RateLimit,
    RecoveryCode,
    TrustedDevice,
    User,
    UserSession,
    utcnow,
)
from app.db.session import get_session_factory

PURGE_LOCK = 74623020
log = logging.getLogger("pgweb")


async def purge(db: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    """Удаляет ненужные записи одной транзакцией; возвращает число удаленных по таблицам."""
    now = now or utcnow()
    settings = get_settings()
    # Вторая копия API не чистит одновременно: блокировка до конца транзакции
    if not await db.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": PURGE_LOCK}):
        await db.rollback()
        return {}
    ended = now - timedelta(days=settings.purge_after_days)
    idle = timedelta(days=settings.session_idle_days)
    statements = {
        "login_challenges": delete(LoginChallenge).where(
            or_(LoginChallenge.expires_at < now, LoginChallenge.consumed_at.is_not(None))
        ),
        "rate_limits": delete(RateLimit).where(RateLimit.expires_at < now),
        # Доверенные браузеры раньше входов: у них ссылка на вход
        "trusted_devices": delete(TrustedDevice).where(
            or_(TrustedDevice.revoked_at < ended, TrustedDevice.expires_at < ended)
        ),
        "sessions": delete(UserSession).where(
            or_(
                UserSession.revoked_at < ended,
                UserSession.expires_at < ended,
                UserSession.last_seen_at < ended - idle,
            )
        ),
        "access_codes": delete(AccessCode).where(
            or_(
                AccessCode.used_at < ended,
                AccessCode.revoked_at < ended,
                AccessCode.expires_at < ended,
            )
        ),
        # Записи из окна смены устройств нужны лимиту, даже отозванные
        "app_devices": delete(AppDevice).where(
            or_(AppDevice.revoked_at < ended, AppDevice.expires_at < ended),
            AppDevice.created_at < now - timedelta(days=settings.device_change_days),
        ),
        "audit_events": delete(AuditEvent).where(
            AuditEvent.at < now - timedelta(days=settings.audit_days)
        ),
        "download_events": delete(DownloadEvent).where(
            DownloadEvent.at < now - timedelta(days=settings.download_log_days)
        ),
    }
    counts = {}
    for name, statement in statements.items():
        result = await db.execute(statement.execution_options(synchronize_session=False))
        counts[name] = result.rowcount or 0
    await db.commit()
    # Обычно уже сделано при запуске API; здесь — если запуск не смог (база была недоступна)
    await clear_member_two_factor(db)
    return counts


async def clear_member_two_factor(db: AsyncSession) -> int:
    """Удаляет у участников данные 2FA (DECISIONS п. 11); возвращает число участников.

    Без выхода из аккаунта: auth_version не меняется. Повторный вызов ничего не делает.
    Идет при запуске API и в ежедневной очистке, а не в миграции: миграция применяется до
    перезапуска API, и прежний код, которому нужна 2FA участника, в это окно еще отвечает.
    """
    members = select(User.id).where(User.role == "member")
    await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id.in_(members)))
    await db.execute(delete(TrustedDevice).where(TrustedDevice.user_id.in_(members)))
    await db.execute(delete(LoginChallenge).where(LoginChallenge.user_id.in_(members)))
    result = await db.execute(
        update(User)
        .where(
            User.role == "member",
            or_(User.totp_enabled.is_(True), User.totp_secret_enc.is_not(None)),
        )
        .values(
            totp_enabled=False, totp_secret_enc=None, totp_key_version=None, totp_last_step=None
        )
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return result.rowcount or 0


async def startup() -> None:
    """Однократно при запуске API: 2FA участников. Ошибка не мешает API стартовать."""
    try:
        async with get_session_factory()() as db:
            cleared = await clear_member_two_factor(db)
        if cleared:
            log.info("member two-factor cleared: %s", cleared)
    except Exception:  # noqa: BLE001 — повторит ежедневная очистка
        log.exception("member two-factor cleanup failed")


def seconds_until(time_of_day: str, now: datetime) -> float:
    """Секунды до ближайшего HH:MM UTC; если время сегодня прошло — до завтрашнего."""
    hour, minute = (int(part) for part in time_of_day.split(":"))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def run_daily() -> None:
    """Фоновая задача API: очистка раз в сутки. Ошибка одного прогона не останавливает задачу."""
    while True:
        await asyncio.sleep(seconds_until(get_settings().purge_time, utcnow()))
        try:
            async with get_session_factory()() as db:
                counts = await purge(db)
            # Только числа: в журнал не попадают данные участников
            removed = ", ".join(f"{name}={count}" for name, count in counts.items() if count)
            log.info("purge: %s", removed or "nothing to remove")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            log.error("purge failed: %s", type(error).__name__)
