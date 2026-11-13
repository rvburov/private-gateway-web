"""Лента обновлений программы: прием манифеста (cli publish-update), лента по токену устройства
и файлы по билету.

Манифест — как у scripts/release.cs клиента: отступы, перевод строки в конце, текст заметок.
Сайт хранит и отдает его байт в байт; подпись проверяет программа, а не сайт.
"""

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app import cli
from app.core.config import get_settings
from app.core.security.tokens import sign
from app.db.models import AppDevice, AppUpdate, DownloadEvent, Release, utcnow
from app.services import updates
from tests.helpers import PASSWORD, register_user

NAMES = {
    "win-x64-msi": "PrivateGateway-{v}-win-x64.msi",
    "win-x64-zip": "PrivateGateway-{v}-win-x64.zip",
    "linux-x64-deb": "private-gateway_{v}_amd64.deb",
    "linux-x64-rpm": "private-gateway-{v}-1.x86_64.rpm",
    "linux-x64-tar": "PrivateGateway-{v}-linux-x64.tar.gz",
    "osx-arm64-tar": "PrivateGateway-{v}-osx-arm64.tar.gz",
    "osx-arm64-dmg": "PrivateGateway-{v}-osx-arm64.dmg",
    "android-apk": "PrivateGateway-{v}-android.apk",
}
FEED = {
    "windows": {"win-x64-msi"},
    "macos": {"osx-arm64-dmg"},
    "linux": {"linux-x64-deb", "linux-x64-rpm"},
    "android": {"android-apk"},
}
SIGNATURE = base64.b64encode(b"0D\x02 " + bytes(range(32)) + b"\x02 " + bytes(range(32, 64)))
FILES_URL = "http://testserver/api/app/updates/files/"


@pytest.fixture
def store(tmp_path, monkeypatch):
    root = tmp_path / "releases"
    root.mkdir()
    monkeypatch.setenv("PGWEB_DOWNLOAD_ROOT", str(root))
    get_settings.cache_clear()
    return root


def assets(root, version: str, kinds=tuple(NAMES), *, stored=True) -> dict:
    """Файлы выпуска для манифеста; stored — уже приняты на сайт (лежат в хранилище)."""
    result = {}
    for kind in kinds:
        payload = f"Private Gateway {version} {kind}: test bytes, not an application\n".encode()
        payload *= 50
        sha256 = hashlib.sha256(payload).hexdigest()
        if stored:
            (root / f"{sha256}.bin").write_bytes(payload)
        name = NAMES[kind].format(v=version)
        result[kind] = {"file": name, "sha256": sha256, "size": len(payload)}
    return result


def manifest(
    version: str,
    files: dict,
    *,
    rollout: int = 20,
    channel: str = "stable",
    highlights: tuple[str, ...] = ("Обновления приходят с сайта.", "Подпись проверяет программа."),
) -> bytes:
    data = {
        "version": version,
        "channel": channel,
        "rollout": rollout,
        "published": "2026-11-13T09:30:00Z",
        "notes": "https://private-gateway.duckdns.org/downloads",
        "highlights": list(highlights),
        "assets": files,
    }
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode()


def sized(version: str, files: dict, size: int) -> bytes:
    """Верный манифест ровно size байт: длинная строка заметок, в конце «}» и перевод строки."""
    padding = size - len(manifest(version, files, highlights=("",)))
    data = manifest(version, files, highlights=("x" * padding,))
    assert len(data) == size and data.endswith(b"}\n")
    return data


async def publish(tmp_path, version: str, data: bytes, signature: bytes = SIGNATURE + b"\n"):
    """Как import-release.sh update: файлы в папке приема, затем cli publish-update."""
    (tmp_path / "update.json").write_bytes(data)
    (tmp_path / "update.json.sig").write_bytes(signature)
    args = cli.parser().parse_args(
        [
            "publish-update",
            "--version",
            version,
            "--manifest",
            str(tmp_path / "update.json"),
            "--signature",
            str(tmp_path / "update.json.sig"),
        ]
    )
    await cli.run(args)


