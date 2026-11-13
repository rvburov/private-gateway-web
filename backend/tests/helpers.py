"""Подготовка синтетических приглашений, затем обычный путь браузера."""

from datetime import UTC, datetime, timedelta

from app.core.security import tokens, totp
from app.db.models import AccessCode

PASSWORD = "gateway-test-only-password"


async def invite(db, email="member@example.test", *, role="member", **changes):
    code = tokens.gen_invite_code()
    values = dict(
        kind="invite",
        code_hash=tokens.hash_code(code, prefix="PG"),
        email=email,
        role=role,
        expires_at=datetime.now(UTC) + timedelta(days=2),
    )
    values.update(changes)
    row = AccessCode(**values)
    db.add(row)
    await db.commit()
    return code, row


def registration(code, email="member@example.test", **extra):
    body = dict(invite_code=code, email=email, display_name="Test Member", password=PASSWORD)
    body.update(extra)
    return body


async def register_user(client, db, email="member@example.test", *, role="member"):
    """Участник входит сразу после регистрации; администратор настраивает 2FA."""
    code, _ = await invite(db, email, role=role)
    response = await client.post("/api/auth/register", json=registration(code, email))
    assert response.status_code == 200, response.text
    if role == "member":
        assert response.json()["status"] == "ok", response.text
        return {"user": response.json()["user"], "password": PASSWORD}
    assert response.json()["status"] == "totp_setup_required"
    setup = await client.post("/api/auth/2fa/setup", json={})
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    step = totp.current_step()
    response = await client.post(
        "/api/auth/2fa/setup/confirm", json={"code": totp.code_at_step(secret, step)}
    )
    assert response.status_code == 200, response.text
    return {
        "user": response.json()["user"],
        "secret": secret,
        "step": step,
        "recovery_codes": response.json()["recovery_codes"],
        "password": PASSWORD,
    }


async def password_login(client, email="member@example.test", password=PASSWORD):
    return await client.post("/api/auth/login", json={"email": email, "password": password})


def session_cookie(client):
    found = [cookie for cookie in client.cookies.jar if "session" in cookie.name]
    assert len(found) == 1
    return found[0]
