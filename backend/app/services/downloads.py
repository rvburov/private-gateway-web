"""Приватное хранилище выпусков, без произвольных путей и внешних перенаправлений."""

import os
import re
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


def release_path(release: Release) -> Path | None:
    if not release.storage_name or not re.fullmatch(r"[a-f0-9]{64}\.bin", release.storage_name):
        return None
    root = get_settings().download_root.resolve()
    path = root / release.storage_name
    try:
        if path.is_symlink() or path.resolve(strict=True).parent != root or not path.is_file():
            return None
        if path.stat().st_size != release.size_bytes:
            return None
    except OSError:
        return None
    return path


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
    if not path:
        raise AppError(404, "not_found")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise AppError(404, "not_found") from None
    file = os.fdopen(fd, "rb")
    if os.fstat(file.fileno()).st_size != release.size_bytes:
        file.close()
        raise AppError(404, "not_found")
    filename = release.filename or f"private-gateway-{platform}"
    size, sha256 = release.size_bytes, release.sha256
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

    # Файлы выпуска в контейнере монтируются read-only; дескриптор защищает от подмены symlink.
    def chunks():
        try:
            while block := file.read(1024 * 1024):
                yield block
        finally:
            file.close()

    return StreamingResponse(
        chunks(),
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(filename, safe=""),
            "Content-Length": str(size),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
            "X-Checksum-SHA256": sha256 or "",
        },
    )


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
