"""Журнал скачиваний, лимит входов на сайт и устройства приложения (вход по аккаунту сайта).

Участник входит в приложение паролем (присланный код не проверяется, клиенты 0.2.0 шлют его
всегда), администратор — паролем и кодом 2FA (DECISIONS п. 11).
"""

import hashlib

import pytest

from app.core.config import get_settings
from app.db.models import Release
from tests.helpers import PASSWORD, password_login, register_user

BROWSER = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140.0 Safari/537.36"


def device(uid: str = "install-0000000000000001", **changes) -> dict:
    value = {"uid": uid, "name": "Рабочий ноутбук", "platform": "windows", "app_version": "0.2.0"}
    value.update(changes)
    return value


ADMIN = "admin@example.test"


async def app_login(
    client, user, code=None, *, uid="install-0000000000000001", email=None, **extra
):
    body = {"email": email or user["user"]["email"], "password": PASSWORD, "device": device(uid)}
    if code is not None:
        body["code"] = code
    body.update(extra)
    return await client.post("/api/app/login", json=body)


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def second_session(clients, db, user, totp_clock, ip: str):
    browser = await clients(ip=ip)
    login = await password_login(browser, user["user"]["email"])
    if "secret" not in user:
        assert login.json()["status"] == "ok", login.text
        return browser
    assert login.json()["status"] == "totp_required", login.text
    done = await browser.post("/api/auth/2fa", json={"code": totp_clock(user)})
    assert done.status_code == 200, done.text
    return browser


@pytest.fixture
async def release(tmp_path, monkeypatch, db):
    root = tmp_path / "releases"
    root.mkdir()
    monkeypatch.setenv("PGWEB_DOWNLOAD_ROOT", str(root))
    get_settings.cache_clear()
    payload = b"Private Gateway test release, not an application"
    storage_name = hashlib.sha256(payload).hexdigest() + ".bin"
    (root / storage_name).write_bytes(payload)
    db.add(
        Release(
            platform="windows",
            version="1.2.3",
            filename="PrivateGateway-1.2.3-win-x64.msi",
            storage_name=storage_name,
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
        )
    )
    await db.commit()
    return payload


# --- Журнал скачиваний ---


async def test_download_is_logged_with_member_version_and_masked_ip(
    clients, db, release, totp_clock
):
    admin_client = await clients(ip="198.51.100.20")
    admin = await register_user(admin_client, db, "admin@example.test", role="admin")
    member_client = await clients(ip="203.0.113.77")
    member_client.headers["User-Agent"] = BROWSER
    member = await register_user(member_client, db)
    response = await member_client.get("/api/downloads/windows/file")
    assert response.status_code == 200 and response.content == release
    assert (await member_client.get("/api/admin/downloads")).status_code == 403
    listing = await admin_client.get("/api/admin/downloads")
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert body["total"] == 1
    event = body["items"][0]
    assert event["user"]["email"] == member["user"]["email"]
    assert (event["platform"], event["version"]) == ("windows", "1.2.3")
    assert event["filename"] == "PrivateGateway-1.2.3-win-x64.msi"
    # Полный адрес не хранится: только сеть /24
    assert event["ip_masked"] == "203.0.113.0/24"
    assert event["device"] == "Chrome · Windows"
    only_admin = await admin_client.get(f"/api/admin/downloads?user_id={admin['user']['id']}")
    assert only_admin.json()["total"] == 0
    only_member = await admin_client.get(f"/api/admin/downloads?user_id={member['user']['id']}")
    assert only_member.json()["total"] == 1


async def test_refused_download_is_not_logged(clients, db, totp_clock):
    admin_client = await clients()
    await register_user(admin_client, db, "admin@example.test", role="admin")
    assert (await admin_client.get("/api/downloads/windows/file")).status_code == 404
    anonymous = await clients(csrf=False, ip="192.0.2.99")
    assert (await anonymous.get("/api/downloads/windows/file")).status_code == 401
    assert (await admin_client.get("/api/admin/downloads")).json()["total"] == 0


# --- Входы на сайт: лимит и список ---


