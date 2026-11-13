"""Полное удаление участника и приглашений, смена роли и 2FA (DECISIONS п. 11)."""

import hashlib

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.models import (
    AccessCode,
    AppDevice,
    AuditEvent,
    DownloadEvent,
    LoginChallenge,
    RecoveryCode,
    Release,
    TrustedDevice,
    User,
    UserSession,
)
from tests.helpers import PASSWORD, invite, password_login, register_user

ADMIN = "admin@example.test"
MEMBER = "member@example.test"


async def count(db, model, *where) -> int:
    return await db.scalar(select(func.count()).select_from(model).where(*where))


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
            platform="linux",
            version="1.2.3",
            filename="private-gateway_1.2.3_amd64.deb",
            storage_name=storage_name,
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
        )
    )
    await db.commit()


async def test_admin_deletes_a_member_with_everything_except_the_download_log(
    clients, db, totp_clock, release
):
    admin_browser = await clients(ip="198.51.100.120")
    admin = await register_user(admin_browser, db, ADMIN, role="admin")
    browser = await clients(ip="203.0.113.120")
    member = await register_user(browser, db, MEMBER)
    member_id = member["user"]["id"]
    assert (await browser.get("/api/downloads/linux/file")).status_code == 200
    app = await clients(csrf=False, ip="203.0.113.121")
    login = await app.post(
        "/api/app/login",
        json={
            "email": MEMBER,
            "password": PASSWORD,
            "device": {
                "uid": "install-rrrrrrrrrrrrrr01",
                "name": "Laptop",
                "platform": "linux",
                "app_version": "0.2.0",
            },
        },
    )
    token = login.json()["token"]
    reset = await admin_browser.post(
        f"/api/admin/members/{member_id}/reset-code", json={"code": totp_clock(admin)}
    )
    assert reset.status_code == 200
    # Без кода 2FA и участнику удаление недоступно
    assert (
        await browser.post(f"/api/admin/members/{member_id}/delete", json={"code": "123456"})
    ).status_code == 403
    bad = await admin_browser.post(f"/api/admin/members/{member_id}/delete", json={})
    assert bad.status_code == 422
    wrong = await admin_browser.post(
        f"/api/admin/members/{member_id}/delete", json={"code": "000000"}
    )
    assert wrong.status_code == 400 and wrong.json()["error"]["code"] == "invalid_code"
    assert await count(db, User, User.id == member_id) == 1
    deleted = await admin_browser.post(
        f"/api/admin/members/{member_id}/delete", json={"code": totp_clock(admin)}
    )
    assert deleted.status_code == 204, deleted.text
    assert await count(db, User, User.id == member_id) == 0
    for model in (UserSession, TrustedDevice, LoginChallenge, RecoveryCode, AppDevice):
        assert await count(db, model, model.user_id == member_id) == 0, model
    assert await count(db, AccessCode, AccessCode.email == MEMBER) == 0
    # Скачивание осталось в журнале без участника
    events = (await db.scalars(select(DownloadEvent))).all()
    assert len(events) == 1 and events[0].user_id is None
    log = (await admin_browser.get("/api/admin/downloads")).json()
    assert log["items"][0]["user"] is None
    audit = (
        await db.scalars(select(AuditEvent).where(AuditEvent.action == "member.deleted"))
    ).one()
    assert (audit.actor_id, audit.target_id) == (admin["user"]["id"], member_id)
    # Вход, приложение и повторное удаление больше ничего не находят
    assert (await browser.get("/api/me")).status_code == 401
    status = await app.get("/api/app/status", headers={"Authorization": f"Bearer {token}"})
    assert status.status_code == 401
    assert (await password_login(browser)).status_code == 401
    again = await admin_browser.post(
        f"/api/admin/members/{member_id}/delete", json={"code": totp_clock(admin)}
    )
    assert again.status_code == 404
    # Адрес свободен для нового приглашения
    created = await admin_browser.post(
        "/api/admin/invites",
        json={"email": MEMBER, "role": "member", "expires_in_days": 1, "code": totp_clock(admin)},
    )
    assert created.status_code == 201


async def test_admin_cannot_delete_self_and_deleted_admin_leaves_others(clients, db, totp_clock):
    first_browser = await clients(ip="198.51.100.121")
    first = await register_user(first_browser, db, ADMIN, role="admin")
    second_browser = await clients(ip="198.51.100.122")
    second = await register_user(second_browser, db, "second-admin@example.test", role="admin")
    own = await first_browser.post(
        f"/api/admin/members/{first['user']['id']}/delete", json={"code": totp_clock(first)}
    )
    assert own.status_code == 400
    assert own.json()["error"]["code"] == "self_change_forbidden"
    assert await count(db, User) == 2
    # Созданное удаленным администратором приглашение остается, без автора
    created = await second_browser.post(
        "/api/admin/invites",
        json={
            "email": "third@example.test",
            "role": "member",
            "expires_in_days": 1,
            "code": totp_clock(second),
        },
    )
    assert created.status_code == 201
    deleted = await first_browser.post(
        f"/api/admin/members/{second['user']['id']}/delete", json={"code": totp_clock(first)}
    )
    assert deleted.status_code == 204
    assert (await second_browser.get("/api/me")).status_code == 401
    kept = (
        await db.scalars(select(AccessCode).where(AccessCode.email == "third@example.test"))
    ).one()
    assert kept.created_by is None
    assert (await first_browser.get("/api/admin/members")).json()["total"] == 1