async def outcome(tmp_path, version: str, data: bytes, signature: bytes = SIGNATURE) -> str:
    """Итог publish-update: "accepted" или причина отказа (тест сверяет его assert)."""
    try:
        await publish(tmp_path, version, data, signature)
    except ValueError as error:
        return str(error)
    return "accepted"


async def refused(tmp_path, version: str, data: bytes, signature: bytes = SIGNATURE) -> str:
    """Причина отказа publish-update; принятый манифест — ошибка теста."""
    reason = await outcome(tmp_path, version, data, signature)
    assert reason != "accepted", f"publish-update accepted {version}"
    return reason


async def member_device(clients, db, *, email="member@example.test", uids=("install-0000000001",)):
    """Участник и его устройства с приложением: токен на каждое."""
    browser = await clients(ip="192.0.2.80")
    user = await register_user(browser, db, email)
    app = await clients(csrf=False, ip="203.0.113.57")
    app.headers.pop("Origin")
    tokens = []
    for uid in uids:
        device = {"uid": uid, "name": "Test laptop", "platform": "windows", "app_version": "0.3.0"}
        login = await app.post(
            "/api/app/login", json={"email": email, "password": PASSWORD, "device": device}
        )
        assert login.status_code == 200, login.text
        tokens.append(login.json()["token"])
    return browser, user, app, tokens


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def feed(app, token: str, platform: str = "windows", channel: str = "stable"):
    response = await app.get(
        "/api/app/updates",
        params={"platform": platform, "channel": channel},
        headers=bearer(token),
    )
    assert response.status_code == 200, response.text
    return response.json()["releases"]


def ticket_of(url: str) -> str:
    assert url.startswith(FILES_URL), url
    return url.removeprefix(FILES_URL)


# --- Лента: доступ, содержимое, порядок ---


async def test_feed_needs_an_active_device_token_and_does_not_renew_it(clients, db):
    browser, _, app, (token,) = await member_device(clients, db)
    assert (await app.get("/api/app/updates", params={"platform": "windows"})).status_code == 401
    wrong = await app.get("/api/app/updates?platform=windows", headers=bearer("x" * 43))
    assert wrong.status_code == 401
    # Cookie сайта не заменяет токен устройства
    assert (await browser.get("/api/app/updates?platform=windows")).status_code == 401
    before = await db.scalar(select(AppDevice.expires_at))
    assert await feed(app, token) == []
    db.expire_all()
    # Лента только читает: токен продлевает лишь /api/app/status
    assert await db.scalar(select(AppDevice.expires_at)) == before
    assert (await app.post("/api/app/logout", headers=bearer(token))).status_code == 204
    gone = await app.get("/api/app/updates?platform=windows", headers=bearer(token))
    assert gone.status_code == 401 and gone.json() == {"error": {"code": "unauthorized"}}


async def test_feed_parameters_are_validated(clients, db):
    _, _, app, (token,) = await member_device(clients, db)
    for query in ("platform=ios", "platform=", "", "platform=windows&channel=nightly"):
        response = await app.get(f"/api/app/updates?{query}", headers=bearer(token))
        assert response.status_code == 422, query
        assert response.json() == {"error": {"code": "validation_error"}}


async def test_each_platform_gets_only_its_files_present_in_the_manifest_and_store(
    clients, db, store, tmp_path
):
    _, _, app, (token,) = await member_device(clients, db)
    files = assets(store, "1.2.3")
    data = manifest("1.2.3", files)
    await publish(tmp_path, "1.2.3", data, b"  " + SIGNATURE + b"\r\n")
    started = datetime.now(UTC)
    for platform, kinds in FEED.items():
        (release,) = await feed(app, token, platform)
        assert release["version"] == "1.2.3" and release["channel"] == "stable"
        # Байт в байт: подпись программа проверяет над этими байтами
        assert base64.b64decode(release["manifest"]) == data
        assert release["signature"] == SIGNATURE.decode()
        assert set(release["files"]) == kinds, platform
        for item in release["files"].values():
            ticket_of(item["url"])
            expires = datetime.fromisoformat(item["expires_at"])
            assert abs(expires - started - timedelta(minutes=30)) < timedelta(seconds=10)
    # Файла нет в хранилище — в ленте его нет, остальные остаются
    (store / f"{files['linux-x64-rpm']['sha256']}.bin").unlink()
    (release,) = await feed(app, token, "linux")
    assert set(release["files"]) == {"linux-x64-deb"}
    # Нет в манифесте — нет и в ленте, даже если файл лежит на сайте
    other = assets(store, "1.2.4", ("win-x64-msi", "linux-x64-deb"))
    await publish(tmp_path, "1.2.4", manifest("1.2.4", other))
    newest, _ = await feed(app, token, "android")
    assert newest["version"] == "1.2.4" and newest["files"] == {}


