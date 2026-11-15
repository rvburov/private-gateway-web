"""Файлы закрыты авторизацией; разрешенное имя не дает выйти из каталога выпусков."""

import hashlib
import json

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import AppUpdate, DownloadEvent, Release, utcnow
from tests.helpers import register_user


@pytest.fixture
async def download_root(tmp_path, monkeypatch):
    root = tmp_path / "releases"
    root.mkdir()
    monkeypatch.setenv("PGWEB_DOWNLOAD_ROOT", str(root))
    get_settings.cache_clear()
    return root


@pytest.fixture
async def macos_catalog(client, db, download_root):
    await register_user(client, db)
    files = {}
    for architecture in ("arm64", "x64"):
        payload = f"Test macOS {architecture} installer, not an application".encode()
        digest = hashlib.sha256(payload).hexdigest()
        (download_root / f"{digest}.bin").write_bytes(payload)
        files[architecture] = {
            "file": f"PrivateGateway-1.2.3-osx-{architecture}.dmg",
            "sha256": digest,
            "size": len(payload),
        }
    arm = files["arm64"]
    release = Release(
        platform="macos",
        version="1.2.3",
        filename=arm["file"],
        storage_name=arm["sha256"] + ".bin",
        size_bytes=arm["size"],
        sha256=arm["sha256"],
    )
    update = AppUpdate(
        version="1.2.3",
        channel="stable",
        rollout=100,
        published_at=utcnow(),
        manifest=json.dumps({"assets": {"osx-x64-dmg": files["x64"]}}).encode(),
        signature="dGVzdA==",
    )
    db.add_all([release, update])
    await db.commit()
    return release, update, files


async def test_macos_catalog_downloads_each_chip_with_its_own_bytes_and_log(
    client,
    clients,
    db,
    download_root,
    macos_catalog,
):
    _, _, files = macos_catalog
    mac = next(
        x for x in (await client.get("/api/downloads")).json()["items"] if x["platform"] == "macos"
    )
    assert mac["url"] == "/api/downloads/macos/file"
    assert mac["filename"] == files["arm64"]["file"]
    variants = {x["architecture"]: x for x in mac["variants"]}
    assert set(variants) == {"arm64", "x64"}
    anonymous = await clients(csrf=False)
    for architecture, variant in variants.items():
        asset = files[architecture]
        assert variant["available"] is True
        assert variant["filename"] == asset["file"]
        assert (await anonymous.get(variant["url"])).status_code == 401
        response = await client.get(variant["url"])
        assert response.status_code == 200
        assert response.content == (download_root / f"{asset['sha256']}.bin").read_bytes()
        assert response.headers["x-checksum-sha256"] == asset["sha256"]
        assert asset["file"] in response.headers["content-disposition"]
    events = (await db.scalars(select(DownloadEvent).order_by(DownloadEvent.id))).all()
    assert [(x.platform, x.filename) for x in events] == [
        ("macos", files["arm64"]["file"]),
        ("macos", files["x64"]["file"]),
    ]


@pytest.mark.parametrize("reason", ["old", "stopped", "beta", "missing", "size", "symlink"])
async def test_unavailable_intel_is_not_listed_or_replaced_with_arm(
    client,
    db,
    download_root,
    macos_catalog,
    reason,
):
    _, update, files = macos_catalog
    intel_path = download_root / f"{files['x64']['sha256']}.bin"
    if reason == "old":
        update.version = "1.2.2"  # Не брать Intel от другой версии текущего каталога.
    elif reason == "stopped":
        update.rollout = 0
    elif reason == "beta":
        update.channel = "beta"
    elif reason == "missing":
        intel_path.unlink()
    elif reason == "size":
        intel_path.write_bytes(b"short")
    elif reason == "symlink":
        outside = download_root.parent / "outside-intel.dmg"
        outside.write_bytes(intel_path.read_bytes())
        intel_path.unlink()
        intel_path.symlink_to(outside)
    await db.commit()
    mac = next(
        x for x in (await client.get("/api/downloads")).json()["items"] if x["platform"] == "macos"
    )
    arm, intel = mac["variants"]
    assert arm["available"] is True
    assert intel["available"] is False
    assert intel["url"] is None and intel["version"] is None
    assert (await client.get("/api/downloads/macos/file?architecture=x64")).status_code == 404
    assert (await client.get("/api/downloads/macos/file")).status_code == 200


async def test_disabled_mac_release_and_invalid_architecture_have_no_download(
    client,
    db,
    macos_catalog,
):
    release, _, _ = macos_catalog
    for url in (
        "/api/downloads/windows/file?architecture=x64",
        "/api/downloads/macos/file?architecture=unknown",
    ):
        assert (await client.get(url)).status_code == 404
    release.enabled = False
    await db.commit()
    mac = next(
        x for x in (await client.get("/api/downloads")).json()["items"] if x["platform"] == "macos"
    )
    assert all(not variant["available"] for variant in mac["variants"])
    assert (await client.get("/api/downloads/macos/file?architecture=x64")).status_code == 404


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