async def test_admin_deletes_invitations_in_any_state(clients, db, totp_clock):
    from datetime import UTC, datetime, timedelta

    browser = await clients(ip="198.51.100.123")
    admin = await register_user(browser, db, ADMIN, role="admin")
    active_code, active = await invite(db, "active@example.test")
    _, expired = await invite(
        db, "expired@example.test", expires_at=datetime.now(UTC) - timedelta(days=1)
    )
    _, revoked = await invite(db, "revoked@example.test", revoked_at=datetime.now(UTC))
    member_browser = await clients(ip="203.0.113.123")
    assert (
        await member_browser.post(f"/api/admin/invites/{active.id}/delete", json={"code": "123456"})
    ).status_code == 401
    await register_user(member_browser, db, "member-two@example.test")
    forbidden = await member_browser.post(
        f"/api/admin/invites/{active.id}/delete", json={"code": "123456"}
    )
    assert forbidden.status_code == 403
    for row in (active, expired, revoked):
        response = await browser.post(
            f"/api/admin/invites/{row.id}/delete", json={"code": totp_clock(admin)}
        )
        assert response.status_code == 204, response.text
    listing = (await browser.get("/api/admin/invites")).json()
    emails = [item["email"] for item in listing["items"]]
    assert "active@example.test" not in emails and "expired@example.test" not in emails
    # Удаленное действующее приглашение не регистрирует
    anonymous = await clients(ip="203.0.113.124")
    from tests.helpers import registration

    response = await anonymous.post(
        "/api/auth/register", json=registration(active_code, "active@example.test")
    )
    assert response.status_code == 400
    missing = await browser.post(
        f"/api/admin/invites/{active.id}/delete", json={"code": totp_clock(admin)}
    )
    assert missing.status_code == 404
    actions = (await db.scalars(select(AuditEvent.action))).all()
    assert actions.count("invite.deleted") == 3


async def test_demoted_admin_loses_two_factor_and_signs_in_with_password(clients, db, totp_clock):
    first_browser = await clients(ip="198.51.100.124")
    first = await register_user(first_browser, db, ADMIN, role="admin")
    second_browser = await clients(ip="198.51.100.125")
    second = await register_user(second_browser, db, "second-admin@example.test", role="admin")
    second_id = second["user"]["id"]
    assert await count(db, RecoveryCode, RecoveryCode.user_id == second_id) == 8
    demoted = await first_browser.patch(
        f"/api/admin/members/{second_id}", json={"role": "member", "code": totp_clock(first)}
    )
    assert demoted.status_code == 200, demoted.text
    assert demoted.json()["totp_enabled"] is False
    user = await db.get(User, second_id, populate_existing=True)
    assert user.totp_secret_enc is None and user.totp_last_step is None
    assert await count(db, RecoveryCode, RecoveryCode.user_id == second_id) == 0
    assert await count(db, TrustedDevice, TrustedDevice.user_id == second_id) == 0
    # Смена роли завершает сеансы; новый вход — по паролю, без 2FA
    assert (await second_browser.get("/api/me")).status_code == 401
    login = await password_login(second_browser, "second-admin@example.test")
    assert login.json()["status"] == "ok"
    assert (await second_browser.get("/api/admin/members")).status_code == 403


async def test_promoted_member_sets_up_two_factor_before_administration(clients, db, totp_clock):
    from app.core.security import totp

    admin_browser = await clients(ip="198.51.100.126")
    admin = await register_user(admin_browser, db, ADMIN, role="admin")
    browser = await clients(ip="203.0.113.126")
    member = await register_user(browser, db)
    promoted = await admin_browser.patch(
        f"/api/admin/members/{member['user']['id']}",
        json={"role": "admin", "code": totp_clock(admin)},
    )
    assert promoted.status_code == 200
    assert (await browser.get("/api/me")).status_code == 401
    login = await password_login(browser)
    assert login.json()["status"] == "totp_setup_required"
    # Без настройки ни кабинета, ни приложения
    assert (await browser.get("/api/admin/members")).status_code == 401
    app = await clients(csrf=False, ip="203.0.113.127")
    refused = await app.post(
        "/api/app/login",
        json={
            "email": MEMBER,
            "password": PASSWORD,
            "code": "123456",
            "device": {
                "uid": "install-ssssssssssssss01",
                "name": "Laptop",
                "platform": "linux",
                "app_version": "0.2.0",
            },
        },
    )
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "setup_required"
    setup = (await browser.post("/api/auth/2fa/setup", json={})).json()
    done = await browser.post(
        "/api/auth/2fa/setup/confirm",
        json={"code": totp.code_at_step(setup["secret"], totp.current_step())},
    )
    assert done.status_code == 200
    assert (await browser.get("/api/admin/members")).status_code == 200


async def test_admin_routes_require_configured_two_factor(clients, db, monkeypatch):
    """Второй рубеж: даже если сеанс у администратора без 2FA есть, /admin/* закрыты."""
    from app.services import auth

    browser = await clients(ip="198.51.100.127")
    await register_user(browser, db, ADMIN, role="admin")
    user = await db.scalar(select(User).where(User.email == ADMIN))
    original = auth.current_user

    async def without_two_factor(session, request, **kwargs):
        found = await original(session, request, **kwargs)
        found.totp_enabled = False
        return found

    monkeypatch.setattr(auth, "current_user", without_two_factor)
    for path in ("/api/admin/members", "/api/admin/invites", "/api/admin/downloads"):
        response = await browser.get(path)
        assert response.status_code == 403, path
        assert response.json()["error"]["code"] == "setup_required"
    assert user.role == "admin"
