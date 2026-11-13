"""Очистка ненужных данных: что удаляется, что остается и когда (DECISIONS п. 11)."""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import tokens
from app.db.models import (
    AccessCode,
    AppDevice,
    AuditEvent,
    DownloadEvent,
    LoginChallenge,
    RateLimit,
    TrustedDevice,
    User,
    UserSession,
)
from app.services import retention

NOW = datetime(2026, 11, 13, 3, 30, tzinfo=UTC)


def days(value: float) -> datetime:
    return NOW - timedelta(days=value)


def session(user_id: int, **values) -> UserSession:
    base = dict(
        user_id=user_id,
        id_hash=tokens.hash_token(tokens.new_token()),
        auth_version=1,
        created_at=days(1),
        last_seen_at=days(1),
        expires_at=NOW + timedelta(days=20),
    )
    return UserSession(**(base | values))


def app_device(user_id: int, uid: str, **values) -> AppDevice:
    base = dict(
        user_id=user_id,
        device_uid=uid,
        name="Laptop",
        platform="linux",
        app_version="0.2.0",
        token_hash=tokens.hash_token(tokens.new_token()),
        auth_version=1,
        created_at=days(1),
        last_seen_at=days(1),
        expires_at=NOW + timedelta(days=20),
        new_device=True,
    )
    return AppDevice(**(base | values))


def access(kind: str, email: str, **values) -> AccessCode:
    base = dict(
        kind=kind,
        email=email,
        code_hash=tokens.hash_token(tokens.new_token()),
        created_at=days(40),
        expires_at=NOW + timedelta(days=1),
    )
    return AccessCode(**(base | values))


async def names(db, model, column) -> set:
    return set((await db.scalars(select(column))).all())


async def test_purge_removes_only_records_that_are_no_longer_needed(db):
    user = User(email="member@example.test", display_name="Member", password_hash="x")
    db.add(user)
    await db.flush()
    uid = user.id
    db.add_all(
        [
            session(uid, ip_masked="keep-active"),
            session(uid, ip_masked="keep-revoked-recently", revoked_at=days(29)),
            session(uid, ip_masked="drop-revoked", revoked_at=days(31)),
            session(uid, ip_masked="drop-expired", expires_at=days(31)),
            session(uid, ip_masked="drop-abandoned", last_seen_at=days(14 + 31)),
            session(uid, ip_masked="keep-idle", last_seen_at=days(14 + 29)),
        ]
    )
    db.add_all(
        [
            TrustedDevice(
                user_id=uid,
                token_hash="t-keep",
                auth_version=1,
                expires_at=NOW + timedelta(days=1),
            ),
            TrustedDevice(user_id=uid, token_hash="t-drop", auth_version=1, expires_at=days(31)),
            TrustedDevice(
                user_id=uid,
                token_hash="t-drop-revoked",
                auth_version=1,
                expires_at=NOW + timedelta(days=1),
                revoked_at=days(31),
            ),
        ]
    )
    db.add_all(
        [
            LoginChallenge(
                user_id=uid,
                token_hash="c-keep",
                auth_version=1,
                expires_at=NOW + timedelta(minutes=5),
            ),
            LoginChallenge(
                user_id=uid,
                token_hash="c-expired",
                auth_version=1,
                expires_at=NOW - timedelta(seconds=1),
            ),
            LoginChallenge(
                user_id=uid,
                token_hash="c-consumed",
                auth_version=1,
                expires_at=NOW + timedelta(minutes=5),
                consumed_at=NOW - timedelta(minutes=1),
            ),
        ]
    )
    db.add_all(
        [
            RateLimit(key="r-keep", count=1, expires_at=NOW + timedelta(minutes=1)),
            RateLimit(key="r-drop", count=1, expires_at=NOW - timedelta(minutes=1)),
        ]
    )
    db.add_all(
        [
            access("invite", "keep-active@example.test"),
            access("invite", "keep-used-recently@example.test", used_at=days(29)),
            access("invite", "drop-used@example.test", used_at=days(31)),
            access("invite", "drop-revoked@example.test", revoked_at=days(31)),
            access("invite", "drop-expired@example.test", expires_at=days(31)),
            access("invite", "keep-expired-recently@example.test", expires_at=days(29)),
            access("password_reset", "drop-reset@example.test", user_id=uid, used_at=days(31)),
        ]
    )
    db.add_all(
        [
            app_device(uid, "keep-active"),
            # Отозвано давно, но создано в окне смены устройств: нужно лимиту
            app_device(uid, "keep-in-window", created_at=days(29), revoked_at=days(29)),
            app_device(uid, "keep-revoked-recently", created_at=days(60), revoked_at=days(29)),
            app_device(uid, "drop-revoked", created_at=days(60), revoked_at=days(31)),
            app_device(uid, "drop-expired", created_at=days(90), expires_at=days(31)),
        ]
    )
    db.add_all(
        [
            AuditEvent(action="keep", at=days(179)),
            AuditEvent(action="drop", at=days(181)),
            DownloadEvent(platform="linux", version="1.0.0", filename="keep", at=days(364)),
            DownloadEvent(platform="linux", version="1.0.0", filename="drop", at=days(366)),
        ]
    )
    await db.commit()

    counts = await retention.purge(db, NOW)

    assert counts == {
        "login_challenges": 2,
        "rate_limits": 1,
        "trusted_devices": 2,
        "sessions": 3,
        "access_codes": 4,
        "app_devices": 2,
        "audit_events": 1,
        "download_events": 1,
    }
    db.expire_all()
    assert await names(db, UserSession, UserSession.ip_masked) == {
        "keep-active",
        "keep-revoked-recently",
        "keep-idle",
    }
    assert await names(db, TrustedDevice, TrustedDevice.token_hash) == {"t-keep"}
    assert await names(db, LoginChallenge, LoginChallenge.token_hash) == {"c-keep"}
    assert await names(db, RateLimit, RateLimit.key) == {"r-keep"}
    assert await names(db, AccessCode, AccessCode.email) == {
        "keep-active@example.test",
        "keep-used-recently@example.test",
        "keep-expired-recently@example.test",
    }
    assert await names(db, AppDevice, AppDevice.device_uid) == {
        "keep-active",
        "keep-in-window",
        "keep-revoked-recently",
    }
    assert await names(db, AuditEvent, AuditEvent.action) == {"keep"}
    assert await names(db, DownloadEvent, DownloadEvent.filename) == {"keep"}
    assert await db.get(User, uid) is not None
    # Повторный запуск ничего не находит
    assert set((await retention.purge(db, NOW)).values()) == {0}