async def test_oldest_site_session_is_ended_over_the_limit(clients, db, totp_clock, monkeypatch):
    monkeypatch.setenv("PGWEB_SESSION_LIMIT", "2")
    get_settings.cache_clear()
    first = await clients(ip="192.0.2.31")
    user = await register_user(first, db)
    second = await second_session(clients, db, user, totp_clock, "192.0.2.32")
    assert (await first.get("/api/me")).status_code == 200
    third = await second_session(clients, db, user, totp_clock, "192.0.2.33")
    # Третий вход при лимите 2 завершает самый давний сеанс, свежие остаются
    assert (await first.get("/api/me")).status_code == 401
    assert (await second.get("/api/me")).status_code == 200
    assert (await third.get("/api/me")).status_code == 200
    overview = (await third.get("/api/me/devices")).json()
    assert overview["session_limit"] == 2
    assert len(overview["sessions"]) == 2
    assert [item["current"] for item in overview["sessions"]].count(True) == 1


async def test_member_ends_own_session_but_not_someone_elses(clients, db, totp_clock):
    first = await clients(ip="192.0.2.41")
    first.headers["User-Agent"] = BROWSER
    user = await register_user(first, db)
    second = await second_session(clients, db, user, totp_clock, "192.0.2.42")
    other_client = await clients(ip="192.0.2.43")
    await register_user(other_client, db, "other@example.test")
    sessions = (await second.get("/api/me/devices")).json()["sessions"]
    target = next(item for item in sessions if not item["current"])
    assert target["label"] == "Chrome · Windows"
    assert target["ip_masked"] == "192.0.2.0/24"
    # Чужой сеанс по номеру не найти
    assert (await other_client.post(f"/api/me/sessions/{target['id']}/revoke")).status_code == 404
    assert (await first.get("/api/me")).status_code == 200
    assert (await second.post(f"/api/me/sessions/{target['id']}/revoke")).status_code == 204
    assert (await first.get("/api/me")).status_code == 401
    # Изменение без CSRF по-прежнему отклоняется
    bare = await clients(csrf=False, ip="192.0.2.44")
    bare.cookies = second.cookies
    assert (await bare.post(f"/api/me/sessions/{target['id']}/revoke")).status_code == 403


# --- Приложение: вход по аккаунту, токен устройства ---


async def test_app_login_status_and_logout_use_only_bearer_token(clients, db, totp_clock):
    browser = await clients()
    user = await register_user(browser, db)
    app = await clients(csrf=False, ip="198.51.100.5")
    app.headers.pop("Origin")
    login = await app_login(app, user)
    assert login.status_code == 200, login.text
    token = login.json()["token"]
    assert login.json()["device"]["platform"] == "windows"
    assert login.json()["user"]["email"] == user["user"]["email"]
    status = await app.get("/api/app/status", headers=bearer(token))
    assert status.status_code == 200 and status.json()["status"] == "ok"
    assert status.json()["device"]["ip_masked"] == "198.51.100.0/24"
    # Cookie сайта не заменяет токен приложения
    assert (await browser.get("/api/app/status")).status_code == 401
    assert (await app.get("/api/app/status", headers=bearer("x" * 40))).status_code == 401
    assert (await app.post("/api/app/logout", headers=bearer(token))).status_code == 204
    assert (await app.get("/api/app/status", headers=bearer(token))).status_code == 401


async def test_admin_app_login_requires_password_and_second_factor(clients, db, totp_clock):
    browser = await clients()
    user = await register_user(browser, db, ADMIN, role="admin")
    app = await clients(csrf=False, ip="198.51.100.6")
    wrong_password = await app.post(
        "/api/app/login",
        json={
            "email": user["user"]["email"],
            "password": "not-the-password",
            "code": totp_clock(user),
            "device": device(),
        },
    )
    assert wrong_password.status_code == 401
    assert (await app_login(app, user, "000000")).json()["error"]["code"] == "invalid_code"
    code = totp_clock(user)
    assert (await app_login(app, user, code)).status_code == 200
    # Тот же код второй раз не принимается
    replay = await app_login(app, user, code, uid="install-0000000000000002")
    assert replay.status_code == 400
    both = await app_login(app, user, "123456", recovery_code=user["recovery_codes"][0])
    assert both.status_code == 422


