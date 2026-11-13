"""Лента обновлений программы: подписанные манифесты выпусков и билеты на файлы.

Выпуск клиента присылает workflow «Выпуск на сайт» (deploy/import-release.sh): сначала файлы
(в хранилище по SHA-256), затем подпись update.json.sig и последним манифест update.json —
его вносит publish() (cli publish-update). Манифест хранится байт в байт: подпись ECDSA и
SHA-256 файлов проверяет программа встроенным ключом, поэтому подделать обновление сайт не
может, может только не показать его. Повторный прием той же версии заменяет манифест и
подпись: так приходит новая доля раскатки.

Ленту (feed) берет устройство своим токеном, как /api/app/status. Файл — по билету из ленты:
HMAC секретом сайта над device_id|version|kind|sha256|exp, живет 30 минут и действует, пока
устройство не отозвано и участник не заблокирован. Билет сам — право: службе десктопа токен
устройства не нужен, ленту ей передает окно.
"""

import base64
import binascii
import json
import re
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.net import mask_ip, user_agent
from app.core.security import tokens
from app.db.models import AppUpdate, DownloadEvent, utcnow
from app.services import devices
from app.services.auth import client_ip
from app.services.downloads import file_response, open_stored, stored_file

# Файлы, которые программа ставит сама (виды из scripts/release.cs клиента). Архивы zip и tar
# в ленту не идут: их не ставит ни служба, ни приложение
PLATFORM_KINDS = {
    "windows": ("win-x64-msi",),
    "macos": ("osx-arm64-dmg",),
    "linux": ("linux-x64-deb", "linux-x64-rpm"),
    "android": ("android-apk",),
}
KIND_PLATFORM = {kind: platform for platform, kinds in PLATFORM_KINDS.items() for kind in kinds}
# Новые сверху: служба выбирает обновление и версию для отката
FEED_RELEASES = 5
# Пределы — как у программы: манифест до 64 КБ, подпись до 1 КБ, файл до 2 ГБ
MANIFEST_MAX_BYTES = 64 * 1024
SIGNATURE_MAX_BYTES = 1024
ASSET_MAX_BYTES = 2 * 1024**3
TICKET_TTL = timedelta(minutes=30)
TICKET_PURPOSE = "update-file"

STABLE_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
SEMVER = re.compile(r"([0-9]+)\.([0-9]+)\.([0-9]+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?")
KIND = re.compile(r"[a-z0-9-]{1,40}")
# Имя файла без папок, как его проверяет программа: файл ляжет в ее папку загрузок
FILE_NAME = re.compile(r"[A-Za-z0-9_~+-][A-Za-z0-9._~+-]{0,199}")
SHA256 = re.compile(r"[0-9a-f]{64}")
SIGNATURE = re.compile(r"[A-Za-z0-9+/]+={0,2}")
TICKET_FIELDS = re.compile(
    r"([0-9]{1,19})\|([0-9A-Za-z.+-]{1,64})\|([a-z0-9-]{1,40})\|([0-9a-f]{64})\|([0-9]{1,12})"
)


def version_key(version: str) -> tuple:
    """Порядок SemVer: 1.10.0 новее 1.9.0, выпуск новее своей беты."""
    match = SEMVER.fullmatch(version)
    if not match:
        return ((-1,), False, ())
    major, minor, patch, pre = match.groups()
    identifiers = (
        tuple((0, int(x), "") if x.isdigit() else (1, 0, x) for x in pre.split(".")) if pre else ()
    )
    return ((int(major), int(minor), int(patch)), pre is None, identifiers)


def _asset(value: object) -> dict | None:
    """Файл манифеста, проверенный как в программе: имя, SHA-256 и размер."""
    if not isinstance(value, dict):
        return None
    name, sha256, size = value.get("file"), value.get("sha256"), value.get("size")
    if not isinstance(name, str) or not FILE_NAME.fullmatch(name):
        return None
    if not isinstance(sha256, str) or not SHA256.fullmatch(sha256):
        return None
    if type(size) is not int or not 1 <= size <= ASSET_MAX_BYTES:
        return None
    return {"file": name, "sha256": sha256, "size": size}


def _assets(manifest: bytes) -> dict[str, dict]:
    """Файлы ленты из принятого манифеста (только виды, которые отдает сайт)."""
    try:
        assets = json.loads(manifest).get("assets")
    except (ValueError, AttributeError):
        return {}
    if not isinstance(assets, dict):
        return {}
    found = {}
    for kind in KIND_PLATFORM:
        asset = _asset(assets.get(kind))
        if asset is not None:
            found[kind] = asset
    return found


def _published(value: object) -> datetime:
    if isinstance(value, str):
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            pass
        else:
            return moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    raise ValueError("update.json: published must be an ISO 8601 time")


def _signature(data: bytes) -> str:
    """Текст update.json.sig без пробелов по краям: base64 (подпись проверяет программа)."""
    try:
        value = data.decode("ascii").strip()
    except UnicodeDecodeError:
        value = ""
    if not value or len(value) > SIGNATURE_MAX_BYTES or not SIGNATURE.fullmatch(value):
        raise ValueError("update.json.sig must be base64 text up to 1 KB")
    try:
        base64.b64decode(value, validate=True)
    except binascii.Error:
        raise ValueError("update.json.sig must be base64 text up to 1 KB") from None
    return value


