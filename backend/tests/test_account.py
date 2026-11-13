"""Свой аккаунт: смена пароля и выход на всех устройствах (DECISIONS п. 11).

Оба действия оставляют только текущий браузер: другие входы на сайт, доверенные браузеры и
устройства приложения завершаются. Администратор подтверждает их кодом 2FA.
"""

from sqlalchemy import select

from app.db.models import AccessCode, AuditEvent
from tests.helpers import PASSWORD, password_login, register_user

NEW_PASSWORD = "changed-gateway-test-password"
ADMIN = "admin@example.test"


def device(uid: str) -> dict:
    return {"uid": uid, "name": "Test laptop", "platform": "linux", "app_version": "0.2.0"}


async def app_token(clients, email: str, uid: str, password: str = PASSWORD, **extra) -> str:
    app = await clients(csrf=False, ip="198.51.100.200")
    body = {"email": email, "password": password, "device": device(uid)} | extra
    response = await app.post("/api/app/login", json=body)
    assert response.status_code == 200, response.text
    return response.json()["token"]


async def app_status(clients, token: str) -> int:
    app = await clients(csrf=False, ip="198.51.100.201")
    return (
        await app.get("/api/app/status", headers={"Authorization": f"Bearer {token}"})
    ).status_code


async def test_member_changes_password_and_only_this_browser_stays(clients, db):
    current = await clients(ip="192.0.2.150")
    member = await register_user(current, db)
    other = await clients(ip="192.0.2.151")
    assert (await password_login(other)).json()["status"] == "ok"
    token = await app_token(clients, member["user"]["email"], "install-pppppppppppppp01")
    changed = await current.post(
        "/api/me/password", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    )
    assert changed.status_code == 200, changed.text
    assert changed.json() == {"status": "ok"}
    # Текущий браузер получил новый сеанс, остальные входы и приложение завершены
    assert (await current.get("/api/me")).status_code == 200
    assert (await other.get("/api/me")).status_code == 401
    assert await app_status(clients, token) == 401
    overview = (await current.get("/api/me/devices")).json()
    assert [item["current"] for item in overview["sessions"]] == [True]
    assert overview["devices"] == []
    assert (await password_login(other)).status_code == 401
    assert (await password_login(other, password=NEW_PASSWORD)).json()["status"] == "ok"
    actions = (await db.scalars(select(AuditEvent.action))).all()
    assert "password.changed" in actions


async def test_wrong_current_password_keeps_the_session_and_is_rate_limited(clients, db):
    browser = await clients(ip="192.0.2.152")
    await register_user(browser, db)
    body = {"current_password": "not-the-password", "new_password": NEW_PASSWORD}
    statuses = []
    for _ in range(6):
        response = await browser.post("/api/me/password", json=body)
        statuses.append(response.status_code)
        if response.status_code == 400:
            assert response.json()["error"]["code"] == "invalid_password"
    # Не 401: неверный пароль не выходит из аккаунта
    assert statuses == [400] * 5 + [429]
    assert (await browser.get("/api/me")).status_code == 200
    assert (await password_login(browser, password=NEW_PASSWORD)).status_code == 401


async def test_new_password_follows_the_policy(clients, db):
    browser = await clients(ip="192.0.2.153")
    await register_user(browser, db)
    short = await browser.post(
        "/api/me/password", json={"current_password": PASSWORD, "new_password": "short"}
    )
    assert short.status_code == 400
    assert short.json()["error"]["code"] == "password_too_short"
    assert (await password_login(browser)).json()["status"] == "ok"