async def test_admin_app_login_without_code_asks_for_it_and_spends_nothing(clients, db, totp_clock):
    browser = await clients()
    user = await register_user(browser, db, ADMIN, role="admin")
    app = await clients(csrf=False, ip="198.51.100.16")
    # Верный пароль без кода: 401 code_required, коды и попытки кода не тратятся
    for _ in range(7):
        missing = await app_login(app, user)
        assert missing.status_code == 401
        assert missing.json() == {"error": {"code": "code_required"}}
    wrong_password = await app.post(
        "/api/app/login",
        json={"email": ADMIN, "password": "not-the-password", "device": device()},
    )
    assert wrong_password.json()["error"]["code"] == "invalid_credentials"
    assert (await app_login(app, user, totp_clock(user))).status_code == 200
    from sqlalchemy import func, select

    from app.db.models import RecoveryCode

    unused = await db.scalar(
        select(func.count()).select_from(RecoveryCode).where(RecoveryCode.used_at.is_(None))
    )
    assert unused == 8


async def test_member_app_login_ignores_any_code(clients, db):
    browser = await clients()
    user = await register_user(browser, db)
    app = await clients(csrf=False, ip="198.51.100.17")
    # Клиент 0.2.0 всегда присылает шесть цифр; участнику код не нужен и не проверяется
    for index, extra in enumerate(
        [{"code": "000000"}, {"code": "123456"}, {"recovery_code": "anything-goes"}, {}]
    ):
        uid = f"install-mmmmmmmmmmmmmm{index:02d}"
        response = await app_login(app, user, uid=uid, **extra)
        assert response.status_code in (200, 409), response.text
        if index < 3:
            assert response.status_code == 200, response.text
    # Четвертое устройство уперлось в лимит 3, а не в проверку кода
    assert response.json()["error"]["code"] in ("device_limit", "device_change_limit")


