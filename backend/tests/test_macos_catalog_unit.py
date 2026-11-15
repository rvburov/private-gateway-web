"""Выбор установщика и отказ без файла — без внешней БД; HTTP/SQL сценарии в test_downloads."""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import Request

from app.api.schemas import DownloadsOut
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import AppUpdate, Release
from app.services import downloads, updates


@pytest.fixture
def mac_store(tmp_path, monkeypatch):
    monkeypatch.setenv("PGWEB_DATABASE_URL", "postgresql+asyncpg://test@localhost/unit_test")
    monkeypatch.setenv("PGWEB_DOWNLOAD_ROOT", str(tmp_path))
    get_settings.cache_clear()
    artifacts = {}
    for arch in ("arm64", "x64"):
        payload = f"Installer for {arch}, test bytes only".encode()
        digest = hashlib.sha256(payload).hexdigest()
        path = tmp_path / f"{digest}.bin"
        path.write_bytes(payload)
        artifacts[arch] = {
            "file": f"Client-1.2.3-{arch}.dmg",
            "sha256": digest,
            "size": len(payload),
        }
    arm = artifacts["arm64"]
    release = Release(
        platform="macos",
        version="1.2.3",
        enabled=True,
        filename=arm["file"],
        size_bytes=arm["size"],
        sha256=arm["sha256"],
        storage_name=arm["sha256"] + ".bin",
    )
    update = AppUpdate(
        version="1.2.3",
        channel="stable",
        rollout=100,
        manifest=json.dumps(
            {
                "assets": {
                    "osx-x64-dmg": artifacts["x64"],
                }
            }
        ).encode(),
    )
    db = SimpleNamespace(
        get=AsyncMock(return_value=update),
        scalar=AsyncMock(return_value=release),
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [release])),
        add=Mock(),
        commit=AsyncMock(),
    )
    monkeypatch.setattr(downloads, "current_user", AsyncMock(return_value=SimpleNamespace(id=7)))
    request = Request({"type": "http", "headers": [], "client": ("192.0.2.18", 1234)})
    yield db, release, update, artifacts, request
    get_settings.cache_clear()


async def test_exact_architecture_file_and_log_are_preserved(mac_store):
    db, _, _, artifacts, request = mac_store
    listing = await downloads.catalog(db, request)
    # Проверяет, что новый ответ проходит реальную схему API и не теряет варианты.
    mac = next(x for x in DownloadsOut.model_validate(listing).items if x.platform == "macos")
    assert mac.filename == artifacts["arm64"]["file"]
    assert [x.architecture for x in mac.variants] == ["arm64", "x64"]
    assert mac.variants[1].url == "/api/downloads/macos/file?architecture=x64"
    for arch, query in (("arm64", None), ("x64", "x64")):
        response = await downloads.download(db, request, "macos", query)
        payload = b"".join([chunk async for chunk in response.body_iterator])
        assert hashlib.sha256(payload).hexdigest() == artifacts[arch]["sha256"]
        assert db.add.call_args.args[0].filename == artifacts[arch]["file"]
        assert response.headers["content-type"] == "application/x-apple-diskimage"
    db.get.assert_awaited_with(AppUpdate, "1.2.3")


@pytest.mark.parametrize("reason", ["old", "stopped", "beta", "missing", "symlink"])
async def test_intel_unavailable_cannot_return_arm_bytes(mac_store, tmp_path, reason):
    db, _, update, artifacts, request = mac_store
    path = tmp_path / f"{artifacts['x64']['sha256']}.bin"
    if reason == "old":
        db.get.return_value = None
    elif reason == "stopped":
        update.rollout = 0
    elif reason == "beta":
        update.channel = "beta"
    elif reason == "missing":
        path.unlink()
    else:
        outside = tmp_path.parent / f"{tmp_path.name}-outside.dmg"
        outside.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(outside)
    listing = await downloads.catalog(db, request)
    mac = next(x for x in listing["items"] if x["platform"] == "macos")
    assert mac["available"] is True
    assert mac["variants"][1]["available"] is False
    assert mac["variants"][1]["url"] is None
    with pytest.raises(AppError) as error:
        await downloads.download(db, request, "macos", "x64")
    assert error.value.status == 404
    db.add.assert_not_called()


async def test_new_intel_path_keeps_the_session_guard(mac_store, monkeypatch):
    db, _, _, _, request = mac_store
    monkeypatch.setattr(downloads, "current_user", AsyncMock(side_effect=AppError(401, "login")))
    status = 200
    try:
        await downloads.download(db, request, "macos", "x64")
    except AppError as error:
        status = error.status
    assert status == 401
    db.scalar.assert_not_called()
    db.get.assert_not_called()


def test_feed_indexes_both_mac_kinds_and_validates_metadata():
    asset = {"file": "Client-x64.dmg", "sha256": "a" * 64, "size": 100}
    assert set(updates.PLATFORM_KINDS["macos"]) == {"osx-arm64-dmg", "osx-x64-dmg"}
    manifest = json.dumps({"assets": {"osx-x64-dmg": asset}}).encode()
    assert updates._assets(manifest) == {"osx-x64-dmg": asset}
    for invalid in (
        asset | {"file": "../escape.dmg"},
        asset | {"size": True},
        asset | {"sha256": "invalid"},
    ):
        manifest = json.dumps({"assets": {"osx-x64-dmg": invalid}}).encode()
        assert updates._assets(manifest) == {}
