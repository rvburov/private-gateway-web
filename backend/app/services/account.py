"""Свой аккаунт: смена пароля и выход на всех устройствах.

Оба действия завершают все остальные входы на сайт, доверенные браузеры и устройства
приложения (auth_version + 1), а текущему браузеру выдают новый сеанс. Администратор
подтверждает их кодом 2FA, участник — нет (у него 2FA нет, DECISIONS п. 11).
"""

from fastapi import Request, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import passwords
from app.db.models import AccessCode, User, utcnow
from app.services import auth, limits


async def _locked_user(db: AsyncSession, request: Request) -> User:
    user = await auth.current_user(db, request, touch=False)
    await db.execute(select(User.id).where(User.id == user.id).with_for_update())
    # Под блокировкой сеанс проверяется заново: отзыв доступа мог завершиться раньше нас,
    # и выданный ниже новый сеанс не должен его отменить
    user = await auth.current_user(db, request, touch=False)
    await db.refresh(user)
    return user


async def _confirm_factor(db: AsyncSession, user: User, code: str | None) -> None:
    if not auth.needs_two_factor(user):
        return
    if code is None:
        raise AppError(400, "code_required")
    await limits.attempt("admin-factor", str(user.id))
    await auth.consume_factor(db, user, code)


async def change_password(db: AsyncSession, request: Request, response: Response, body) -> dict:
    user = await auth.current_user(db, request, touch=False)
    user_id, stored_hash = user.id, user.password_hash
    await db.rollback()
    await limits.attempt("password-change", str(user_id))
    passwords.validate_password_policy(body.new_password)
    if not await passwords.verify_password_async(stored_hash, body.current_password):
        # Не 401: неверный текущий пароль не завершает сеанс в интерфейсе
        raise AppError(400, "invalid_password")
    new_hash = await passwords.hash_password_async(body.new_password)
    user = await _locked_user(db, request)
    if user.id != user_id or user.password_hash != stored_hash:
        raise AppError(409, "password_changed")
    await _confirm_factor(db, user, body.code)
    user.password_hash = new_hash
    # Невыполненные коды сброса больше не нужны: пароль задал сам участник
    await db.execute(
        update(AccessCode)
        .where(
            AccessCode.user_id == user.id,
            AccessCode.kind == "password_reset",
            AccessCode.used_at.is_(None),
            AccessCode.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow())
    )
    await auth.revoke_access(db, user)
    auth.audit(db, "password.changed", user.id, user.id)
    await auth.new_session(db, user, request, response)
    await limits.clear("password-change", str(user.id))
    await limits.clear("admin-factor", str(user.id))
    return {"status": "ok"}


async def sign_out_everywhere(db: AsyncSession, request: Request, response: Response, body) -> dict:
    user = await _locked_user(db, request)
    await _confirm_factor(db, user, body.code)
    await auth.revoke_access(db, user)
    auth.audit(db, "access.signed_out_everywhere", user.id, user.id)
    await auth.new_session(db, user, request, response)
    await limits.clear("admin-factor", str(user.id))
    return {"status": "ok"}