async def test_feed_lists_five_newest_versions_of_the_channel(clients, db, store, tmp_path):
    _, _, app, (token,) = await member_device(clients, db)
    for version in ("1.2.0", "1.9.0", "1.10.0", "0.9.9", "2.0.0", "1.2.10"):
        await publish(tmp_path, version, manifest(version, assets(store, version)))
    stable = [item["version"] for item in await feed(app, token)]
    assert stable == ["2.0.0", "1.10.0", "1.9.0", "1.2.10", "1.2.0"]
    # Бету сайт пока не принимает; если она есть, ее видит только канал beta
    beta_files = assets(store, "2.1.0-beta.1")
    db.add(
        AppUpdate(
            version="2.1.0-beta.1",
            channel="beta",
            rollout=100,
            published_at=utcnow(),
            manifest=manifest("2.1.0-beta.1", beta_files, rollout=100, channel="beta"),
            signature=SIGNATURE.decode(),
        )
    )
    await db.commit()
    assert [item["version"] for item in await feed(app, token)] == stable
    beta = await feed(app, token, channel="beta")
    assert [item["version"] for item in beta] == [
        "2.1.0-beta.1",
        "2.0.0",
        "1.10.0",
        "1.9.0",
        "1.2.10",
    ]
    assert beta[0]["channel"] == "beta" and set(beta[0]["files"]) == {"win-x64-msi"}


# --- Файл по билету ---


async def test_ticket_download_is_the_stored_file_with_headers_and_a_log_entry(
    clients, db, store, tmp_path
):
    _, user, app, (token,) = await member_device(clients, db)
    files = assets(store, "1.2.3")
    await publish(tmp_path, "1.2.3", manifest("1.2.3", files))
    # Служба десктопа качает без токена: только ссылка из ленты
    service = await clients(csrf=False, ip="203.0.113.58")
    service.headers.pop("Origin")
    service.headers["User-Agent"] = "PrivateGateway-Updates/0.3.0"
    for platform, kind, media in (
        ("android", "android-apk", "application/vnd.android.package-archive"),
        ("windows", "win-x64-msi", "application/x-msi"),
    ):
        (release,) = await feed(app, token, platform)
        response = await service.get(
            release["files"][kind]["url"], headers={"Accept-Encoding": "gzip, br, zstd"}
        )
        asset = files[kind]
        payload = (store / f"{asset['sha256']}.bin").read_bytes()
        assert response.status_code == 200 and response.content == payload
        headers = response.headers
        assert headers["content-type"] == media
        assert headers["content-disposition"] == (
            f"attachment; filename=\"{asset['file']}\"; filename*=UTF-8''{asset['file']}"
        )
        assert headers["content-length"] == str(asset["size"])
        assert headers["x-checksum-sha256"] == asset["sha256"]
        assert headers.get_list("cache-control") == ["no-store"]
        assert "content-encoding" not in headers
    events = (await db.scalars(select(DownloadEvent).order_by(DownloadEvent.id))).all()
    assert [(e.platform, e.version, e.filename) for e in events] == [
        ("android", "1.2.3", files["android-apk"]["file"]),
        ("windows", "1.2.3", files["win-x64-msi"]["file"]),
    ]
    for event in events:
        assert event.user_id == user["user"]["id"]
        assert event.ip_masked == "203.0.113.0/24"
        assert event.user_agent == "PrivateGateway-Updates/0.3.0"