async def test_admin_app_login_needs_two_factor_set_up_on_the_site(clients, db):
    from tests.helpers import invite, registration

    browser = await clients()
    code, _ = await invite(db, "fresh@example.test", role="admin")
    registered = await browser.post(
        "/api/auth/register", json=registration(code, "fresh@example.test")
    )
    assert registered.json()["status"] == "totp_setup_required"
    app = await clients(csrf=False, ip="198.51.100.7")
    for extra in ({"code": "123456"}, {}):
        response = await app.post(
            "/api/app/login",
            json={"email": "fresh@example.test", "password": PASSWORD, "device": device()} | extra,
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "setup_required"
    # Участник сразу после регистрации входит в приложение без 2FA
    member_code, _ = await invite(db, "fresh-member@example.test")
    other = await clients(ip="198.51.100.27")
    member = await other.post(
        "/api/auth/register", json=registration(member_code, "fresh-member@example.test")
    )
    assert member.json()["status"] == "ok"
    response = await app.post(
        "/api/app/login",
        json={"email": "fresh-member@example.test", "password": PASSWORD, "device": device()},
    )
    assert response.status_code == 200, response.text


async def test_device_limit_and_relogin_on_the_same_device(clients, db, totp_clock, monkeypatch):
    monkeypatch.setenv("PGWEB_DEVICE_LIMIT", "2")
    get_settings.cache_clear()
    browser = await clients()
    user = await register_user(browser, db)
    app = await clients(csrf=False, ip="198.51.100.8")
    one = (await app_login(app, user, uid="install-aaaaaaaaaaaaaaa1")).json()
    two = await app_login(app, user, uid="install-aaaaaaaaaaaaaaa2")
    assert two.status_code == 200
    third = await app_login(app, user, uid="install-aaaaaaaaaaaaaaa3")
    assert third.status_code == 409
    assert third.json()["error"]["code"] == "device_limit"
    # Повторный вход того же устройства лимит не тратит, а прежний токен гаснет
    again = await app_login(app, user, uid="install-aaaaaaaaaaaaaaa1")
    assert again.status_code == 200
    assert (await app.get("/api/app/status", headers=bearer(one["token"]))).status_code == 401
    assert (
        await app.get("/api/app/status", headers=bearer(again.json()["token"]))
    ).status_code == 200
    overview = (await browser.get("/api/me/devices")).json()
    assert overview["device_limit"] == 2
    assert len(overview["devices"]) == 2


async def test_member_removes_device_and_frees_the_slot(clients, db, totp_clock, monkeypatch):
    monkeypatch.setenv("PGWEB_DEVICE_LIMIT", "1")
    get_settings.cache_clear()
    browser = await clients()
    user = await register_user(browser, db)
    app = await clients(csrf=False, ip="198.51.100.9")
    token = (await app_login(app, user)).json()["token"]
    blocked = await app_login(app, user, uid="install-bbbbbbbbbbbbbbbb")
    assert blocked.status_code == 409
    device_id = (await browser.get("/api/me/devices")).json()["devices"][0]["id"]
    assert (await browser.post(f"/api/me/devices/{device_id}/revoke")).status_code == 204
    assert (await app.get("/api/app/status", headers=bearer(token))).status_code == 401
    freed = await app_login(app, user, uid="install-bbbbbbbbbbbbbbbb")
    assert freed.status_code == 200


async def test_admin_sees_and_revokes_member_devices_and_blocking_logs_app_out(
    clients, db, totp_clock
):
    admin_client = await clients(ip="198.51.100.30")
    admin = await register_user(admin_client, db, "admin@example.test", role="admin")
    member_client = await clients(ip="203.0.113.30")
    member = await register_user(member_client, db)
    member_id = member["user"]["id"]
    app = await clients(csrf=False, ip="203.0.113.31")
    first = (await app_login(app, member)).json()["token"]
    second = (await app_login(app, member, uid="install-cccccccccccccccc")).json()["token"]
    assert (await member_client.get(f"/api/admin/members/{member_id}/devices")).status_code == 403
    overview = (await admin_client.get(f"/api/admin/members/{member_id}/devices")).json()
    assert len(overview["devices"]) == 2 and len(overview["sessions"]) == 1
    target = next(item for item in overview["devices"] if item["name"])
    revoke = await admin_client.post(
        f"/api/admin/members/{member_id}/devices/{target['id']}/revoke"
    )
    assert revoke.status_code == 204
    statuses = [
        (await app.get("/api/app/status", headers=bearer(token))).status_code
        for token in (first, second)
    ]
    assert sorted(statuses) == [200, 401]
    session_id = overview["sessions"][0]["id"]
    ended = await admin_client.post(f"/api/admin/members/{member_id}/sessions/{session_id}/revoke")
    assert ended.status_code == 204
    assert (await member_client.get("/api/me")).status_code == 401
    # Блокировка участника сразу гасит и оставшееся устройство приложения
    blocked = await admin_client.patch(
        f"/api/admin/members/{member_id}", json={"status": "blocked", "code": totp_clock(admin)}
    )
    assert blocked.status_code == 200
    for token in (first, second):
        assert (await app.get("/api/app/status", headers=bearer(token))).status_code == 401


async def test_admin_sets_personal_device_limit(clients, db, totp_clock, monkeypatch):
    monkeypatch.setenv("PGWEB_DEVICE_LIMIT", "1")
    get_settings.cache_clear()
    admin_client = await clients(ip="198.51.100.40")
    admin = await register_user(admin_client, db, "admin@example.test", role="admin")
    member_client = await clients(ip="203.0.113.40")
    member = await register_user(member_client, db)
    path = f"/api/admin/members/{member['user']['id']}"
    changed = await admin_client.patch(path, json={"device_limit": 3, "code": totp_clock(admin)})
    assert changed.status_code == 200 and changed.json()["device_limit"] == 3
    # Свой лимит не завершает сеанс участника, в отличие от смены роли или блокировки
    assert (await member_client.get("/api/me")).status_code == 200
    app = await clients(csrf=False, ip="203.0.113.41")
    for index in range(3):
        uid = f"install-dddddddddddddd{index:02d}"
        assert (await app_login(app, member, uid=uid)).status_code == 200
    reset = await admin_client.patch(path, json={"device_limit": None, "code": totp_clock(admin)})
    assert reset.status_code == 200 and reset.json()["device_limit"] is None
    member_limit = (await member_client.get("/api/me/devices")).json()["device_limit"]
    assert member_limit == 1


async def test_app_password_change_invalidates_device_token(clients, db, totp_clock):
    admin_client = await clients(ip="198.51.100.50")
    admin = await register_user(admin_client, db, "admin@example.test", role="admin")
    member_client = await clients(ip="203.0.113.50")
    member = await register_user(member_client, db)
    app = await clients(csrf=False, ip="203.0.113.51")
    token = (await app_login(app, member)).json()["token"]
    reset = await admin_client.post(
        f"/api/admin/members/{member['user']['id']}/reset-code", json={"code": totp_clock(admin)}
    )
    assert reset.status_code == 200
    anonymous = await clients(ip="203.0.113.52")
    done = await anonymous.post(
        "/api/auth/reset",
        json={
            "email": member["user"]["email"],
            "code": reset.json()["code"],
            "new_password": "gateway-new-test-password",
        },
    )
    assert done.status_code == 200, done.text
    assert (await app.get("/api/app/status", headers=bearer(token))).status_code == 401


async def test_device_token_dies_when_auth_version_changes(clients, db, totp_clock):
    """Слой auth_version сам по себе: даже без явного отзыва устройства токен гаснет."""
    from sqlalchemy import update

    from app.db.models import User

    browser = await clients()
    user = await register_user(browser, db)
    app = await clients(csrf=False, ip="198.51.100.60")
    token = (await app_login(app, user)).json()["token"]
    assert (await app.get("/api/app/status", headers=bearer(token))).status_code == 200
    await db.execute(
        update(User).where(User.id == user["user"]["id"]).values(auth_version=User.auth_version + 1)
    )
    await db.commit()
    assert (await app.get("/api/app/status", headers=bearer(token))).status_code == 401


async def test_blocking_marks_every_app_device_revoked(clients, db, totp_clock):
    """Слой явного отзыва: устройства помечены отозванными, не только устарели по auth_version."""
    from sqlalchemy import select

    from app.db.models import AppDevice

    admin_client = await clients(ip="198.51.100.61")
    admin = await register_user(admin_client, db, "admin@example.test", role="admin")
    member_client = await clients(ip="203.0.113.61")
    member = await register_user(member_client, db)
    app = await clients(csrf=False, ip="203.0.113.62")
    assert (await app_login(app, member)).status_code == 200
    blocked = await admin_client.patch(
        f"/api/admin/members/{member['user']['id']}",
        json={"status": "blocked", "code": totp_clock(admin)},
    )
    assert blocked.status_code == 200
    db.expire_all()
    rows = (
        await db.scalars(select(AppDevice).where(AppDevice.user_id == member["user"]["id"]))
    ).all()
    assert rows and all(row.revoked_at is not None for row in rows)


# --- Проверки по итогам разбора: обход 2FA, коды, попытки, чужие устройства, сроки ---


async def test_ended_session_also_forgets_the_trusted_browser(clients, db, totp_clock):
    """Завершенный вход не дает войти снова одним паролем через «запомнить устройство»."""
    owner = await clients(ip="192.0.2.71")
    user = await register_user(owner, db, ADMIN, role="admin")
    stranger = await clients(ip="192.0.2.72")
    assert (await password_login(stranger, user["user"]["email"])).json()["status"] == (
        "totp_required"
    )
    remembered = await stranger.post(
        "/api/auth/2fa", json={"code": totp_clock(user), "remember_device": True}
    )
    assert remembered.status_code == 200, remembered.text
    # Пока вход не завершен, доверенный браузер входит без кода (так и задумано)
    assert (await password_login(stranger, user["user"]["email"])).json()["status"] == "ok"
    sessions = (await owner.get("/api/me/devices")).json()["sessions"]
    target = next(item for item in sessions if not item["current"])
    assert (await owner.post(f"/api/me/sessions/{target['id']}/revoke")).status_code == 204
    again = await password_login(stranger, user["user"]["email"])
    assert again.status_code == 200 and again.json()["status"] == "totp_required"


async def test_evicted_session_also_forgets_the_trusted_browser(
    clients, db, totp_clock, monkeypatch
):
    monkeypatch.setenv("PGWEB_SESSION_LIMIT", "1")
    get_settings.cache_clear()
    first = await clients(ip="192.0.2.73")
    user = await register_user(first, db, ADMIN, role="admin")
    await password_login(first, user["user"]["email"])
    remembered = await first.post(
        "/api/auth/2fa", json={"code": totp_clock(user), "remember_device": True}
    )
    assert remembered.status_code == 200
    await second_session(clients, db, user, totp_clock, "192.0.2.74")
    # Вход сверх лимита завершил первый браузер вместе с его доверием
    assert (await first.get("/api/me")).status_code == 401
    assert (await password_login(first, user["user"]["email"])).json()["status"] == (
        "totp_required"
    )


async def test_device_limit_refusal_still_spends_the_code_and_keeps_site_login_open(
    clients, db, totp_clock, monkeypatch
):
    monkeypatch.setenv("PGWEB_DEVICE_LIMIT", "1")
    get_settings.cache_clear()
    browser = await clients(ip="198.51.100.70")
    user = await register_user(browser, db, ADMIN, role="admin")
    app = await clients(csrf=False, ip="198.51.100.71")
    assert (await app_login(app, user, totp_clock(user))).status_code == 200
    code = totp_clock(user)
    refused = await app_login(app, user, code, uid="install-eeeeeeeeeeeeeee1")
    assert refused.status_code == 409
    # Предъявленный код израсходован, хотя вход не состоялся
    replay = await browser.post(
        "/api/auth/login", json={"email": user["user"]["email"], "password": PASSWORD}
    )
    assert replay.json()["status"] == "totp_required"
    assert (await browser.post("/api/auth/2fa", json={"code": code})).status_code == 400
    recovery = user["recovery_codes"][0]
    by_recovery = await app_login(
        app, user, None, uid="install-eeeeeeeeeeeeeee2", recovery_code=recovery
    )
    assert by_recovery.status_code == 409
    again = await app_login(app, user, None, uid="install-eeeeeeeeeeeeeee2", recovery_code=recovery)
    assert again.json()["error"]["code"] == "invalid_code"
    # Много отказов по лимиту не закрывают вход на сайт, где освобождают место
    for index in range(6):
        uid = f"install-ffffffffffffff{index:02d}"
        assert (await app_login(app, user, totp_clock(user), uid=uid)).status_code == 409
    site = await clients(ip="198.51.100.71")
    assert (await password_login(site, user["user"]["email"])).status_code == 200
    assert (await site.post("/api/auth/2fa", json={"code": totp_clock(user)})).status_code == 200


async def test_app_login_is_rate_limited(clients, db, totp_clock):
    browser = await clients(ip="198.51.100.80")
    user = await register_user(browser, db)
    app = await clients(csrf=False, ip="198.51.100.81")
    body = {
        "email": user["user"]["email"],
        "password": "not-the-password",
        "code": "123456",
        "device": device(),
    }
    statuses = [(await app.post("/api/app/login", json=body)).status_code for _ in range(6)]
    assert statuses == [401] * 5 + [429]
    # Администратор: верный пароль и неверные коды — перебор кода тоже ограничен
    admin_browser = await clients(ip="198.51.100.83")
    admin = await register_user(admin_browser, db, ADMIN, role="admin")
    other = await clients(csrf=False, ip="198.51.100.82")
    codes = [(await app_login(other, admin, "000000")).status_code for _ in range(6)]
    assert codes == [400] * 5 + [429]
    assert (await app_login(other, admin, totp_clock(admin))).status_code == 429


async def test_nobody_revokes_someone_elses_app_device(clients, db, totp_clock):
    admin_client = await clients(ip="198.51.100.90")
    await register_user(admin_client, db, "admin@example.test", role="admin")
    first_client = await clients(ip="203.0.113.90")
    first = await register_user(first_client, db, "first@example.test")
    second_client = await clients(ip="203.0.113.91")
    second = await register_user(second_client, db, "second@example.test")
    app = await clients(csrf=False, ip="203.0.113.92")
    token = (await app_login(app, first)).json()["token"]
    device_id = (await first_client.get("/api/me/devices")).json()["devices"][0]["id"]
    assert (await second_client.post(f"/api/me/devices/{device_id}/revoke")).status_code == 404
    wrong_member = f"/api/admin/members/{second['user']['id']}/devices/{device_id}/revoke"
    assert (await admin_client.post(wrong_member)).status_code == 404
    assert (await admin_client.get("/api/admin/members/999999/devices")).status_code == 404
    assert (await app.get("/api/app/status", headers=bearer(token))).status_code == 200


async def test_blocked_member_cannot_sign_in_to_the_app(clients, db, totp_clock):
    from sqlalchemy import func, select

    from app.db.models import AppDevice

    admin_client = await clients(ip="198.51.100.95")
    admin = await register_user(admin_client, db, "admin@example.test", role="admin")
    member_client = await clients(ip="203.0.113.95")
    member = await register_user(member_client, db)
    blocked = await admin_client.patch(
        f"/api/admin/members/{member['user']['id']}",
        json={"status": "blocked", "code": totp_clock(admin)},
    )
    assert blocked.status_code == 200
    app = await clients(csrf=False, ip="203.0.113.96")
    refused = await app_login(app, member, "123456")
    assert refused.status_code == 401
    assert refused.json()["error"]["code"] == "invalid_credentials"
    count = await db.scalar(
        select(func.count()).select_from(AppDevice).where(AppDevice.user_id == member["user"]["id"])
    )
    assert count == 0


async def test_expired_device_token_is_refused_and_frees_the_slot(
    clients, db, totp_clock, monkeypatch
):
    from datetime import timedelta

    from sqlalchemy import update

    from app.db.models import AppDevice, utcnow

    monkeypatch.setenv("PGWEB_DEVICE_LIMIT", "1")
    get_settings.cache_clear()
    browser = await clients(ip="198.51.100.97")
    user = await register_user(browser, db)
    app = await clients(csrf=False, ip="198.51.100.98")
    token = (await app_login(app, user)).json()["token"]
    await db.execute(
        update(AppDevice)
        .where(AppDevice.user_id == user["user"]["id"])
        .values(expires_at=utcnow() - timedelta(minutes=1))
    )
    await db.commit()
    assert (await app.get("/api/app/status", headers=bearer(token))).status_code == 401
    assert (await browser.get("/api/me/devices")).json()["devices"] == []
    other = await app_login(app, user, uid="install-gggggggggggggggg")
    assert other.status_code == 200


async def test_admin_sees_own_current_browser_on_own_card(clients, db):
    admin_client = await clients(ip="198.51.100.99")
    admin = await register_user(admin_client, db, "admin@example.test", role="admin")
    own = await admin_client.get(f"/api/admin/members/{admin['user']['id']}/devices")
    assert [item["current"] for item in own.json()["sessions"]] == [True]


async def test_download_log_skips_broken_files_and_pages_newest_first(
    clients, db, release, totp_clock, tmp_path
):
    from sqlalchemy import select

    from app.db.models import Release

    admin_client = await clients(ip="198.51.100.100")
    await register_user(admin_client, db, "admin@example.test", role="admin")
    member_client = await clients(ip="203.0.113.100")
    await register_user(member_client, db)
    for _ in range(3):
        assert (await member_client.get("/api/downloads/windows/file")).status_code == 200
    page = (await admin_client.get("/api/admin/downloads?limit=2&offset=0")).json()
    rest = (await admin_client.get("/api/admin/downloads?limit=2&offset=2")).json()
    assert page["total"] == rest["total"] == 3
    first_ids = [item["id"] for item in page["items"]]
    assert len(first_ids) == 2 and len(rest["items"]) == 1
    assert first_ids == sorted(first_ids, reverse=True)
    assert rest["items"][0]["id"] < min(first_ids)
    # Файл выпуска испорчен: скачивание отклонено и в журнал не попадает
    stored = (await db.scalars(select(Release))).one()
    (tmp_path / "releases" / stored.storage_name).write_bytes(b"broken")
    assert (await member_client.get("/api/downloads/windows/file")).status_code == 404
    assert (await admin_client.get("/api/admin/downloads")).json()["total"] == 3


# --- Смена устройств: не больше 3 новых установок за 30 дней (DECISIONS п. 11) ---


async def test_device_change_limit_counts_new_installations_only(clients, db):
    browser = await clients(ip="203.0.113.110")
    member = await register_user(browser, db)
    app = await clients(csrf=False, ip="203.0.113.111")
    uids = [f"install-hhhhhhhhhhhhhh{index:02d}" for index in range(4)]
    for uid in uids[:3]:
        assert (await app_login(app, member, uid=uid)).status_code == 200
    overview = (await browser.get("/api/me/devices")).json()
    assert overview["device_changes"] == {"used": 3, "limit": 3, "days": 30}
    # Место освобождено, но три новых установки за 30 дней уже были: четвертая — отказ
    first = overview["devices"][-1]
    assert (await browser.post(f"/api/me/devices/{first['id']}/revoke")).status_code == 204
    refused = await app_login(app, member, uid=uids[3])
    assert refused.status_code == 409
    assert refused.json() == {"error": {"code": "device_change_limit"}}
    # Повторный вход знакомой установки — не смена, даже после удаления участником
    for uid in uids[:3]:
        again = await app_login(app, member, uid=uid)
        assert again.status_code == 200, again.text
    after = (await browser.get("/api/me/devices")).json()
    assert after["device_changes"]["used"] == 3 and len(after["devices"]) == 3


async def test_device_removed_by_admin_frees_a_device_change(clients, db, totp_clock):
    from sqlalchemy import select

    from app.db.models import AppDevice

    admin_client = await clients(ip="198.51.100.111")
    await register_user(admin_client, db, ADMIN, role="admin")
    browser = await clients(ip="203.0.113.112")
    member = await register_user(browser, db)
    member_id = member["user"]["id"]
    app = await clients(csrf=False, ip="203.0.113.113")
    for index in range(3):
        uid = f"install-iiiiiiiiiiiiii{index:02d}"
        assert (await app_login(app, member, uid=uid)).status_code == 200
    blocked = await app_login(app, member, uid="install-iiiiiiiiiiiiii03")
    assert blocked.json()["error"]["code"] == "device_change_limit"
    first = await db.scalar(
        select(AppDevice).where(AppDevice.device_uid == "install-iiiiiiiiiiiiii00")
    )
    removed = await admin_client.post(f"/api/admin/members/{member_id}/devices/{first.id}/revoke")
    assert removed.status_code == 204
    assert (await browser.get("/api/me/devices")).json()["device_changes"]["used"] == 2
    assert (await app_login(app, member, uid="install-iiiiiiiiiiiiii03")).status_code == 200
    # Удаленное самим участником — по-прежнему в счете
    fourth = await db.scalar(
        select(AppDevice).where(AppDevice.device_uid == "install-iiiiiiiiiiiiii03")
    )
    assert (await browser.post(f"/api/me/devices/{fourth.id}/revoke")).status_code == 204
    again = await app_login(app, member, uid="install-iiiiiiiiiiiiii04")
    assert again.json()["error"]["code"] == "device_change_limit"


async def test_device_change_window_and_count_are_configurable(clients, db, monkeypatch):
    from datetime import timedelta

    from sqlalchemy import update

    from app.db.models import AppDevice, utcnow

    monkeypatch.setenv("PGWEB_DEVICE_CHANGES", "1")
    monkeypatch.setenv("PGWEB_DEVICE_CHANGE_DAYS", "7")
    monkeypatch.setenv("PGWEB_DEVICE_LIMIT", "1")
    get_settings.cache_clear()
    browser = await clients(ip="203.0.113.114")
    member = await register_user(browser, db)
    app = await clients(csrf=False, ip="203.0.113.115")
    assert (await app_login(app, member, uid="install-jjjjjjjjjjjjjj00")).status_code == 200
    device_id = (await browser.get("/api/me/devices")).json()["devices"][0]["id"]
    assert (await browser.post(f"/api/me/devices/{device_id}/revoke")).status_code == 204
    refused = await app_login(app, member, uid="install-jjjjjjjjjjjjjj01")
    assert refused.json()["error"]["code"] == "device_change_limit"
    assert (await browser.get("/api/me/devices")).json()["device_changes"] == {
        "used": 1,
        "limit": 1,
        "days": 7,
    }
    # Неделя прошла: прежняя смена больше не считается
    await db.execute(
        update(AppDevice)
        .where(AppDevice.user_id == member["user"]["id"])
        .values(created_at=utcnow() - timedelta(days=7, minutes=1))
    )
    await db.commit()
    assert (await app_login(app, member, uid="install-jjjjjjjjjjjjjj01")).status_code == 200


async def test_personal_device_limit_raises_the_change_limit(clients, db, totp_clock):
    admin_client = await clients(ip="198.51.100.116")
    admin = await register_user(admin_client, db, ADMIN, role="admin")
    browser = await clients(ip="203.0.113.116")
    member = await register_user(browser, db)
    changed = await admin_client.patch(
        f"/api/admin/members/{member['user']['id']}",
        json={"device_limit": 5, "code": totp_clock(admin)},
    )
    assert changed.status_code == 200
    app = await clients(csrf=False, ip="203.0.113.117")
    for index in range(5):
        uid = f"install-kkkkkkkkkkkkkk{index:02d}"
        assert (await app_login(app, member, uid=uid)).status_code == 200, index
    overview = (await browser.get("/api/me/devices")).json()
    assert overview["device_changes"] == {"used": 5, "limit": 5, "days": 30}
    assert (await app_login(app, member, uid="install-kkkkkkkkkkkkkk05")).status_code == 409
