"""Argon2id RFC 9106: профиль и ограниченный пул перенесены из AI Agent Capper."""

import asyncio
import weakref
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import cache

import anyio
from argon2 import PasswordHasher, profiles
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import get_settings
from app.core.errors import AppError

PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128
_hasher = PasswordHasher.from_parameters(profiles.RFC_9106_LOW_MEMORY)
_slots: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


@asynccontextmanager
async def _hash_slot() -> AsyncIterator[None]:
    loop = asyncio.get_running_loop()
    semaphore = _slots.setdefault(
        loop, asyncio.Semaphore(max(get_settings().password_hash_slots, 1))
    )
    try:
        async with asyncio.timeout(10):
            await semaphore.acquire()
    except TimeoutError:
        raise AppError(503, "busy", retry_after=5) from None
    try:
        yield
    finally:
        semaphore.release()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


@cache
def _dummy_hash() -> str:
    return hash_password("private-gateway-dummy-for-timing")


async def hash_password_async(password: str) -> str:
    async with _hash_slot():
        return await anyio.to_thread.run_sync(hash_password, password)


async def verify_password_async(password_hash: str | None, password: str) -> bool:
    async with _hash_slot():

        def check() -> bool:
            matched = verify_password(password_hash or _dummy_hash(), password)
            return bool(password_hash) and matched

        return await anyio.to_thread.run_sync(check)


async def verify_dummy_async(password: str) -> None:
    await verify_password_async(None, password)


def validate_password_policy(password: str) -> None:
    if len(password) < PASSWORD_MIN_LENGTH:
        raise AppError(400, "password_too_short")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise AppError(400, "password_too_long")
