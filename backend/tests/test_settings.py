"""Конфигурация не ослабляет production-cookie и не раскрывает ключи при ошибке."""

import secrets

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def settings(**overrides):
    values = {
        "database_url": "postgresql+asyncpg://unused:unused@127.0.0.1/pgweb_test",
        "secret_key": secrets.token_hex(32),
        "master_keys": "1:" + secrets.token_hex(32),
        "public_origin": "https://gateway.example.com",
        "cookie_secure": True,
    }
    return Settings(**(values | overrides))


def test_remote_origin_requires_secure_cookies():
    with pytest.raises(ValidationError):
        settings(cookie_secure=False)
    with pytest.raises(ValidationError):
        settings(public_origin="http://gateway.example.com")
    assert settings(public_origin="http://127.0.0.1:5173", cookie_secure=False)


def test_invalid_secret_is_not_echoed_in_errors():
    invalid_secret = "PRIVATE-INPUT-THAT-MUST-NOT-APPEAR"
    with pytest.raises(ValidationError) as caught:
        settings(secret_key=invalid_secret)
    assert invalid_secret not in str(caught.value)
    assert "secret_key=" not in repr(settings())


def test_key_versions_and_resource_limits():
    with pytest.raises(ValidationError):
        settings(master_keys="1:" + secrets.token_hex(32) + ",1:" + secrets.token_hex(32))
    with pytest.raises(ValidationError):
        settings(password_hash_slots=1000)
    with pytest.raises(ValidationError):
        settings(trusted_device_days=3650)


@pytest.mark.parametrize(
    "origin", ["https://user:password@example.com", "https://example.com/path"]
)
def test_origin_cannot_contain_credentials_or_path(origin):
    with pytest.raises(ValidationError):
        settings(public_origin=origin)


def test_version_is_a_short_safe_token():
    assert settings().version == "dev"
    assert settings(version="4771282596c8").version == "4771282596c8"
    for bad in ["", "x" * 41, "1.0 <script>", "a/b"]:
        with pytest.raises(ValidationError):
            settings(version=bad)
