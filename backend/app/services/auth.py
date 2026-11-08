"""Сценарии Capper на транзакциях PostgreSQL: вход, приглашения, 2FA и отзыв сеансов."""

from datetime import timedelta

from fastapi import Request, Response
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import UserOut
from app.core.config import get_settings
from app.core.cookies import clear_cookie, cookie_name, set_cookie
from app.core.errors import AppError
from app.core.security import crypto, passwords, tokens, totp
from app.db.models import (
    AccessCode,
    AuditEvent,
    LoginChallenge,
    RecoveryCode,
    TrustedDevice,
    User,
    UserSession,
    utcnow,
)
from app.services import limits
from app.services.two_factor import consume_recovery_code, consume_totp_step


def client_ip(request: Request) -> str:
    # X-Forwarded-For доверяет только настроенный reverse proxy самого ASGI-сервера.
    return request.client.host if request.client else "unknown"


def audit(
    db: AsyncSession, action: str, actor_id: int | None = None, target_id: int | None = None
) -> None:
    db.add(AuditEvent(actor_id=actor_id, target_id=target_id, action=action))


async def revoke_access(db: AsyncSession, user: User) -> None:
    now = utcnow()
    user.auth_version += 1
    await db.execute(
        update(UserSession).where(UserSession.user_id == user.id).values(revoked_at=now)
    )
    await db.execute(
        update(TrustedDevice).where(TrustedDevice.user_id == user.id).values(revoked_at=now)
    )
    await db.execute(
        update(LoginChallenge).where(LoginChallenge.user_id == user.id).values(consumed_at=now)
    )


async def current_user(db: AsyncSession, request: Request, *, touch: bool = True) -> User:
    token = request.cookies.get(cookie_name("session"), "")
    if not token or len(token) > 128:
        raise AppError(401, "unauthorized")
    now = utcnow()
    result = await db.execute(
        select(User, UserSession)
        .join(UserSession, UserSession.user_id == User.id)
        .where(
            UserSession.id_hash == tokens.hash_token(token),
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
            UserSession.last_seen_at > now - timedelta(days=get_settings().session_idle_days),
            UserSession.auth_version == User.auth_version,
            User.status == "active",
            User.totp_enabled.is_(True),
        )
    )
    pair = result.one_or_none()
    if not pair:
        raise AppError(401, "unauthorized")
    user, session = pair
    if touch and session.last_seen_at < now - timedelta(minutes=5):
        session.last_seen_at = now
        await db.commit()
    return user


async def new_session(
    db: AsyncSession, user: User, request: Request, response: Response, *, remember: bool = False
) -> dict:
    now = utcnow()
    old = request.cookies.get(cookie_name("session"))
    if old:
        await db.execute(
            update(UserSession)
            .where(UserSession.id_hash == tokens.hash_token(old))
            .values(revoked_at=now)
        )
    value = tokens.new_token()
    db.add(
        UserSession(
            user_id=user.id,
            id_hash=tokens.hash_token(value),
            auth_version=user.auth_version,
            expires_at=now + timedelta(days=get_settings().session_absolute_days),
        )
    )
    if remember:
        device = tokens.new_token()
        db.add(
            TrustedDevice(
                user_id=user.id,
                token_hash=tokens.hash_token(device),
                auth_version=user.auth_version,
                expires_at=now + timedelta(days=get_settings().trusted_device_days),
            )
        )
        set_cookie(response, "device", device)
    audit(db, "login.completed", user.id)
    await db.commit()
    set_cookie(response, "session", value)
    clear_cookie(response, "login")
    return {"status": "ok", "user": UserOut.model_validate(user)}


async def new_challenge(db: AsyncSession, user: User, request: Request, response: Response) -> dict:
    old = request.cookies.get(cookie_name("login"))
    if old:
        await db.execute(
            update(LoginChallenge)
            .where(LoginChallenge.token_hash == tokens.hash_token(old))
            .values(consumed_at=utcnow())
        )
    old_session = request.cookies.get(cookie_name("session"))
    if old_session:
        await db.execute(
            update(UserSession)
            .where(UserSession.id_hash == tokens.hash_token(old_session))
            .values(revoked_at=utcnow())
        )
    value = tokens.new_token()
    db.add(
        LoginChallenge(
            user_id=user.id,
            token_hash=tokens.hash_token(value),
            auth_version=user.auth_version,
            expires_at=utcnow() + timedelta(minutes=get_settings().login_pending_minutes),
        )
    )
    await db.commit()
    set_cookie(response, "login", value)
    clear_cookie(response, "session")
    return {"status": "totp_required" if user.totp_enabled else "totp_setup_required", "user": None}