async def test_password_change_needs_a_session_and_csrf(clients, db):
    browser = await clients(ip="192.0.2.154")
    await register_user(browser, db)
    anonymous = await clients(ip="192.0.2.155")
    body = {"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    assert (await anonymous.post("/api/me/password", json=body)).status_code == 401
    assert (await anonymous.post("/api/me/sign-out-everywhere", json={})).status_code == 401
    bare = await clients(csrf=False, ip="192.0.2.156")
    bare.cookies = browser.cookies
    assert (await bare.post("/api/me/password", json=body)).status_code == 403
    assert (await bare.post("/api/me/sign-out-everywhere", json={})).status_code == 403


async def test_password_change_revokes_pending_reset_codes(clients, db, totp_clock):
    admin_browser = await clients(ip="192.0.2.157")
    admin = await register_user(admin_browser, db, ADMIN, role="admin")
    browser = await clients(ip="192.0.2.158")
    member = await register_user(browser, db)
    reset = await admin_browser.post(
        f"/api/admin/members/{member['user']['id']}/reset-code", json={"code": totp_clock(admin)}
    )
    assert reset.status_code == 200
    changed = await browser.post(
        "/api/me/password", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    )
    assert changed.status_code == 200
    stale = await browser.post(
        "/api/auth/reset",
        json={
            "email": member["user"]["email"],
            "code": reset.json()["code"],
            "new_password": "another-gateway-test-password",
        },
    )
    assert stale.status_code == 400
    codes = (await db.scalars(select(AccessCode).where(AccessCode.kind == "password_reset"))).all()
    assert codes and all(code.revoked_at is not None for code in codes)


async def test_admin_confirms_password_change_with_two_factor(clients, db, totp_clock):
    browser = await clients(ip="192.0.2.159")
    admin = await register_user(browser, db, ADMIN, role="admin")
    body = {"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    missing = await browser.post("/api/me/password", json=body)
    assert missing.status_code == 400 and missing.json()["error"]["code"] == "code_required"
    wrong = await browser.post("/api/me/password", json=body | {"code": "000000"})
    assert wrong.status_code == 400 and wrong.json()["error"]["code"] == "invalid_code"
    assert (await password_login(browser, ADMIN, NEW_PASSWORD)).status_code == 401
    browser = await clients(ip="192.0.2.160")
    assert (await password_login(browser, ADMIN)).json()["status"] == "totp_required"
    assert (
        await browser.post("/api/auth/2fa", json={"code": totp_clock(admin)})
    ).status_code == 200
    done = await browser.post("/api/me/password", json=body | {"code": totp_clock(admin)})
    assert done.status_code == 200, done.text
    assert (await browser.get("/api/admin/members")).status_code == 200


async def test_member_signs_out_everywhere_except_this_browser(clients, db):
    current = await clients(ip="192.0.2.161")
    member = await register_user(current, db)
    other = await clients(ip="192.0.2.162")
    assert (await password_login(other)).json()["status"] == "ok"
    tokens = [
        await app_token(clients, member["user"]["email"], f"install-qqqqqqqqqqqqqq0{index}")
        for index in range(2)
    ]
    # Код участника не нужен; присланный — не проверяется
    done = await current.post("/api/me/sign-out-everywhere", json={})
    assert done.status_code == 200, done.text
    assert (await current.get("/api/me")).status_code == 200
    assert (await other.get("/api/me")).status_code == 401
    for token in tokens:
        assert await app_status(clients, token) == 401
    # Пароль прежний: на других устройствах можно войти снова
    assert (await password_login(other)).json()["status"] == "ok"
    # Повторный вход тех же установок приложения — не смена устройств
    again = await app_token(clients, member["user"]["email"], "install-qqqqqqqqqqqqqq00")
    assert await app_status(clients, again) == 200


async def test_admin_signs_out_everywhere_only_with_a_code(clients, db, totp_clock):
    current = await clients(ip="192.0.2.163")
    admin = await register_user(current, db, ADMIN, role="admin")
    other = await clients(ip="192.0.2.164")
    assert (await password_login(other, ADMIN)).json()["status"] == "totp_required"
    assert (await other.post("/api/auth/2fa", json={"code": totp_clock(admin)})).status_code == 200
    missing = await current.post("/api/me/sign-out-everywhere", json={})
    assert missing.status_code == 400 and missing.json()["error"]["code"] == "code_required"
    assert (await other.get("/api/me")).status_code == 200
    done = await current.post("/api/me/sign-out-everywhere", json={"code": totp_clock(admin)})
    assert done.status_code == 200, done.text
    assert (await current.get("/api/admin/members")).status_code == 200
    assert (await other.get("/api/me")).status_code == 401