async def test_forged_or_altered_tickets_are_refused(clients, db, store, tmp_path):
    _, _, app, (token,) = await member_device(clients, db)
    await publish(tmp_path, "1.2.3", manifest("1.2.3", assets(store, "1.2.3")))
    (release,) = await feed(app, token, "linux")
    anonymous = await clients(csrf=False, ip="203.0.113.59")
    good = ticket_of(release["files"]["linux-x64-deb"]["url"])
    head, mac = good.split(".")
    payload = base64.urlsafe_b64decode(head + "=" * (-len(head) % 4)).decode()
    device_id, version, kind, sha256, exp = payload.split("|")

    def encode(text: str) -> str:
        return base64.urlsafe_b64encode(text.encode()).rstrip(b"=").decode()

    flipped = ("B" if mac[0] == "A" else "A") + mac[1:]
    altered = [
        # Подпись не от сайта
        f"{head}.{flipped}",
        # Срок, устройство и файл — внутри подписи: поменять их нельзя
        f"{encode(f'{device_id}|{version}|{kind}|{sha256}|{int(exp) + 3600}')}.{mac}",
        f"{encode(f'{int(device_id) + 1}|{version}|{kind}|{sha256}|{exp}')}.{mac}",
        f"{encode(f'{device_id}|{version}|linux-x64-rpm|{sha256}|{exp}')}.{mac}",
        # Подпись другого назначения тем же секретом
        sign("other", payload),
        "garbage",
        "a" * 2000 + "." + mac,
    ]
    for ticket in altered:
        response = await anonymous.get(f"/api/app/updates/files/{ticket}")
        assert response.status_code == 403, ticket
        assert response.json() == {"error": {"code": "invalid_ticket"}}
    assert (await anonymous.get(f"/api/app/updates/files/{good}")).status_code == 200
    assert await db.scalar(select(func.count()).select_from(DownloadEvent)) == 1


async def test_ticket_lives_thirty_minutes(clients, db, store, tmp_path, monkeypatch):
    _, _, app, (token,) = await member_device(clients, db)
    await publish(tmp_path, "1.2.3", manifest("1.2.3", assets(store, "1.2.3")))
    (release,) = await feed(app, token, "macos")
    url = release["files"]["osx-arm64-dmg"]["url"]
    anonymous = await clients(csrf=False, ip="203.0.113.60")
    issued = utcnow()
    monkeypatch.setattr(updates, "utcnow", lambda: issued + timedelta(minutes=29))
    assert (await anonymous.get(url)).status_code == 200
    monkeypatch.setattr(updates, "utcnow", lambda: issued + timedelta(minutes=31))
    expired = await anonymous.get(url)
    assert expired.status_code == 403
    assert expired.json() == {"error": {"code": "ticket_expired"}}


async def test_ticket_stops_when_the_device_or_member_loses_access(
    clients, db, store, tmp_path, totp_clock
):
    admin_client = await clients(ip="198.51.100.61")
    admin = await register_user(admin_client, db, "admin@example.test", role="admin")
    uids = ("install-aaaaaaaaaaaa", "install-bbbbbbbbbbbb", "install-cccccccccccc")
    browser, user, app, tokens = await member_device(clients, db, uids=uids)
    await publish(tmp_path, "1.2.3", manifest("1.2.3", assets(store, "1.2.3")))
    urls = [
        (await feed(app, token, "android"))[0]["files"]["android-apk"]["url"] for token in tokens
    ]
    anonymous = await clients(csrf=False, ip="203.0.113.61")

    async def status(url: str) -> int:
        response = await anonymous.get(url)
        if response.status_code == 403:
            assert response.json() == {"error": {"code": "forbidden"}}
        return response.status_code

    # Участник удалил первое устройство на сайте: его билет больше не действует
    devices = (await browser.get("/api/me/devices")).json()["devices"]
    first = await db.scalar(select(AppDevice.id).where(AppDevice.device_uid == uids[0]))
    assert first in [item["id"] for item in devices]
    assert (await browser.post(f"/api/me/devices/{first}/revoke")).status_code == 204
    assert [await status(url) for url in urls] == [403, 200, 200]
    # Второе вышло из аккаунта в приложении
    assert (await app.post("/api/app/logout", headers=bearer(tokens[1]))).status_code == 204
    assert [await status(url) for url in urls] == [403, 403, 200]
    # Блокировка участника закрывает и последнее
    blocked = await admin_client.patch(
        f"/api/admin/members/{user['user']['id']}",
        json={"status": "blocked", "code": totp_clock(admin)},
    )
    assert blocked.status_code == 200, blocked.text
    assert [await status(url) for url in urls] == [403, 403, 403]
    assert await db.scalar(select(func.count()).select_from(DownloadEvent)) == 3


