"""Проверки CSRF применяются до любых изменений или проверок пароля."""

import pytest


@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE"])
async def test_mutations_require_csrf(clients, method):
    client = await clients(csrf=False)
    response = await client.request(method, "/api/auth/logout", json={})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"


@pytest.mark.parametrize(
    "headers",
    [
        {"X-CSRF-Token": "different"},
        {"X-CSRF-Token": ""},
        {"Origin": "https://attacker.example"},
        {"Origin": "null"},
    ],
)
async def test_wrong_csrf_or_origin_rejected(client, headers):
    response = await client.post("/api/auth/logout", json={}, headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_failed"


async def test_csrf_is_stable_for_multiple_tabs_and_get_is_uncached(client):
    first = await client.get("/api/auth/csrf")
    second = await client.get("/api/auth/csrf")
    assert first.json()["csrf_token"] == second.json()["csrf_token"]
    assert "no-store" in second.headers["cache-control"]
    assert (await client.post("/api/auth/logout", json={})).status_code == 204


async def test_validation_response_does_not_echo_password(client):
    sentinel = "must-not-appear-in-validation-response"
    response = await client.post("/api/auth/register", json={"password": sentinel})
    assert response.status_code == 422
    assert sentinel not in response.text
    assert response.json()["error"]["code"] == "validation_error"


async def test_private_routes_are_not_public(client):
    for path in (
        "/api/me",
        "/api/downloads",
        "/api/downloads/windows/file",
        "/api/admin/members",
        "/api/admin/invites",
    ):
        response = await client.get(path)
        assert response.status_code == 401, (path, response.text)
