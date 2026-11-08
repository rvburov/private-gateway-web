"""Условные UPDATE из Capper: TOTP и резервный код потребляются атомарно."""

from datetime import datetime

from sqlalchemy import or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RecoveryCode, User, utcnow


async def consume_totp_step(db: AsyncSession, user_id: int, step: int) -> bool:
    result = await db.execute(
        update(User)
        .where(User.id == user_id, or_(User.totp_last_step.is_(None), User.totp_last_step < step))
        .values(totp_last_step=step)
        .returning(User.id)
    )
    return result.scalar_one_or_none() is not None


async def consume_recovery_code(
    db: AsyncSession, user_id: int, code_hash: str, *, now: datetime | None = None
) -> bool:
    result = await db.execute(
        update(RecoveryCode)
        .where(
            RecoveryCode.user_id == user_id,
            RecoveryCode.code_hash == code_hash,
            RecoveryCode.used_at.is_(None),
        )
        .values(used_at=now or utcnow())
        .returning(RecoveryCode.id)
    )
    return result.scalar_one_or_none() is not None