async def test_purge_periods_are_configurable(db, monkeypatch):
    monkeypatch.setenv("PGWEB_PURGE_AFTER_DAYS", "7")
    monkeypatch.setenv("PGWEB_AUDIT_DAYS", "30")
    monkeypatch.setenv("PGWEB_DOWNLOAD_LOG_DAYS", "30")
    get_settings.cache_clear()
    user = User(email="member@example.test", display_name="Member", password_hash="x")
    db.add(user)
    await db.flush()
    db.add_all(
        [
            access("invite", "drop@example.test", used_at=days(8)),
            access("invite", "keep@example.test", used_at=days(6)),
            AuditEvent(action="drop", at=days(31)),
            DownloadEvent(platform="linux", version="1.0.0", filename="drop", at=days(31)),
            # Закончилось 10 дней назад (> 7), но создано в 30-дневном окне смены устройств
            app_device(user.id, "keep-in-window", created_at=days(20), revoked_at=days(10)),
            app_device(user.id, "drop-old", created_at=days(31), revoked_at=days(10)),
        ]
    )
    await db.commit()
    counts = await retention.purge(db, NOW)
    assert (counts["access_codes"], counts["audit_events"], counts["download_events"]) == (1, 1, 1)
    assert await names(db, AppDevice, AppDevice.device_uid) == {"keep-in-window"}


async def test_purge_skips_while_another_copy_runs(db_factory):
    async with db_factory() as holder, db_factory() as other:
        await holder.execute(select(1))
        from sqlalchemy import text

        await holder.execute(text(f"SELECT pg_advisory_xact_lock({retention.PURGE_LOCK})"))
        assert await retention.purge(other, NOW) == {}
        await holder.rollback()
        assert await retention.purge(other, NOW) != {}


def test_daily_time_is_next_occurrence_in_utc():
    morning = datetime(2026, 11, 13, 1, 0, tzinfo=UTC)
    assert retention.seconds_until("03:30", morning) == 2.5 * 3600
    evening = datetime(2026, 11, 13, 3, 30, tzinfo=UTC)
    assert retention.seconds_until("03:30", evening) == 24 * 3600
    assert retention.seconds_until("00:00", datetime(2026, 11, 13, 23, 59, tzinfo=UTC)) == 60


async def test_api_process_runs_and_stops_the_daily_purge(db_factory, monkeypatch):
    from app.main import create_app

    started = asyncio.Event()
    stopped = asyncio.Event()

    async def fake_daily():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr(retention, "run_daily", fake_daily)
    application = create_app()
    async with application.router.lifespan_context(application):
        await asyncio.wait_for(started.wait(), timeout=2)
        assert not stopped.is_set()
    assert stopped.is_set()
    monkeypatch.setenv("PGWEB_PURGE_TIME", "off")
    get_settings.cache_clear()
    started.clear()
    async with application.router.lifespan_context(application):
        await asyncio.sleep(0.05)
    assert not started.is_set()
