"""Администратор управляет только доступом к этому сайту; VPN здесь не затрагивается."""

from datetime import timedelta

from fastapi import Request
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import InviteOut, UserOut
from app.core.errors import AppError
from app.core.security import tokens
from app.db.models import AccessCode, User, utcnow
from app.services import auth, devices, downloads, limits


async def require_admin(db: AsyncSession, request: Request) -> User:
    user = await auth.current_user(db, request)
    if user.role != "admin":
        raise AppError(403, "forbidden")
    # Сеанс администратора без 2FA не выдается; проверка здесь — второй рубеж для /admin/*
    if not user.totp_enabled:
        raise AppError(403, "setup_required")
    return user


async def confirm_admin(db: AsyncSession, request: Request, code: str) -> User:
    # Общая транзакционная блокировка делает проверку последнего администратора атомарной.
    await require_admin(db, request)
    await db.execute(text("SELECT pg_advisory_xact_lock(74623019)"))
    actor = await auth.current_user(db, request, touch=False)
    actor = await db.scalar(
        select(User)
        .where(User.id == actor.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if actor.status != "active" or actor.role != "admin":
        raise AppError(403, "forbidden")
    await limits.attempt("admin-factor", str(actor.id))
    await auth.consume_factor(db, actor, code)
    return actor


async def members(
    db: AsyncSession, request: Request, q: str, status: str | None, limit: int, offset: int
) -> dict:
    await require_admin(db, request)
    where = []
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append(
            User.email.ilike(f"%{escaped}%", escape="\\")
            | User.display_name.ilike(f"%{escaped}%", escape="\\")
        )
    if status:
        where.append(User.status == status)
    total = await db.scalar(select(func.count()).select_from(User).where(*where))
    rows = (
        await db.scalars(select(User).where(*where).order_by(User.id).limit(limit).offset(offset))
    ).all()
    return {"items": [UserOut.model_validate(x) for x in rows], "total": total}


async def _check_last_admin(db: AsyncSession, user: User) -> None:
    if user.role == "admin" and user.status == "active":
        count = await db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == "admin", User.status == "active")
        )
        if count <= 1:
            raise AppError(400, "last_admin")


async def update_member(db: AsyncSession, request: Request, user_id: int, body) -> UserOut:
    actor = await confirm_admin(db, request, body.code)
    user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    if not user:
        raise AppError(404, "not_found")
    limit_given = "device_limit" in body.model_fields_set
    if body.status is None and body.role is None and not limit_given:
        raise AppError(400, "no_changes")
    if user.id == actor.id:
        raise AppError(400, "self_change_forbidden")
    next_role, next_status = body.role or user.role, body.status or user.status
    if next_role != "admin" or next_status != "active":
        await _check_last_admin(db, user)
    changed = next_role != user.role or next_status != user.status
    demoted = user.role == "admin" and next_role == "member"
    user.role, user.status = next_role, next_status
    if demoted:
        # Участнику 2FA не нужна: данные второго фактора удаляются, как у всех участников
        await auth.clear_two_factor(db, user)
    if changed:
        # Назначенный администратор без 2FA при следующем входе сначала настроит ее
        await auth.revoke_access(db, user)
        auth.audit(db, "member.updated", actor.id, user.id)
    if limit_given and body.device_limit != user.device_limit:
        # Новый лимит действует со следующего входа в приложение; вошедшие устройства остаются
        user.device_limit = body.device_limit
        auth.audit(db, "member.device_limit", actor.id, user.id)
    await db.commit()
    await limits.clear("admin-factor", str(actor.id))
    return UserOut.model_validate(user)


async def delete_member(db: AsyncSession, request: Request, user_id: int, code: str) -> None:
    """Полное удаление участника: аккаунт и все, что к нему относится.

    Каскадом удаляются входы, доверенные браузеры, шаги входа, резервные коды, устройства
    приложения и коды сброса; отдельно — приглашения на его почту. Журнал скачиваний
    сохраняет записи без участника (user_id = NULL), журнал действий — только номера.
    """
    actor = await confirm_admin(db, request, code)
    user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    if not user:
        raise AppError(404, "not_found")
    if user.id == actor.id:
        raise AppError(400, "self_change_forbidden")
    await _check_last_admin(db, user)
    await db.execute(
        delete(AccessCode).where(AccessCode.kind == "invite", AccessCode.email == user.email)
    )
    await db.execute(delete(User).where(User.id == user.id))
    auth.audit(db, "member.deleted", actor.id, user_id)
    await db.commit()
    await limits.clear("admin-factor", str(actor.id))