async def test_store_file_swapped_for_a_link_is_neither_listed_nor_served(
    clients, db, store, tmp_path
):
    _, _, app, (token,) = await member_device(clients, db)
    files = assets(store, "1.2.3")
    await publish(tmp_path, "1.2.3", manifest("1.2.3", files))
    (release,) = await feed(app, token)
    url = release["files"]["win-x64-msi"]["url"]
    # Файл хранилища подменен ссылкой на файл вне хранилища того же размера
    stored = store / f"{files['win-x64-msi']['sha256']}.bin"
    size = files["win-x64-msi"]["size"]
    outside = tmp_path / "outside.bin"
    outside.write_bytes((b"outside-the-store" * size)[:size])
    stored.unlink()
    stored.symlink_to(outside)
    anonymous = await clients(csrf=False, ip="203.0.113.63")
    response = await anonymous.get(url)
    assert response.status_code == 404
    assert b"outside-the-store" not in response.content
    (again,) = await feed(app, token)
    assert again["files"] == {}
    assert await db.scalar(select(func.count()).select_from(DownloadEvent)) == 0


# --- Прием выпуска: cli publish-update и store-file ---


async def test_publish_update_refuses_what_programs_could_not_use(clients, db, store, tmp_path):
    files = assets(store, "1.2.3")
    # Другие байты rpm, которых на сайт не присылали
    missing = files | assets(store, "9.9.9", ("linux-x64-rpm",), stored=False)
    wrong_size = files | {
        "android-apk": files["android-apk"] | {"size": files["android-apk"]["size"] + 1}
    }
    archives_only = {kind: files[kind] for kind in ("win-x64-zip", "linux-x64-tar")}

    def renamed(name: str) -> dict:
        """Файлы на месте, SHA-256 и размер верные — плохое только имя msi."""
        return files | {"win-x64-msi": files["win-x64-msi"] | {"file": name}}

    cases = [
        ("1.2.3", manifest("1.2.3", missing), "linux-x64-rpm"),
        ("1.2.3", manifest("1.2.3", wrong_size), "android-apk"),
        ("1.2.4", manifest("1.2.3", files), "not for version 1.2.4"),
        # Бету не принимает уже версия, какой бы канал ни был в манифесте
        ("1.3.0-beta.1", manifest("1.3.0-beta.1", files), "Only stable versions"),
        ("1.3.0-beta.1", manifest("1.3.0-beta.1", files, channel="beta"), "Only stable versions"),
        ("1.2.3", manifest("1.2.3", files, channel="beta"), "stable channel"),
        ("1.2.3", b"{not json", "JSON"),
        ("1.2.3", b'["1.2.3"]', "JSON object"),
        ("1.2.3", manifest("1.2.3", files, rollout=101), "rollout"),
        ("1.2.3", manifest("1.2.3", archives_only), "no files for the update feed"),
        # Имя с папкой или кавычкой программа не примет: файл ляжет в ее папку загрузок
        ("1.2.3", manifest("1.2.3", renamed("../x.msi")), "invalid asset 'win-x64-msi'"),
        ("1.2.3", manifest("1.2.3", renamed('a"b.msi')), "invalid asset 'win-x64-msi'"),
    ]
    for version, data, reason in cases:
        assert reason in await refused(tmp_path, version, data)
    bad_signature = await refused(tmp_path, "1.2.3", manifest("1.2.3", files), b"{not base64}")
    assert "update.json.sig must be base64" in bad_signature
    assert await db.scalar(select(func.count()).select_from(AppUpdate)) == 0
    # Тот же манифест со всеми файлами на месте принимается
    await publish(tmp_path, "1.2.3", manifest("1.2.3", files))
    assert await db.scalar(select(func.count()).select_from(AppUpdate)) == 1


