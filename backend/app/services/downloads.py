"""Приватное хранилище выпусков, без произвольных путей и внешних перенаправлений.

Файлы лежат под именами <sha256>.bin в PGWEB_DOWNLOAD_ROOT. Их отдают каталог «Скачать
клиент» (по сеансу сайта) и лента обновлений программы (services/updates.py, по билету).
"""

import hashlib
import os
import re
import tempfile
from io import BufferedReader
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.net import device_label, mask_ip, user_agent
from app.db.models import DownloadEvent, Release, User
from app.services.auth import client_ip, current_user

PLATFORMS = ("windows", "macos", "ios", "linux", "android")
# Тип файла по расширению: Android открывает установщик по типу .apk, иначе файл «не открыть»
MEDIA_TYPES = {
    ".apk": "application/vnd.android.package-archive",
    ".msi": "application/x-msi",
    ".exe": "application/vnd.microsoft.portable-executable",
    ".dmg": "application/x-apple-diskimage",
    ".deb": "application/vnd.debian.binary-package",
    ".rpm": "application/x-rpm",
}


def media_type(filename: str) -> str:
    return MEDIA_TYPES.get(Path(filename).suffix.lower(), "application/octet-stream")


def content_disposition(filename: str) -> str:
    """attachment с именем файла: ASCII-запасное filename и точное filename* (RFC 6266).

    Старые загрузчики Android понимают только filename; расширение в нем сохраняется.
    """
    fallback = re.sub(r"[^A-Za-z0-9._+-]", "_", filename).lstrip(".") or "download"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


def app_store_url(value: str) -> bool:
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "apps.apple.com"
        and not parsed.username
        and not parsed.password
        and parsed.port in {None, 443}
        and bool(re.search(r"/id[0-9]+(?:/|$)", parsed.path))
        and not parsed.fragment
    )


def stored_file(storage_name: str | None, size: int | None) -> Path | None:
    """Файл хранилища <sha256>.bin нужного размера прямо в корне хранилища, не ссылка."""
    if not storage_name or not re.fullmatch(r"[a-f0-9]{64}\.bin", storage_name):
        return None
    root = get_settings().download_root.resolve()
    path = root / storage_name
    try:
        if path.is_symlink() or path.resolve(strict=True).parent != root or not path.is_file():
            return None
        if path.stat().st_size != size:
            return None
    except OSError:
        return None
    return path


def release_path(release: Release) -> Path | None:
    return stored_file(release.storage_name, release.size_bytes)


def store(source: Path) -> tuple[str, int, str]:
    """Копирует проверенный файл в хранилище под именем <sha256>.bin: имя, размер, SHA-256.

    Тот же файл повторно ложится на свое же имя, поэтому повторный прием безопасен.
    """
    root = get_settings().download_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    fd, temporary = tempfile.mkstemp(prefix=".release-", dir=root)
    try:
        with os.fdopen(fd, "wb") as output, source.open("rb") as content:
            while block := content.read(1024 * 1024):
                digest.update(block)
                output.write(block)
                size += len(block)
            output.flush()
            os.fsync(output.fileno())
        storage_name = digest.hexdigest() + ".bin"
        os.chmod(temporary, 0o640)
        os.replace(temporary, root / storage_name)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return storage_name, size, digest.hexdigest()


def open_stored(path: Path, size: int | None) -> BufferedReader | None:
    """Открывает файл без перехода по ссылке и сверяет размер уже по дескриптору."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    file = os.fdopen(fd, "rb")
    if os.fstat(file.fileno()).st_size != size:
        file.close()
        return None
    return file


def file_response(
    file: BufferedReader, filename: str, size: int, sha256: str | None
) -> StreamingResponse:
    """Ответ с файлом: тип по расширению, имя, точный размер и SHA-256 в заголовках."""

    # Файлы выпуска в контейнере монтируются read-only; дескриптор защищает от подмены symlink.
    def chunks():
        try:
            while block := file.read(1024 * 1024):
                yield block
        finally:
            file.close()

    # Cache-Control: no-store и nosniff добавляет SecurityMiddleware ко всем ответам API.
    # Content-Length — точный размер: телефон показывает ход загрузки и проверяет конец файла
    return StreamingResponse(
        chunks(),
        media_type=media_type(filename),
        headers={
            "Content-Disposition": content_disposition(filename),
            "Content-Length": str(size),
            "X-Checksum-SHA256": sha256 or "",
        },
    )


async def catalog(db: AsyncSession, request: Request) -> dict:
    await current_user(db, request)
    releases = {
        r.platform: r
        for r in (await db.scalars(select(Release).where(Release.enabled.is_(True)))).all()
    }
    items = []
    for platform in PLATFORMS:
        release = releases.get(platform)
        available = bool(
            release
            and (
                (platform == "ios" and release.store_url and app_store_url(release.store_url))
                or (platform != "ios" and release_path(release))
            )
        )
        items.append(
            {
                "platform": platform,
                "available": available,
                "version": release.version if available else None,
                "filename": release.filename if available else None,
                "size_bytes": release.size_bytes if available else None,
                "sha256": release.sha256 if available else None,
                "url": (
                    release.store_url if platform == "ios" else f"/api/downloads/{platform}/file"
                )
                if available
                else None,
            }
        )
    return {"items": items}


async def download(db: AsyncSession, request: Request, platform: str) -> StreamingResponse:
    user = await current_user(db, request)
    if platform not in PLATFORMS or platform == "ios":
        raise AppError(404, "not_found")
    release = await db.scalar(
        select(Release).where(Release.platform == platform, Release.enabled.is_(True))
    )
    path = release_path(release) if release else None
    file = open_stored(path, release.size_bytes) if release and path else None
    if release is None or file is None:
        raise AppError(404, "not_found")
    filename = release.filename or f"private-gateway-{platform}"
    size, sha256 = release.size_bytes or 0, release.sha256
    # Журнал скачиваний: запись до отдачи файла, чтобы ее не потерять при обрыве передачи
    db.add(
        DownloadEvent(
            user_id=user.id,
            platform=platform,
            version=release.version,
            filename=release.filename,
            ip_masked=mask_ip(client_ip(request)),
            user_agent=user_agent(request),
        )
    )
    try:
        await db.commit()
    except Exception:
        file.close()
        raise
    return file_response(file, filename, size, sha256)


async def history(db: AsyncSession, user_id: int | None, limit: int, offset: int) -> dict:
    """Журнал скачиваний для администратора, новые сверху; можно по одному участнику."""
    where = [DownloadEvent.user_id == user_id] if user_id is not None else []
    total = await db.scalar(select(func.count()).select_from(DownloadEvent).where(*where))
    rows = (
        await db.execute(
            select(DownloadEvent, User)
            .outerjoin(User, User.id == DownloadEvent.user_id)
            .where(*where)
            .order_by(DownloadEvent.at.desc(), DownloadEvent.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return {
        "items": [
            {
                "id": event.id,
                "at": event.at,
                "platform": event.platform,
                "version": event.version,
                "filename": event.filename,
                "ip_masked": event.ip_masked,
                "device": device_label(event.user_agent),
                "user": (
                    {"id": user.id, "email": user.email, "display_name": user.display_name}
                    if user
                    else None
                ),
            }
            for event, user in rows
        ],
        "total": total,
    }
