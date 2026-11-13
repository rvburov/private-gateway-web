"""Сценарии входа проходят через API, токены и коды не подменяются сеансами в БД.

Двухфакторная проверка — только у администраторов (DECISIONS п. 11): сценарии с кодом 2FA
идут от администратора, участник входит по паролю.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.security import tokens, totp
from app.db.models import RecoveryCode, User, UserSession
from tests.helpers import invite, password_login, register_user, registration, session_cookie

ADMIN = "admin@example.test"


async def test_member_invitation_opens_the_account_without_two_factor(client, db):
    code, access = await invite(db)
    registered = await client.post("/api/auth/register", json=registration(code))
    assert registered.status_code == 200, registered.text
    assert registered.json()["status"] == "ok"
    assert registered.json()["user"]["totp_enabled"] is False
    me = await client.get("/api/me")
    assert me.status_code == 200 and me.json()["role"] == "member"
    cookie = session_cookie(client)
    assert cookie.has_nonstandard_attr("HttpOnly")
    assert cookie.get_nonstandard_attr("SameSite") == "lax"
    user = await db.get(User, me.json()["id"], populate_existing=True)
    assert user.password_hash.startswith("$argon2id$")
    assert user.totp_secret_enc is None
    assert await db.scalar(select(func.count()).select_from(RecoveryCode)) == 0
    await db.refresh(access)
    assert access.used_at is not None
    # Шаги 2FA участнику недоступны: незавершенного входа у него нет
    assert (await client.post("/api/auth/2fa/setup", json={})).status_code == 401
    # Повторный вход — тоже только паролем
    assert (await client.post("/api/auth/logout", json={})).status_code == 204
    login = await password_login(client)
    assert login.status_code == 200 and login.json()["status"] == "ok"
    assert login.json()["user"]["email"] == "member@example.test"
    assert (await client.get("/api/downloads")).status_code == 200


async def test_admin_invitation_setup_and_session_are_real(client, db):
    code, access = await invite(db, ADMIN, role="admin")
    registered = await client.post("/api/auth/register", json=registration(code, ADMIN))
    assert registered.status_code == 200, registered.text
    assert registered.json()["status"] == "totp_setup_required"
    assert (await client.get("/api/me")).status_code == 401
    setup = (await client.post("/api/auth/2fa/setup", json={})).json()
    assert (await client.post("/api/auth/2fa/setup", json={})).json()["secret"] == setup["secret"]
    assert "Private%20Gateway" in setup["otpauth_uri"]
    assert setup["qr_svg"].startswith("<svg")
    done = await client.post(
        "/api/auth/2fa/setup/confirm",
        json={"code": totp.code_at_step(setup["secret"], totp.current_step())},
    )
    assert done.status_code == 200, done.text
    codes = done.json()["recovery_codes"]
    assert len(codes) == len(set(codes)) == 8
    me = await client.get("/api/me")
    assert me.status_code == 200 and me.json()["role"] == "admin"
    cookie = session_cookie(client)
    assert cookie.has_nonstandard_attr("HttpOnly")
    assert cookie.get_nonstandard_attr("SameSite") == "lax"
    user = await db.get(User, me.json()["id"], populate_existing=True)
    assert user.password_hash.startswith("$argon2id$")
    assert setup["secret"].encode() not in user.totp_secret_enc
    stored_codes = list((await db.scalars(select(RecoveryCode.code_hash))).all())
    assert set(stored_codes) == {tokens.hash_code(c) for c in codes}
    stored_sessions = list((await db.scalars(select(UserSession))).all())
    assert len(stored_sessions) == 1
    assert cookie.value not in repr(stored_sessions[0].__dict__)
    await db.refresh(access)
    assert access.used_at is not None


@pytest.mark.parametrize("variant", ["unknown", "wrong_email", "expired", "revoked"])
async def test_invalid_invitation_does_not_create_account(client, db, variant):
    changes = {}
    if variant == "expired":
        changes["expires_at"] = datetime.now(UTC) - timedelta(seconds=1)
    if variant == "revoked":
        changes["revoked_at"] = datetime.now(UTC)
    code, _ = await invite(db, **changes)
    if variant == "unknown":
        code = tokens.gen_invite_code()
    email = "other@example.test" if variant == "wrong_email" else "member@example.test"
    response = await client.post("/api/auth/register", json=registration(code, email))
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "invalid_invite"
    assert await db.scalar(select(func.count()).select_from(User)) == 0
    assert (await client.get("/api/me")).status_code == 401


async def test_invitation_only_consumed_once_under_concurrency(clients, db):
    code, _ = await invite(db)
    first, second = await clients(ip="192.0.2.11"), await clients(ip="192.0.2.12")
    responses = await asyncio.gather(
        first.post("/api/auth/register", json=registration(code)),
        second.post("/api/auth/register", json=registration(code)),
    )
    assert sorted(r.status_code for r in responses) == [200, 400]
    assert await db.scalar(select(func.count()).select_from(User)) == 1


async def test_password_step_does_not_open_account_and_totp_cannot_replay(client, db):
    user = await register_user(client, db, ADMIN, role="admin")
    assert (await client.post("/api/auth/logout", json={})).status_code == 204
    assert (await client.get("/api/me")).status_code == 401
    login = await password_login(client, ADMIN)
    assert login.status_code == 200 and login.json()["status"] == "totp_required"
    assert (await client.get("/api/downloads")).status_code == 401
    original = totp.code_at_step(user["secret"], user["step"])
    replay = await client.post("/api/auth/2fa", json={"code": original, "remember_device": False})
    assert replay.status_code == 400 and replay.json()["error"]["code"] == "invalid_code"
    next_code = totp.code_at_step(user["secret"], user["step"] + 1)
    complete = await client.post(
        "/api/auth/2fa", json={"code": next_code, "remember_device": False}
    )
    assert complete.status_code == 200 and complete.json()["status"] == "ok"
    assert (await client.get("/api/me")).status_code == 200


async def test_recovery_code_is_one_use_even_with_two_challenges(clients, client, db):
    user = await register_user(client, db, ADMIN, role="admin")
    first, second = await clients(ip="192.0.2.13"), await clients(ip="192.0.2.14")
    assert (await password_login(first, ADMIN)).status_code == 200
    assert (await password_login(second, ADMIN)).status_code == 200
    payload = {"recovery_code": user["recovery_codes"][0], "remember_device": False}
    responses = await asyncio.gather(
        first.post("/api/auth/2fa", json=payload), second.post("/api/auth/2fa", json=payload)
    )
    assert sorted(r.status_code for r in responses) == [200, 400]
    authorized = [(await browser.get("/api/me")).status_code for browser in (first, second)]
    assert sorted(authorized) == [200, 401]


async def test_wrong_password_and_unknown_account_have_same_error(client, db):
    await register_user(client, db)
    await client.post("/api/auth/logout", json={})
    wrong = await password_login(client, password="incorrect-test-password")
    unknown = await password_login(client, email="missing@example.test")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"error": {"code": "invalid_credentials"}}


async def test_password_policy_does_not_consume_invite(client, db):
    code, row = await invite(db)
    response = await client.post("/api/auth/register", json=registration(code, password="short"))
    assert response.status_code in (400, 422)
    await db.refresh(row)
    assert row.used_at is None
    correct = await client.post("/api/auth/register", json=registration(code))
    assert correct.status_code == 200, correct.text


async def test_failed_login_has_persistent_rate_limit(client, clients):
    for _ in range(5):
        response = await password_login(client, email="missing@example.test")
        assert response.status_code == 401, response.text
    limited = await password_login(client, email="missing@example.test")
    assert limited.status_code == 429, limited.text
    assert int(limited.headers["Retry-After"]) > 0
    other = await clients(ip="192.0.2.200")
    assert (await password_login(other, email="missing@example.test")).status_code == 401


async def test_remembered_device_still_needs_password_and_expires(client, db):
    from sqlalchemy import update

    from app.db.models import TrustedDevice

    user = await register_user(client, db, ADMIN, role="admin")
    await client.post("/api/auth/logout", json={})
    assert (await password_login(client, ADMIN)).json()["status"] == "totp_required"
    done = await client.post(
        "/api/auth/2fa",
        json={
            "code": totp.code_at_step(user["secret"], user["step"] + 1),
            "remember_device": True,
        },
    )
    assert done.status_code == 200, done.text
    device_cookie = next(cookie for cookie in client.cookies.jar if "device" in cookie.name)
    stored = (await db.scalars(select(TrustedDevice))).one()
    assert stored.token_hash == tokens.hash_token(device_cookie.value)
    assert stored.expires_at <= datetime.now(UTC) + timedelta(days=30, seconds=1)
    await client.post("/api/auth/logout", json={})
    assert (await client.get("/api/me")).status_code == 401
    assert (await password_login(client, ADMIN, password="wrong-test-password")).status_code == 401
    assert (await password_login(client, ADMIN)).json()["status"] == "ok"
    await client.post("/api/auth/logout", json={})
    await db.execute(
        update(TrustedDevice).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await db.commit()
    assert (await password_login(client, ADMIN)).json()["status"] == "totp_required"


async def test_expired_session_and_challenge_cannot_authorize(client, db):
    from sqlalchemy import update

    from app.db.models import LoginChallenge

    user = await register_user(client, db, ADMIN, role="admin")
    past = datetime.now(UTC) - timedelta(seconds=1)
    await db.execute(update(UserSession).values(expires_at=past))
    await db.commit()
    assert (await client.get("/api/me")).status_code == 401
    assert (await password_login(client, ADMIN)).json()["status"] == "totp_required"
    await db.execute(update(LoginChallenge).values(expires_at=past))
    await db.commit()
    response = await client.post(
        "/api/auth/2fa",
        json={
            "code": totp.code_at_step(user["secret"], user["step"] + 1),
            "remember_device": False,
        },
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "login_expired"


async def test_new_password_challenge_revokes_previous_session(client, clients, db):
    await register_user(client, db, ADMIN, role="admin")
    old = session_cookie(client)
    old_name, old_value = old.name, old.value
    challenge = await password_login(client, ADMIN)
    assert challenge.json()["status"] == "totp_required"
    assert (await client.get("/api/me")).status_code == 401
    copied = await clients(ip="192.0.2.80")
    copied.cookies.set(old_name, old_value)
    assert (await copied.get("/api/me")).status_code == 401


async def test_new_member_sign_in_replaces_the_session_of_this_browser(client, clients, db):
    await register_user(client, db)
    old = session_cookie(client)
    old_name, old_value = old.name, old.value
    assert (await password_login(client)).json()["status"] == "ok"
    assert (await client.get("/api/me")).status_code == 200
    copied = await clients(ip="192.0.2.81")
    copied.cookies.set(old_name, old_value)
    assert (await copied.get("/api/me")).status_code == 401


async def test_admin_without_two_factor_gets_no_session_only_setup(client, clients, db):
    """Назначенный администратор без 2FA входит только через настройку приложения 2FA."""
    from sqlalchemy import update

    admin_browser = await clients(ip="192.0.2.82")
    admin = await register_user(admin_browser, db, ADMIN, role="admin")
    member = await register_user(client, db)
    await db.execute(update(User).where(User.id == member["user"]["id"]).values(role="admin"))
    await db.commit()
    # Сеанс, выданный участнику, у администратора без 2FA не действует
    assert (await client.get("/api/me")).status_code == 401
    assert (await client.get("/api/admin/members")).status_code == 401
    login = await password_login(client)
    assert login.status_code == 200 and login.json()["status"] == "totp_setup_required"
    assert (await client.get("/api/me")).status_code == 401
    setup = (await client.post("/api/auth/2fa/setup", json={})).json()
    done = await client.post(
        "/api/auth/2fa/setup/confirm",
        json={"code": totp.code_at_step(setup["secret"], totp.current_step())},
    )
    assert done.status_code == 200, done.text
    assert (await client.get("/api/admin/members")).status_code == 200
    assert admin["user"]["role"] == "admin"


async def test_stale_member_challenge_cannot_start_two_factor(client, db):
    """Незавершенный шаг входа участника (до перехода на вход по паролю) не ведет к 2FA."""
    from app.db.models import LoginChallenge

    user = await register_user(client, db)
    value = tokens.new_token()
    db.add(
        LoginChallenge(
            user_id=user["user"]["id"],
            token_hash=tokens.hash_token(value),
            auth_version=1,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
    )
    await db.commit()
    client.cookies.set("pgweb_login", value)
    for path, body in (
        ("/api/auth/2fa/setup", {}),
        ("/api/auth/2fa/setup/confirm", {"code": "123456"}),
        ("/api/auth/2fa", {"code": "123456"}),
    ):
        response = await client.post(path, json=body)
        assert response.status_code == 401, (path, response.text)
        assert response.json()["error"]["code"] == "login_expired"
