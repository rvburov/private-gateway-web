"""Модели доступа к сайту: адаптация auth-моделей Capper без данных VPN и AI."""

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    false,
    text,
)
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
    # Свой лимит устройств приложения; None — общий PGWEB_DEVICE_LIMIT (основа будущих тарифов)
    device_limit: Mapped[int | None]
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
    # Чем вошли: показывается участнику и администратору в списке устройств
    user_agent: Mapped[str | None] = mapped_column(String(300))
    ip_masked: Mapped[str | None] = mapped_column(String(64))


class TrustedDevice(Base):
    __tablename__ = "trusted_devices"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    auth_version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(index=True)
    revoked_at: Mapped[datetime | None]
    # Последний вход этого браузера: завершение входа гасит и вход без 2FA с него
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL"), index=True
    )


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


class AppUpdate(Base):
    """Выпуск в ленте обновлений программы: манифест update.json байт в байт и его подпись.

    Подпись (ECDSA, update.json.sig) и SHA-256 файлов проверяет сама программа встроенным
    ключом: сайт хранит манифест как есть и подделать обновление не может. Файлы манифеста
    лежат в хранилище выпусков по SHA-256. Повторный прием той же версии заменяет манифест и
    подпись — так приходит новая доля раскатки.
    """

    __tablename__ = "app_updates"
    __table_args__ = (
        CheckConstraint("channel IN ('stable','beta')", name="app_update_channel"),
        CheckConstraint("rollout BETWEEN 0 AND 100", name="app_update_rollout"),
    )
    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    channel: Mapped[str] = mapped_column(String(16))
    rollout: Mapped[int]
    # Время выпуска из манифеста (поле published)
    published_at: Mapped[datetime]
    manifest: Mapped[bytes] = mapped_column(LargeBinary)
    # Содержимое update.json.sig без пробелов по краям: base64 подписи DER
    signature: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


class DownloadEvent(Base):
    """Журнал скачиваний: кто, когда и какой выпуск получил. IP хранится маскированным."""

    __tablename__ = "download_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    platform: Mapped[str] = mapped_column(String(16))
    version: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str | None] = mapped_column(String(200))
    ip_masked: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class AppDevice(Base):
    """Устройство с приложением Private Gateway: вход в клиент по аккаунту сайта.

    Токен устройства хранится только хешем. Активное устройство — не отозвано, не истекло и
    выпущено при текущем auth_version участника (смена пароля или блокировка его гасят).
    Отозванные записи хранятся до очистки: по ним считается лимит смены устройств.
    """

    __tablename__ = "app_devices"
    __table_args__ = (
        CheckConstraint(
            "platform IN ('windows','macos','ios','linux','android')", name="app_device_platform"
        ),
        Index(
            "ux_app_devices_active_uid",
            "user_id",
            "device_uid",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    device_uid: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(100))
    platform: Mapped[str] = mapped_column(String(16))
    app_version: Mapped[str] = mapped_column(String(64))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    auth_version: Mapped[int]
    ip_masked: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(index=True)
    revoked_at: Mapped[datetime | None]
    # Первый вход этой установки (uid) в аккаунт: такие входы считает лимит смены устройств
    new_device: Mapped[bool] = mapped_column(default=False, server_default=false())
    # Удалено администратором: в лимите смены устройств участника не считается
    removed_by_admin: Mapped[bool] = mapped_column(default=False, server_default=false())
