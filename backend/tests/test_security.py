"""Проверки границ перенесенных из Capper примитивов, без настоящих учетных данных."""

import re

import pytest

from app.core.security import crypto, tokens, totp

NOW = 1_800_000_000.0


def test_tokens_are_random_and_only_hashes_are_stored():
    first, second = tokens.new_token(), tokens.new_token()
    assert first != second
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", first)
    assert re.fullmatch(r"[0-9a-f]{64}", tokens.hash_token(first))
    assert tokens.hash_token(first) != first
    assert tokens.hash_token(first) != tokens.hash_token(second)


def test_codes_normalize_but_hashes_are_keyed():
    code = tokens.gen_invite_code()
    assert code.startswith("PG-")
    assert tokens.hash_code(code) == tokens.hash_code(code.lower().replace("-", " "))
    assert tokens.hash_code(code) != tokens.hash_token(tokens.normalize_code(code))
    assert tokens.hash_code(code) != tokens.hash_code(tokens.gen_invite_code())
    backups = tokens.gen_recovery_codes()
    assert len(backups) == len(set(backups)) == 8


def test_totp_has_bounded_time_window_and_rejects_replay():
    secret = totp.new_totp_secret()
    step = totp.current_step(NOW)
    for offset in (-1, 0, 1):
        code = totp.code_at_step(secret, step + offset)
        assert totp.verify_totp(secret, code, last_step=None, now=NOW) == step + offset
    for offset in (-3, 3):
        code = totp.code_at_step(secret, step + offset)
        assert totp.verify_totp(secret, code, last_step=None, now=NOW) is None
    code = totp.code_at_step(secret, step)
    assert totp.verify_totp(secret, code, last_step=step, now=NOW) is None
    assert totp.verify_totp(secret, code, last_step=step + 1, now=NOW) is None


def test_totp_accepts_keyboard_digits_but_not_similar_symbols():
    secret = totp.new_totp_secret()
    step = totp.current_step(NOW)
    code = totp.code_at_step(secret, step)
    fullwidth = "".join(chr(ord("０") + int(digit)) for digit in code)
    assert totp.verify_totp(secret, fullwidth, last_step=None, now=NOW) == step
    assert totp.verify_totp(secret, code[:5] + "²", last_step=None, now=NOW) is None
    assert totp.verify_totp(secret, "12345", last_step=None, now=NOW) is None


def test_totp_qr_uses_gateway_issuer_without_remote_image():
    secret = totp.new_totp_secret()
    uri = totp.totp_uri(secret, "member@example.test")
    assert uri.startswith("otpauth://totp/")
    assert "Private%20Gateway" in uri
    svg = totp.qr_svg(uri)
    assert svg.startswith("<svg") and "</svg>" in svg
    assert "<image" not in svg


def test_encrypted_secret_is_bound_to_its_row_and_authenticated():
    plain = "test-only-totp-material"
    aad = crypto.aad_for(crypto.AAD_TOTP_SECRET, 17)
    cipher, version = crypto.encrypt_str(plain, aad)
    assert plain.encode() not in cipher
    assert crypto.decrypt_str(cipher, version, aad) == plain
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt_str(cipher, version, crypto.aad_for(crypto.AAD_TOTP_SECRET, 18))
    damaged = cipher[:-1] + bytes([cipher[-1] ^ 1])
    with pytest.raises(crypto.CryptoError):
        crypto.decrypt_str(damaged, version, aad)


async def test_password_hash_is_argon2id_and_wrong_or_broken_hash_fails():
    from app.core.security.passwords import hash_password_async, verify_password_async

    password = "synthetic-test-password-for-argon"
    first = await hash_password_async(password)
    second = await hash_password_async(password)
    assert first.startswith("$argon2id$")
    assert first != second and password not in first
    assert await verify_password_async(first, password)
    assert not await verify_password_async(first, password + "-wrong")
    assert not await verify_password_async("invalid-hash", password)


def test_production_session_cookie_has_host_bound_secure_flags():
    from starlette.responses import Response

    from app.core.config import get_settings
    from app.core.cookies import set_cookie

    settings = get_settings().model_copy(
        update={
            "public_origin": "https://gateway.example.test",
            "cookie_secure": True,
        }
    )
    response = Response()
    set_cookie(response, "session", "test-only-token", settings)
    header = response.headers["set-cookie"]
    assert header.startswith("__Host-")
    assert "Secure" in header and "HttpOnly" in header and "SameSite=lax" in header
    assert "Path=/" in header and "Domain=" not in header
