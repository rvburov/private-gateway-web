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


async def test_android_package_is_served_for_the_phone_installer(client, db, download_root):
    """APK: тип для установщика Android, имя с .apk, точный размер, без сжатия и кеша."""
    await register_user(client, db)
    payload = b"PK\x03\x04 Private Gateway test package, not an application" * 64
    storage_name = hashlib.sha256(payload).hexdigest() + ".bin"
    (download_root / storage_name).write_bytes(payload)
    db.add(
        Release(
            platform="android",
            version="0.2.0",
            filename="PrivateGateway-0.2.0-android.apk",
            storage_name=storage_name,
            size_bytes=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
        )
    )
    await db.commit()
    response = await client.get(
        "/api/downloads/android/file", headers={"Accept-Encoding": "gzip, br, zstd"}
    )
    assert response.status_code == 200 and response.content == payload
    headers = response.headers
    assert headers["content-type"] == "application/vnd.android.package-archive"
    assert headers["content-disposition"] == (
        'attachment; filename="PrivateGateway-0.2.0-android.apk"; '
        "filename*=UTF-8''PrivateGateway-0.2.0-android.apk"
    )
    assert headers["content-length"] == str(len(payload))
    assert "content-encoding" not in headers
    assert headers.get_list("cache-control") == ["no-store"]
    assert headers.get_list("x-content-type-options") == ["nosniff"]
    assert headers["x-checksum-sha256"] == hashlib.sha256(payload).hexdigest()


def test_download_names_keep_the_extension_for_every_platform():
    from app.services.downloads import content_disposition, media_type

    assert media_type("PrivateGateway.APK") == "application/vnd.android.package-archive"
    assert media_type("PrivateGateway-1.2.3-win-x64.msi") == "application/x-msi"
    assert media_type("PrivateGateway-1.2.3-osx-arm64.dmg") == "application/x-apple-diskimage"
    assert media_type("private-gateway_1.2.3_amd64.deb") == "application/vnd.debian.binary-package"
    assert media_type("archive.tar.gz") == "application/octet-stream"
    header = content_disposition("Клиент 1.0 «тест».apk")
    assert header.startswith('attachment; filename="')
    fallback = header.split('"')[1]
    assert fallback.endswith(".apk") and fallback.isascii() and '"' not in fallback
    assert "filename*=UTF-8''%D0%9A" in header
    assert content_disposition('..\\evil".apk').split('"')[1] == "_evil_.apk"
