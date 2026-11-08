"""Роль администратора проверяет сервер, отзыв закрывает уже выданные сеансы."""

from app.core.security import tokens
from app.db.models import AccessCode, User
from tests.helpers import PASSWORD, password_login, register_user


async def test_member_cannot_administer_even_by_direct_request(client, db):
    user = await register_user(client, db)
    assert (await client.get("/api/admin/members")).status_code == 403
    assert (await client.get("/api/admin/invites")).status_code == 403
    body = {"email": "new@example.test", "role": "admin", "expires_in_days": 7, "code": "123456"}
    assert (await client.post("/api/admin/invites", json=body)).status_code == 403
    assert (
        await client.patch(
            f"/api/admin/members/{user['user']['id']}", json={"role": "admin", "code": "123456"}
        )
    ).status_code == 403


async def test_admin_invite_returns_secret_only_once(client, db, totp_clock):
    admin = await register_user(client, db, "admin@example.test", role="admin")
    response = await client.post(
        "/api/admin/invites",
        json={
            "email": "invited@example.test",
            "role": "member",
            "expires_in_days": 3,
            "code": totp_clock(admin),
        },
    )
    assert response.status_code in (200, 201), response.text
    body = response.json()
    raw = body["code"]
    assert raw.startswith("PG-")
    listing = await client.get("/api/admin/invites")
    assert listing.status_code == 200
    assert raw not in listing.text
    invite = await db.get(AccessCode, body["invite"]["id"])
    assert invite.code_hash == tokens.hash_code(raw, prefix="PG")
    assert raw not in repr(invite.__dict__)


async def test_admin_action_rejects_wrong_and_replayed_factor(client, db, totp_clock):
    admin = await register_user(client, db, "admin@example.test", role="admin")
    payload = {
        "email": "one@example.test",
        "role": "member",
        "expires_in_days": 3,
        "code": "not-a-code",
    }
    bad = await client.post("/api/admin/invites", json=payload)
    assert bad.status_code in (400, 422)
    payload["code"] = totp_clock(admin)
    first = await client.post("/api/admin/invites", json=payload)
    assert first.status_code in (200, 201), first.text
    payload["email"] = "two@example.test"
    repeat = await client.post("/api/admin/invites", json=payload)
    assert repeat.status_code == 400
    assert repeat.json()["error"]["code"] == "invalid_code"


async def test_access_revocation_is_immediate_and_does_not_resurrect_sessions(
    client,
    clients,
    db,
    totp_clock,
):
    admin = await register_user(client, db, "admin@example.test", role="admin")
    browser = await clients(ip="192.0.2.21")
    member = await register_user(browser, db)
    assert (await browser.get("/api/downloads")).status_code == 200
    path = f"/api/admin/members/{member['user']['id']}"
    blocked = await client.patch(path, json={"status": "blocked", "code": totp_clock(admin)})
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["status"] == "blocked"
    assert (await browser.get("/api/me")).status_code == 401
    assert (await browser.get("/api/downloads/windows/file")).status_code == 401
    unblocked = await client.patch(path, json={"status": "active", "code": totp_clock(admin)})
    assert unblocked.status_code == 200, unblocked.text
    assert (await browser.get("/api/me")).status_code == 401
    relogin = await password_login(browser)
    assert relogin.status_code == 200 and relogin.json()["status"] == "totp_required"


async def test_admin_cannot_remove_own_access(client, db, totp_clock):
    admin = await register_user(client, db, "admin@example.test", role="admin")
    response = await client.patch(
        f"/api/admin/members/{admin['user']['id']}",
        json={
            "status": "blocked",
            "code": totp_clock(admin),
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "self_change_forbidden"
    assert (await client.get("/api/me")).status_code == 200


async def test_reset_code_is_one_use_revokes_sessions_and_preserves_two_factor(
    client,
    clients,
    db,
    totp_clock,
):
    admin = await register_user(client, db, "admin@example.test", role="admin")
    browser = await clients(ip="192.0.2.22")
    member = await register_user(browser, db)
    response = await client.post(
        f"/api/admin/members/{member['user']['id']}/reset-code", json={"code": totp_clock(admin)}
    )
    assert response.status_code in (200, 201), response.text
    code = response.json()["code"]
    new_password = "new-gateway-test-password"
    body = {"email": "member@example.test", "code": code, "new_password": new_password}
    reset = await browser.post("/api/auth/reset", json=body)
    assert reset.status_code == 200, reset.text
    assert (await browser.get("/api/me")).status_code == 401
    assert (await browser.post("/api/auth/reset", json=body)).status_code == 400
    assert (await password_login(browser, password=PASSWORD)).status_code == 401
    login = await password_login(browser, password=new_password)
    assert login.status_code == 200 and login.json()["status"] == "totp_required"
    fresh = await db.get(User, member["user"]["id"], populate_existing=True)
    assert fresh.totp_enabled


async def test_two_admins_cannot_revoke_each_other_with_stale_sessions(
    client,
    clients,
    db,
    totp_clock,
    monkeypatch,
):
    import asyncio
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func, select, update

    from app.db.models import UserSession

    first = await register_user(client, db, "first-admin@example.test", role="admin")
    second_browser = await clients(ip="192.0.2.24")
    second = await register_user(second_browser, db, "second-admin@example.test", role="admin")
    # current_user обновляет старый last_seen. Эта запись не должна снимать
    # транзакционную блокировку проверки последнего администратора.
    await db.execute(
        update(UserSession).values(
            last_seen_at=datetime.now(UTC) - timedelta(minutes=6),
        )
    )
    await db.commit()
    first_code, second_code = totp_clock(first), totp_clock(second)
    from app.services import auth

    original = auth.current_user
    reached = 0
    both_checked = asyncio.Event()

    async def synchronize_current_user(session, request, **kwargs):
        nonlocal reached
        actor = await original(session, request, **kwargs)
        if kwargs.get("touch") is False:
            return actor
        reached += 1
        if reached == 2:
            both_checked.set()
        await asyncio.wait_for(both_checked.wait(), timeout=5)
        return actor

    monkeypatch.setattr(auth, "current_user", synchronize_current_user)
    responses = await asyncio.gather(
        client.patch(
            f"/api/admin/members/{second['user']['id']}",
            json={
                "status": "blocked",
                "code": first_code,
            },
        ),
        second_browser.patch(
            f"/api/admin/members/{first['user']['id']}",
            json={
                "status": "blocked",
                "code": second_code,
            },
        ),
    )
    statuses = sorted(response.status_code for response in responses)
    assert statuses in ([200, 401], [200, 403]), [r.text for r in responses]
    count = await db.scalar(
        select(func.count())
        .select_from(User)
        .where(
            User.role == "admin",
            User.status == "active",
        )
    )
    assert count == 1
