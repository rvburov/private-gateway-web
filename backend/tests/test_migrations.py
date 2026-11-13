"""Переход на «2FA только у администраторов» на данных прежней схемы (DECISIONS п. 11).

Миграция не трогает 2FA: пока не перезапущен API, прежний код ее требует. Данные 2FA
участников удаляет новый код при запуске (retention.clear_member_two_factor); вход на сайт
и токены приложения продолжают действовать, у администраторов ничего не меняется.
"""

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

import app
from app.core.security import tokens

# Каталог с alembic рядом с импортированным app: проверка мутантов подменяет обе копии
BACKEND = Path(app.__file__).resolve().parents[1]
PREVIOUS = "2135158254eb"


def alembic(*args: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        env=os.environ | {"PGWEB_DATABASE_URL": os.environ["PGWEB_TEST_DATABASE_URL"]},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr[-2000:]


async def reset_schema(engine) -> None:
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))


async def test_member_two_factor_is_cleared_by_new_code_without_signing_anyone_out(db_factory):
    engine = create_async_engine(os.environ["PGWEB_TEST_DATABASE_URL"])
    member_session, app_token = tokens.new_token(), tokens.new_token()
    now = datetime.now(UTC)
    try:
        await reset_schema(engine)
        alembic("upgrade", PREVIOUS)
        async with engine.begin() as connection:
            run = connection.execute
            await run(
                text(
                    "INSERT INTO users (id, email, display_name, password_hash, role, status,"
                    " totp_enabled, totp_secret_enc, totp_key_version, totp_last_step,"
                    " auth_version, created_at) VALUES"
                    " (1, 'admin@example.test', 'Admin', 'x', 'admin', 'active', true,"
                    "  'admin-secret', 1, 100, 3, :now),"
                    " (2, 'member@example.test', 'Member', 'x', 'member', 'active', true,"
                    "  'member-secret', 1, 100, 5, :now)"
                ),
                {"now": now},
            )
            await run(
                text(
                    "INSERT INTO recovery_codes (user_id, code_hash, created_at) VALUES"
                    " (1, 'admin-code', :now), (2, 'member-code', :now)"
                ),
                {"now": now},
            )
            await run(
                text(
                    "INSERT INTO sessions (id, id_hash, user_id, auth_version, created_at,"
                    " last_seen_at, expires_at) VALUES (10, :hash, 2, 5, :now, :now, :later)"
                ),
                {
                    "hash": tokens.hash_token(member_session),
                    "now": now,
                    "later": now + timedelta(days=20),
                },
            )
            await run(
                text(
                    "INSERT INTO trusted_devices (token_hash, user_id, auth_version, created_at,"
                    " expires_at, session_id) VALUES ('admin-browser', 1, 3, :now, :later, NULL),"
                    " ('member-browser', 2, 5, :now, :later, 10)"
                ),
                {"now": now, "later": now + timedelta(days=20)},
            )
            await run(
                text(
                    "INSERT INTO login_challenges (token_hash, user_id, auth_version, created_at,"
                    " expires_at) VALUES ('admin-step', 1, 3, :now, :later),"
                    " ('member-step', 2, 5, :now, :later)"
                ),
                {"now": now, "later": now + timedelta(minutes=5)},
            )
            # Установка A вошла дважды (повторный вход), B — один раз
            await run(
                text(
                    "INSERT INTO app_devices (id, user_id, device_uid, name, platform, app_version,"
                    " token_hash, auth_version, created_at, last_seen_at, expires_at, revoked_at)"
                    " VALUES"
                    " (20, 2, 'install-aaaaaaaaaaaaaaaa', 'A', 'linux', '0.2.0', 'old', 5,"
                    "  :earlier, :earlier, :later, :now),"
                    " (21, 2, 'install-aaaaaaaaaaaaaaaa', 'A', 'linux', '0.2.0', :token, 5,"
                    "  :now, :now, :later, NULL),"
                    " (22, 2, 'install-bbbbbbbbbbbbbbbb', 'B', 'android', '0.2.0', 'b', 5,"
                    "  :now, :now, :later, NULL)"
                ),
                {
                    "token": tokens.hash_token(app_token),
                    "now": now,
                    "earlier": now - timedelta(days=2),
                    "later": now + timedelta(days=20),
                },
            )

        alembic("upgrade", "head")

        # Сразу после миграции прежний код еще отвечает: 2FA участника должна быть на месте
        async with engine.connect() as connection:
            kept = (
                await connection.execute(text("SELECT totp_enabled FROM users WHERE id = 2"))
            ).scalar_one()
            assert kept is True
            codes = await connection.execute(
                text("SELECT count(*) FROM recovery_codes WHERE user_id = 2")
            )
            assert codes.scalar_one() == 1

        from app.services import retention

        await retention.startup()

        async with engine.connect() as connection:
            fetch = connection.execute
            users = (
                await fetch(
                    text(
                        "SELECT id, totp_enabled, totp_secret_enc IS NULL, totp_last_step,"
                        " auth_version FROM users ORDER BY id"
                    )
                )
            ).all()
            assert users == [(1, True, False, 100, 3), (2, False, True, None, 5)]
            for table in ("recovery_codes", "trusted_devices", "login_challenges"):
                owners = (await fetch(text(f"SELECT user_id FROM {table}"))).scalars().all()
                assert owners == [1], table
            assert (
                await fetch(text("SELECT revoked_at FROM sessions WHERE id = 10"))
            ).scalar_one() is None
            flags = (
                await fetch(
                    text("SELECT id, new_device, removed_by_admin FROM app_devices ORDER BY id")
                )
            ).all()
            assert flags == [(20, True, False), (21, False, False), (22, True, False)]

        # Участник по-прежнему в аккаунте на сайте и в приложении
        from app.main import create_app

        transport = httpx.ASGITransport(app=create_app(), client=("192.0.2.30", 1))
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            client.cookies.set("pgweb_session", member_session)
            me = await client.get("/api/me")
            assert me.status_code == 200, me.text
            assert me.json()["totp_enabled"] is False
            status = await client.get(
                "/api/app/status", headers={"Authorization": f"Bearer {app_token}"}
            )
            assert status.status_code == 200, status.text

        alembic("downgrade", PREVIOUS)
        alembic("upgrade", "head")
    finally:
        await reset_schema(engine)
        await engine.dispose()