async def publish(db: AsyncSession, version: str, manifest: bytes, signature: bytes) -> dict:
    """Вносит манифест выпуска и его подпись; файлы ленты из манифеста уже лежат в хранилище.

    Ошибка — ValueError с причиной: команда publish-update печатает ее и ничего не меняет.
    """
    if len(version) > 64 or not STABLE_VERSION.fullmatch(version):
        raise ValueError("Only stable versions X.Y.Z are accepted for the update feed for now")
    if not manifest or len(manifest) > MANIFEST_MAX_BYTES:
        raise ValueError("update.json must be from 1 byte to 64 KB")
    try:
        parsed = json.loads(manifest.decode("utf-8"))
    except ValueError:
        raise ValueError("update.json is not UTF-8 JSON") from None
    if not isinstance(parsed, dict):
        raise ValueError("update.json must be a JSON object")
    if parsed.get("version") != version:
        raise ValueError(f"update.json is not for version {version}")
    if parsed.get("channel") != "stable":
        raise ValueError("Only the stable channel is accepted for the update feed for now")
    rollout = parsed.get("rollout")
    if type(rollout) is not int or not 0 <= rollout <= 100:
        raise ValueError("update.json: rollout must be an integer from 0 to 100")
    published = _published(parsed.get("published"))
    assets = parsed.get("assets")
    if not isinstance(assets, dict) or not assets:
        raise ValueError("update.json has no assets")
    served = []
    for kind, value in assets.items():
        asset = _asset(value)
        if not KIND.fullmatch(kind) or asset is None:
            raise ValueError(f"update.json: invalid asset {kind[:40]!r}")
        if kind not in KIND_PLATFORM:
            continue
        # Иначе у программ будет 404 вместо обновления: сначала файлы, манифест последним
        if stored_file(asset["sha256"] + ".bin", asset["size"]) is None:
            raise ValueError(
                f"{kind} {asset['file']} is not in the download store: send it first "
                "(import-release.sh import or asset)"
            )
        served.append(kind)
    if not served:
        raise ValueError("update.json has no files for the update feed")
    text = _signature(signature)
    now = utcnow()
    values = {
        "channel": "stable",
        "rollout": rollout,
        "published_at": published,
        "manifest": manifest,
        "signature": text,
        "updated_at": now,
    }
    await db.execute(
        insert(AppUpdate)
        .values(version=version, created_at=now, **values)
        .on_conflict_do_update(index_elements=[AppUpdate.version], set_=values)
    )
    await db.commit()
    return {"version": version, "rollout": rollout, "files": served}


async def feed(db: AsyncSession, request: Request, platform: str, channel: str) -> dict:
    device, _ = await devices.app_device(db, request)
    # Канал beta получает и стабильные выпуски, stable — только их
    channels = ("stable",) if channel == "stable" else ("stable", "beta")
    versions = (
        await db.scalars(select(AppUpdate.version).where(AppUpdate.channel.in_(channels)))
    ).all()
    newest = sorted(versions, key=version_key, reverse=True)[:FEED_RELEASES]
    rows = {}
    if newest:
        found = await db.scalars(select(AppUpdate).where(AppUpdate.version.in_(newest)))
        rows = {row.version: row for row in found.all()}
    exp = int(utcnow().timestamp() + TICKET_TTL.total_seconds())
    expires_at = datetime.fromtimestamp(exp, UTC)
    origin = get_settings().public_origin
    releases = []
    for version in newest:
        row = rows.get(version)
        if row is None:
            continue
        assets = _assets(row.manifest)
        files = {}
        # Только файлы своей платформы, которые есть в манифесте и в хранилище
        for kind in PLATFORM_KINDS[platform]:
            asset = assets.get(kind)
            if asset is None or stored_file(asset["sha256"] + ".bin", asset["size"]) is None:
                continue
            ticket = tokens.sign(
                TICKET_PURPOSE, f"{device.id}|{row.version}|{kind}|{asset['sha256']}|{exp}"
            )
            files[kind] = {
                "url": f"{origin}/api/app/updates/files/{ticket}",
                "expires_at": expires_at,
            }
        releases.append(
            {
                "version": row.version,
                "channel": row.channel,
                "manifest": base64.b64encode(row.manifest).decode(),
                "signature": row.signature,
                "files": files,
            }
        )
    return {"releases": releases}


async def download(db: AsyncSession, request: Request, ticket: str) -> StreamingResponse:
    payload = tokens.unsign(TICKET_PURPOSE, ticket)
    match = TICKET_FIELDS.fullmatch(payload) if payload else None
    if not match:
        raise AppError(403, "invalid_ticket")
    device_id, version, kind, sha256, exp = match.groups()
    if int(exp) <= utcnow().timestamp():
        raise AppError(403, "ticket_expired")
    # Билет действует, пока действует доступ устройства: отзыв и блокировка закрывают и файл
    pair = await devices.active_app_device(db, int(device_id))
    if pair is None:
        raise AppError(403, "forbidden")
    _, user = pair
    row = await db.get(AppUpdate, version)
    asset = _assets(row.manifest).get(kind) if row else None
    if asset is None or asset["sha256"] != sha256:
        raise AppError(404, "not_found")
    path = stored_file(sha256 + ".bin", asset["size"])
    file = open_stored(path, asset["size"]) if path else None
    if file is None:
        raise AppError(404, "not_found")
    # Журнал скачиваний, как у файлов каталога: запись до отдачи файла
    db.add(
        DownloadEvent(
            user_id=user.id,
            platform=KIND_PLATFORM[kind],
            version=version,
            filename=asset["file"],
            ip_masked=mask_ip(client_ip(request)),
            user_agent=user_agent(request),
        )
    )
    try:
        await db.commit()
    except Exception:
        file.close()
        raise
    return file_response(file, asset["file"], asset["size"], sha256)