async def invites(db: AsyncSession, request: Request, limit: int, offset: int) -> dict:
    await require_admin(db, request)
    total = await db.scalar(
        select(func.count()).select_from(AccessCode).where(AccessCode.kind == "invite")
    )
    rows = (
        await db.scalars(
            select(AccessCode)
            .where(AccessCode.kind == "invite")
            .order_by(AccessCode.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return {"items": [InviteOut.model_validate(x) for x in rows], "total": total}


async def create_invite(db: AsyncSession, request: Request, body) -> dict:
    actor = await confirm_admin(db, request, body.code)
    if await db.scalar(select(User.id).where(User.email == body.email)):
        raise AppError(409, "account_exists")
    raw = tokens.gen_invite_code()
    invite = AccessCode(
        kind="invite",
        email=body.email,
        role=body.role,
        code_hash=tokens.hash_code(raw, tokens.INVITE_PREFIX),
        created_by=actor.id,
        expires_at=utcnow() + timedelta(days=body.expires_in_days),
    )
    db.add(invite)
    await db.flush()
    auth.audit(db, "invite.created", actor.id, invite.id)
    await db.commit()
    await limits.clear("admin-factor", str(actor.id))
    return {"invite": InviteOut.model_validate(invite), "code": raw}


async def revoke_invite(db: AsyncSession, request: Request, invite_id: int, code: str) -> InviteOut:
    actor = await confirm_admin(db, request, code)
    invite = await db.scalar(
        select(AccessCode)
        .where(AccessCode.id == invite_id, AccessCode.kind == "invite")
        .with_for_update()
    )
    if not invite:
        raise AppError(404, "not_found")
    invite.revoked_at = utcnow()
    auth.audit(db, "invite.revoked", actor.id, invite.id)
    await db.commit()
    await limits.clear("admin-factor", str(actor.id))
    return InviteOut.model_validate(invite)


async def delete_invite(db: AsyncSession, request: Request, invite_id: int, code: str) -> None:
    """Удаляет приглашение в любом состоянии; действующее перестает работать сразу."""
    actor = await confirm_admin(db, request, code)
    invite = await db.scalar(
        select(AccessCode)
        .where(AccessCode.id == invite_id, AccessCode.kind == "invite")
        .with_for_update()
    )
    if not invite:
        raise AppError(404, "not_found")
    await db.execute(delete(AccessCode).where(AccessCode.id == invite.id))
    auth.audit(db, "invite.deleted", actor.id, invite_id)
    await db.commit()
    await limits.clear("admin-factor", str(actor.id))


async def reset_code(db: AsyncSession, request: Request, user_id: int, code: str) -> dict:
    actor = await confirm_admin(db, request, code)
    user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    if not user or user.status != "active":
        raise AppError(404, "not_found")
    await db.execute(
        update(AccessCode)
        .where(
            AccessCode.user_id == user.id,
            AccessCode.kind == "password_reset",
            AccessCode.used_at.is_(None),
        )
        .values(revoked_at=utcnow())
    )
    raw = tokens.gen_reset_code()
    expires_at = utcnow() + timedelta(hours=24)
    db.add(
        AccessCode(
            kind="password_reset",
            user_id=user.id,
            email=user.email,
            role=user.role,
            created_by=actor.id,
            code_hash=tokens.hash_code(raw, tokens.RESET_PREFIX),
            expires_at=expires_at,
        )
    )
    auth.audit(db, "password_reset.created", actor.id, user.id)
    await db.commit()
    await limits.clear("admin-factor", str(actor.id))
    return {"code": raw, "expires_at": expires_at}


async def _member(db: AsyncSession, user_id: int) -> User:
    user = await db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise AppError(404, "not_found")
    return user


async def member_devices(db: AsyncSession, request: Request, user_id: int) -> dict:
    await require_admin(db, request)
    # С запросом: на своей карточке администратор видит текущий браузер и не завершит его
    return await devices.overview(db, await _member(db, user_id), request)


async def revoke_member_session(
    db: AsyncSession, request: Request, user_id: int, session_id: int
) -> None:
    # Завершение входа только защищает участника, поэтому без повторного кода 2FA
    actor = await require_admin(db, request)
    await devices.revoke_session(db, await _member(db, user_id), session_id, actor.id)


async def revoke_member_device(
    db: AsyncSession, request: Request, user_id: int, device_id: int
) -> None:
    actor = await require_admin(db, request)
    # Удаленное администратором устройство не тратит лимит смены устройств участника
    await devices.revoke_device(db, await _member(db, user_id), device_id, actor.id, by_admin=True)


async def download_history(
    db: AsyncSession, request: Request, user_id: int | None, limit: int, offset: int
) -> dict:
    await require_admin(db, request)
    return await downloads.history(db, user_id, limit, offset)
