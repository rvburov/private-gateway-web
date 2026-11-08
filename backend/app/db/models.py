"""Модели доступа к сайту: адаптация auth-моделей Capper без данных VPN и AI."""

from datetime import UTC, datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, LargeBinary, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {datetime: DateTime(timezone=True)}


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin','member')", name="user_role"),
        CheckConstraint("status IN ('active','blocked')", name="user_status"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16), default="member")
    status: Mapped[str] = mapped_column(String(16), default="active")
    totp_enabled: Mapped[bool] = mapped_column(default=False)
    totp_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    totp_key_version: Mapped[int | None]
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger)
    auth_version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class UserSession(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    id_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    auth_version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(index=True)
    revoked_at: Mapped[datetime | None]


class TrustedDevice(Base):
    __tablename__ = "trusted_devices"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    auth_version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(index=True)
    revoked_at: Mapped[datetime | None]


class LoginChallenge(Base):
    __tablename__ = "login_challenges"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    auth_version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(index=True)
    consumed_at: Mapped[datetime | None]
    setup_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    setup_key_version: Mapped[int | None]


class RecoveryCode(Base):
    __tablename__ = "recovery_codes"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    used_at: Mapped[datetime | None]


class AccessCode(Base):
    __tablename__ = "access_codes"
    __table_args__ = (
        CheckConstraint("kind IN ('invite','password_reset')", name="access_kind"),
        CheckConstraint("role IN ('admin','member')", name="access_role"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(16), default="member")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(index=True)
    used_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]


class RateLimit(Base):
    __tablename__ = "rate_limits"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int]
    expires_at: Mapped[datetime] = mapped_column(index=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    target_id: Mapped[int | None]
    action: Mapped[str] = mapped_column(String(64))
    at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class Release(Base):
    __tablename__ = "releases"
    __table_args__ = (
        CheckConstraint(
            "platform IN ('windows','macos','ios','linux','android')", name="release_platform"
        ),
    )
    platform: Mapped[str] = mapped_column(String(16), primary_key=True)
    version: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str | None] = mapped_column(String(200))
    storage_name: Mapped[str | None] = mapped_column(String(200))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    store_url: Mapped[str | None] = mapped_column(String(1000))
    enabled: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
