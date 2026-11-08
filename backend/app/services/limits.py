"""Лимиты переживают рестарт и общие для всех процессов; отдельная транзакция сохраняет отказ."""

import hashlib
import hmac
from datetime import timedelta

from sqlalchemy import case, delete
from sqlalchemy.dialects.postgresql import insert

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.models import RateLimit, utcnow
from app.db.session import get_session_factory


def key_for(scope: str, identity: str) -> str:
    return hmac.new(
        get_settings().secret_key_bytes, f"limit:{scope}:{identity}".encode(), hashlib.sha256
    ).hexdigest()


async def attempt(scope: str, identity: str, *, limit: int = 5, seconds: int = 900) -> None:
    now = utcnow()
    key = key_for(scope, identity)
    expired = RateLimit.expires_at <= now
    statement = insert(RateLimit).values(
        key=key, count=1, expires_at=now + timedelta(seconds=seconds)
    )
    statement = statement.on_conflict_do_update(
        index_elements=[RateLimit.key],
        set_={
            "count": case((expired, 1), else_=RateLimit.count + 1),
            "expires_at": case(
                (expired, now + timedelta(seconds=seconds)), else_=RateLimit.expires_at
            ),
        },
    ).returning(RateLimit.count, RateLimit.expires_at)
    async with get_session_factory()() as db:
        count, expires_at = (await db.execute(statement)).one()
        await db.commit()
    if count > limit:
        raise AppError(
            429, "rate_limited", retry_after=max(1, int((expires_at - now).total_seconds()))
        )


async def clear(scope: str, identity: str) -> None:
    async with get_session_factory()() as db:
        await db.execute(delete(RateLimit).where(RateLimit.key == key_for(scope, identity)))
        await db.commit()