async def challenge_user(db: AsyncSession, request: Request) -> tuple[LoginChallenge, User]:
    value = request.cookies.get(cookie_name("login"), "")
    if not value or len(value) > 128:
        raise AppError(401, "login_expired")
    # Всегда сначала пользователь, затем challenge: тот же порядок у отзыва доступа.
    challenge = await db.scalar(
        select(LoginChallenge).where(LoginChallenge.token_hash == tokens.hash_token(value))
    )
    if not challenge:
        raise AppError(401, "login_expired")
    user = await db.scalar(
        select(User)
        .where(User.id == challenge.user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    challenge = await db.scalar(
        select(LoginChallenge)
        .where(LoginChallenge.id == challenge.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        not user
        or not challenge
        or user.status != "active"
        or challenge.auth_version != user.auth_version
        or challenge.consumed_at
        or challenge.expires_at <= utcnow()
    ):
        raise AppError(401, "login_expired")
    return challenge, user


async def password_login(
    db: AsyncSession, request: Request, response: Response, email: str, password: str
) -> dict:
    identity = email.strip().lower()
    await limits.attempt("login-ip", client_ip(request))
    await limits.attempt("login-user", identity + ":" + client_ip(request))
    row = (
        await db.execute(select(User.id, User.password_hash).where(User.email == identity))
    ).one_or_none()
    await db.rollback()
    stored_hash = row.password_hash if row else None
    valid = await passwords.verify_password_async(stored_hash, password)
    if not valid or not row:
        raise AppError(401, "invalid_credentials")
    user = await db.scalar(select(User).where(User.id == row.id).with_for_update())
    if not user or user.status != "active" or user.password_hash != stored_hash:
        raise AppError(401, "invalid_credentials")
    if passwords.needs_rehash(stored_hash):
        user.password_hash = await passwords.hash_password_async(password)
    await limits.clear("login-user", identity + ":" + client_ip(request))
    await limits.clear("login-ip", client_ip(request))
    device = request.cookies.get(cookie_name("device"), "")
    if device and user.totp_enabled:
        trusted = await db.scalar(
            select(TrustedDevice).where(
                TrustedDevice.token_hash == tokens.hash_token(device),
                TrustedDevice.user_id == user.id,
                TrustedDevice.auth_version == user.auth_version,
                TrustedDevice.revoked_at.is_(None),
                TrustedDevice.expires_at > utcnow(),
            )
        )
        if trusted:
            return await new_session(db, user, request, response)
    return await new_challenge(db, user, request, response)


async def register(db: AsyncSession, request: Request, response: Response, body) -> dict:
    await limits.attempt("register", client_ip(request), limit=10, seconds=3600)
    passwords.validate_password_policy(body.password)
    code_hash = tokens.hash_code(body.invite_code, tokens.INVITE_PREFIX)
    invite = await db.scalar(
        select(AccessCode).where(AccessCode.code_hash == code_hash, AccessCode.kind == "invite")
    )
    if (
        not invite
        or invite.email != body.email
        or invite.revoked_at
        or invite.used_at
        or invite.expires_at <= utcnow()
    ):
        raise AppError(400, "invalid_invite")
    await db.rollback()
    password_hash = await passwords.hash_password_async(body.password)
    invite = await db.scalar(
        select(AccessCode).where(AccessCode.code_hash == code_hash).with_for_update()
    )
    if (
        not invite
        or invite.email != body.email
        or invite.revoked_at
        or invite.used_at
        or invite.expires_at <= utcnow()
    ):
        raise AppError(400, "invalid_invite")
    if await db.scalar(select(User.id).where(User.email == body.email)):
        raise AppError(409, "account_exists")
    user = User(
        email=body.email,
        display_name=body.display_name,
        password_hash=password_hash,
        role=invite.role,
    )
    db.add(user)
    invite.used_at = utcnow()
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise AppError(409, "account_exists") from None
    audit(db, "registration.completed", user.id, invite.id)
    return await new_challenge(db, user, request, response)


async def start_setup(db: AsyncSession, request: Request) -> dict:
    await limits.attempt("setup", client_ip(request), limit=30)
    challenge, user = await challenge_user(db, request)
    if user.totp_enabled:
        raise AppError(409, "already_configured")
    aad = crypto.aad_for(crypto.AAD_LOGIN_SETUP, user.id)
    if challenge.setup_secret_enc is None:
        secret = totp.new_totp_secret()
        challenge.setup_secret_enc, challenge.setup_key_version = crypto.encrypt_str(secret, aad)
        await db.commit()
    else:
        secret = crypto.decrypt_str(challenge.setup_secret_enc, challenge.setup_key_version, aad)
    uri = totp.totp_uri(secret, user.email)
    return {"secret": secret, "otpauth_uri": uri, "qr_svg": totp.qr_svg(uri)}


async def consume_factor(
    db: AsyncSession, user: User, code: str | None, recovery_code: str | None = None
) -> None:
    if not user.totp_enabled or user.totp_secret_enc is None:
        raise AppError(400, "setup_required")
    if recovery_code is not None:
        valid = await consume_recovery_code(db, user.id, tokens.hash_code(recovery_code))
    else:
        secret = crypto.decrypt_str(
            user.totp_secret_enc,
            user.totp_key_version,
            crypto.aad_for(crypto.AAD_TOTP_SECRET, user.id),
        )
        step = totp.verify_totp(secret, code or "", last_step=user.totp_last_step)
        valid = step is not None and await consume_totp_step(db, user.id, step)
    if not valid:
        raise AppError(400, "invalid_code")


async def confirm_setup(db: AsyncSession, request: Request, response: Response, code: str) -> dict:
    await limits.attempt("factor-ip", client_ip(request), limit=10)
    challenge, user = await challenge_user(db, request)
    await limits.attempt("factor-user", str(user.id))
    if user.totp_enabled:
        raise AppError(409, "already_configured")
    if challenge.setup_secret_enc is None:
        raise AppError(400, "setup_required")
    secret = crypto.decrypt_str(
        challenge.setup_secret_enc,
        challenge.setup_key_version,
        crypto.aad_for(crypto.AAD_LOGIN_SETUP, user.id),
    )
    step = totp.verify_totp(secret, code, last_step=None)
    if step is None:
        raise AppError(400, "invalid_code")
    user.totp_secret_enc, user.totp_key_version = crypto.encrypt_str(
        secret, crypto.aad_for(crypto.AAD_TOTP_SECRET, user.id)
    )
    user.totp_enabled = True
    user.totp_last_step = step
    challenge.consumed_at = utcnow()
    challenge.setup_secret_enc = None
    codes = tokens.gen_recovery_codes()
    await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    db.add_all([RecoveryCode(user_id=user.id, code_hash=tokens.hash_code(code)) for code in codes])
    outcome = await new_session(db, user, request, response)
    outcome["recovery_codes"] = codes
    await limits.clear("factor-user", str(user.id))
    return outcome


async def second_factor(db: AsyncSession, request: Request, response: Response, body) -> dict:
    await limits.attempt("factor-ip", client_ip(request), limit=10)
    challenge, user = await challenge_user(db, request)
    await limits.attempt("factor-user", str(user.id))
    await consume_factor(db, user, body.code, body.recovery_code)
    challenge.consumed_at = utcnow()
    result = await new_session(db, user, request, response, remember=body.remember_device)
    await limits.clear("factor-user", str(user.id))
    return result


async def logout(db: AsyncSession, request: Request, response: Response) -> None:
    now = utcnow()
    for kind, model, column in [
        ("session", UserSession, UserSession.id_hash),
        ("login", LoginChallenge, LoginChallenge.token_hash),
    ]:
        token = request.cookies.get(cookie_name(kind))
        if token:
            value = {"consumed_at": now} if kind == "login" else {"revoked_at": now}
            await db.execute(
                update(model).where(column == tokens.hash_token(token)).values(**value)
            )
        clear_cookie(response, kind)
    await db.commit()


async def reset_password(db: AsyncSession, request: Request, body) -> None:
    await limits.attempt("reset", client_ip(request))
    passwords.validate_password_policy(body.new_password)
    code_hash = tokens.hash_code(body.code, tokens.RESET_PREFIX)
    access = await db.scalar(
        select(AccessCode).where(
            AccessCode.code_hash == code_hash, AccessCode.kind == "password_reset"
        )
    )
    if (
        not access
        or access.email != body.email.strip().lower()
        or access.used_at
        or access.revoked_at
        or access.expires_at <= utcnow()
    ):
        raise AppError(400, "invalid_reset")
    user_id = access.user_id
    await db.rollback()
    password_hash = await passwords.hash_password_async(body.new_password)
    user = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    access = await db.scalar(
        select(AccessCode)
        .where(AccessCode.code_hash == code_hash)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        not user
        or user.status != "active"
        or not access
        or access.used_at
        or access.revoked_at
        or access.expires_at <= utcnow()
    ):
        raise AppError(400, "invalid_reset")
    user.password_hash = password_hash
    access.used_at = utcnow()
    await revoke_access(db, user)
    audit(db, "password.reset", user.id)
    await db.commit()