async def test_size_limits_refuse_instead_of_truncating(clients, db, store, tmp_path):
    files = assets(store, "1.2.3")
    limit = updates.MANIFEST_MAX_BYTES
    # Манифест на байт длиннее 64 КБ: обрезанный до предела, он остался бы верным JSON
    over = sized("1.2.3", files, limit + 1)
    assert f"update.json is larger than {limit} bytes" in await refused(tmp_path, "1.2.3", over)
    # Тот же предел у самого приема, без команды
    try:
        await updates.publish(db, "1.2.3", over, SIGNATURE)
    except ValueError as error:
        assert "update.json must be from 1 byte to 64 KB" in str(error)
    else:
        raise AssertionError("updates.publish accepted a manifest over 64 KB")
    # Подпись — текст base64 до 1 КБ; файл с пробелами по краям — до 1088 байт
    data = manifest("1.2.3", files)
    longest = base64.b64encode(bytes(range(256)) * 3)
    too_long = base64.b64encode(bytes(range(256)) * 3 + b"\x00\x01\x02")
    assert (len(longest), len(too_long)) == (1024, 1028)
    reason = await refused(tmp_path, "1.2.3", data, too_long + b"\n")
    assert "update.json.sig must be base64 text up to 1 KB" in reason
    # Файл подписи на байт длиннее: обрезанный до предела, он дал бы верную подпись
    spaced = longest + b" " * 64
    assert len(spaced) == updates.SIGNATURE_MAX_BYTES + 64
    reason = await refused(tmp_path, "1.2.3", data, spaced + b"\n")
    assert "update.json.sig is larger than 1088 bytes" in reason
    assert await db.scalar(select(func.count()).select_from(AppUpdate)) == 0
    # Ровно на пределах — принимаются
    exact = sized("1.2.3", files, limit)
    assert await outcome(tmp_path, "1.2.3", exact, spaced) == "accepted"
    row = (await db.scalars(select(AppUpdate))).one()
    assert (row.manifest, row.signature) == (exact, longest.decode())


async def test_same_version_again_replaces_manifest_and_signature(clients, db, store, tmp_path):
    _, _, app, (token,) = await member_device(clients, db)
    files = assets(store, "1.2.3")
    await publish(tmp_path, "1.2.3", manifest("1.2.3", files, rollout=20))
    (first,) = await feed(app, token)
    created = await db.scalar(select(AppUpdate.created_at))
    # Новая доля раскатки — новый манифест и новая подпись той же версии
    rollout = manifest("1.2.3", files, rollout=50)
    signature = base64.b64encode(b"0E\x02!" + bytes(range(33, 66)))
    await publish(tmp_path, "1.2.3", rollout, signature)
    db.expire_all()
    row = (await db.scalars(select(AppUpdate))).one()
    assert (row.rollout, row.manifest, row.signature) == (50, rollout, signature.decode())
    assert row.created_at == created and row.updated_at > created
    (second,) = await feed(app, token)
    assert base64.b64decode(second["manifest"]) == rollout
    assert json.loads(base64.b64decode(second["manifest"]))["rollout"] == 50
    # Билет, выданный до смены доли, ведет к тому же файлу и действует
    anonymous = await clients(csrf=False, ip="203.0.113.62")
    assert (await anonymous.get(first["files"]["win-x64-msi"]["url"])).status_code == 200


