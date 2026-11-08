"""Файлы закрыты авторизацией; разрешенное имя не дает выйти из каталога выпусков."""

import hashlib

import pytest

from app.core.config import get_settings
from app.db.models import Release
from tests.helpers import register_user


@pytest.fixture
async def download_root(tmp_path, monkeypatch):
    root = tmp_path / "releases"
    root.mkdir()
    monkeypatch.setenv("PGWEB_DOWNLOAD_ROOT", str(root))
    get_settings.cache_clear()
    return root


async def test_empty_catalog_does_not_invent_versions_or_urls(client, db):
    await register_user(client, db)
    response = await client.get("/api/downloads")
    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["platform"] for item in items] == ["windows", "macos", "ios", "linux", "android"]
    for item in items:
        assert item["available"] is False
        assert item["version"] is None and item["url"] is None
    assert (await client.get("/api/downloads/windows/file")).status_code == 404


async def test_file_requires_session_and_returns_registered_bytes(
    client, clients, db, download_root
):
    await register_user(client, db)
    payload = b"Private Gateway test release bytes, not an application"
    storage_name = hashlib.sha256(payload).hexdigest() + ".bin"
    (download_root / storage_name).write_bytes(payload)
    db.add(
        Release(
            platform="windows",
            version="0.0.0-test",
            filename="sample.bin",
            storage_name=storage_name,
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
        )
    )
    await db.commit()
    listing = (await client.get("/api/downloads")).json()["items"]
    windows = next(item for item in listing if item["platform"] == "windows")
    assert windows["available"] is True
    assert windows["url"] == "/api/downloads/windows/file"
    anonymous = await clients(csrf=False, ip="192.0.2.23")
    assert (await anonymous.get(windows["url"])).status_code == 401
    response = await client.get(windows["url"])
    assert response.status_code == 200 and response.content == payload
    assert "attachment" in response.headers["content-disposition"]
    assert "no-store" in response.headers["cache-control"]


@pytest.mark.parametrize("escape", ["parent", "symlink"])
async def test_file_path_and_symlink_cannot_escape_release_root(
    client,
    db,
    download_root,
    escape,
):
    await register_user(client, db)
    secret_file = download_root.parent / "outside.bin"
    secret_file.write_bytes(b"test-only-private-fixture")
    if escape == "parent":
        storage_name = "../outside.bin"
    else:
        storage_name = "a" * 64 + ".bin"
        (download_root / storage_name).symlink_to(secret_file)
    db.add(
        Release(
            platform="windows",
            version="0.0.0-test",
            filename="release.bin",
            storage_name=storage_name,
            size_bytes=24,
            sha256="0" * 64,
        )
    )
    await db.commit()
    response = await client.get("/api/downloads/windows/file")
    assert response.status_code == 404
    assert secret_file.read_bytes() not in response.content
