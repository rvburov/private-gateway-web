"""Конфигурация отдельного сайта; ключи никогда не получают значения по умолчанию."""

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PGWEB_", extra="ignore", hide_input_in_errors=True
    )

    database_url: str = Field(repr=False)
    secret_key: str = Field(repr=False)
    master_keys: str = Field(repr=False)
    public_origin: str = "http://127.0.0.1:5173"
    cookie_secure: bool = True
    password_hash_slots: int = Field(default=2, ge=1, le=16)
    login_pending_minutes: int = Field(default=10, ge=1, le=30)
    trusted_device_days: int = Field(default=30, ge=1, le=30)
    session_absolute_days: int = Field(default=30, ge=1, le=30)
    session_idle_days: int = Field(default=14, ge=1, le=30)
    # Одновременные входы на сайт: при превышении завершается самый давний сеанс
    session_limit: int = Field(default=3, ge=1, le=20)
    # Устройства с приложением на участника (если у него не задан свой лимит)
    device_limit: int = Field(default=3, ge=1, le=50)
    # Токен устройства приложения продлевается при каждой проверке; без проверок гаснет
    app_token_days: int = Field(default=30, ge=1, le=90)
    download_root: Path = Path("downloads")
    # Хеш коммита, из которого собран образ API: по нему deploy.sh видит, что отвечает новая версия
    version: str = Field(default="dev", pattern=r"^[0-9A-Za-z._-]{1,40}$")

    @field_validator("database_url")
    @classmethod
    def postgres_only(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("PostgreSQL asyncpg URL required")
        return value

    @field_validator("secret_key")
    @classmethod
    def secret_hex(cls, value: str) -> str:
        if len(bytes.fromhex(value)) != 32:
            raise ValueError("secret_key must contain 32 random bytes as hex")
        return value

    @field_validator("master_keys")
    @classmethod
    def valid_keys(cls, value: str) -> str:
        versions: set[int] = set()
        for entry in value.split(","):
            version, key = entry.strip().split(":", 1)
            if int(version) < 1 or int(version) in versions or len(bytes.fromhex(key)) != 32:
                raise ValueError("master_keys requires unique positive version:64hex entries")
            versions.add(int(version))
        return value

    @field_validator("public_origin")
    @classmethod
    def origin_only(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("public_origin must be an absolute origin")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("origin cannot contain credentials/query/fragment")
        return value.rstrip("/")

    @model_validator(mode="after")
    def secure_origin(self) -> "Settings":
        if self.cookie_secure and not self.public_origin.startswith("https://"):
            raise ValueError("secure cookies require HTTPS public_origin")
        if not self.cookie_secure and urlsplit(self.public_origin).hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
            "testserver",
        }:
            raise ValueError("insecure cookies are only allowed on loopback development origins")
        return self

    @property
    def secret_key_bytes(self) -> bytes:
        return bytes.fromhex(self.secret_key)

    @property
    def master_key_map(self) -> dict[int, bytes]:
        return {
            int(v): bytes.fromhex(k)
            for v, k in (p.strip().split(":", 1) for p in self.master_keys.split(","))
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