async def test_stopped_rollout_is_accepted_without_files_on_the_site(
    clients, db, store, tmp_path, capsys
):
    _, _, app, (token,) = await member_device(clients, db)
    files = assets(store, "1.2.3")
    await publish(tmp_path, "1.2.3", manifest("1.2.3", files))
    # Сервер восстановлен из бэкапа: манифест в базе, а rpm в хранилище еще не внесен заново
    rpm = files["linux-x64-rpm"]
    (store / f"{rpm['sha256']}.bin").unlink()
    capsys.readouterr()
    # Стоп-кран (доля 0, только update-sig и update) проходит: такой выпуск программа не ставит
    stop = manifest("1.2.3", files, rollout=0)
    assert await outcome(tmp_path, "1.2.3", stop) == "accepted"
    assert f"Not in the download store yet: linux-x64-rpm {rpm['file']}" in capsys.readouterr().out
    db.expire_all()
    row = (await db.scalars(select(AppUpdate))).one()
    assert (row.rollout, row.manifest) == (0, stop)
    # Доля больше 0 без файла — по-прежнему отказ, в ленте остается стоп-кран без ссылок
    assert "linux-x64-rpm" in await refused(tmp_path, "1.2.3", manifest("1.2.3", files, rollout=50))
    (release,) = await feed(app, token, "linux")
    assert base64.b64decode(release["manifest"]) == stop and release["files"] == {}
    # Файл внесли заново — новая доля проходит, ссылки снова в ленте
    assets(store, "1.2.3", ("linux-x64-rpm",))
    assert await outcome(tmp_path, "1.2.3", manifest("1.2.3", files, rollout=50)) == "accepted"
    (release,) = await feed(app, token, "linux")
    assert set(release["files"]) == {"linux-x64-deb", "linux-x64-rpm"}


async def test_stopped_rollout_gives_no_files_and_refuses_earlier_tickets(
    clients, db, store, tmp_path
):
    _, _, app, (token,) = await member_device(clients, db)
    files = assets(store, "1.2.3")
    await publish(tmp_path, "1.2.3", manifest("1.2.3", files, rollout=100))
    (release,) = await feed(app, token)
    url = release["files"]["win-x64-msi"]["url"]
    anonymous = await clients(csrf=False, ip="203.0.113.64")
    assert (await anonymous.get(url)).status_code == 200
    # Стоп-кран: выпуск остается в ленте без ссылок, а билет, выданный до остановки, не действует
    await publish(tmp_path, "1.2.3", manifest("1.2.3", files, rollout=0))
    for platform in FEED:
        (stopped,) = await feed(app, token, platform)
        assert (stopped["version"], stopped["files"]) == ("1.2.3", {}), platform
    response = await anonymous.get(url)
    assert response.status_code == 403
    assert response.json() == {"error": {"code": "rollout_stopped"}}
    # Новая доля больше 0 — ссылки снова в ленте, и тот же билет снова действует
    await publish(tmp_path, "1.2.3", manifest("1.2.3", files, rollout=10))
    (resumed,) = await feed(app, token)
    assert set(resumed["files"]) == {"win-x64-msi"}
    assert (await anonymous.get(url)).status_code == 200
    # Отказ в журнал скачиваний не попадает
    assert await db.scalar(select(func.count()).select_from(DownloadEvent)) == 2


async def test_store_file_keeps_the_file_without_a_catalog_row(clients, db, store, tmp_path):
    payload = b"rpm test bytes, not a package\n" * 100
    source = tmp_path / "private-gateway-1.2.3-1.x86_64.rpm"
    source.write_bytes(payload)
    await cli.run(cli.parser().parse_args(["store-file", "--file", str(source)]))
    sha256 = hashlib.sha256(payload).hexdigest()
    assert (store / f"{sha256}.bin").read_bytes() == payload
    assert await db.scalar(select(func.count()).select_from(Release)) == 0
    browser = await clients()
    await register_user(browser, db)
    catalog = (await browser.get("/api/downloads")).json()["items"]
    assert not any(item["available"] for item in catalog)
    # Пустой файл не принимается
    empty = tmp_path / "empty.rpm"
    empty.write_bytes(b"")
    try:
        await cli.run(cli.parser().parse_args(["store-file", "--file", str(empty)]))
    except ValueError as error:
        assert "nonempty" in str(error)
    else:
        raise AssertionError("store-file accepted an empty file")
