"""Локальное администрирование; секреты вводятся интерактивно или через stdin."""

import argparse
import asyncio
import getpass
import hashlib
import os
import re
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import SQLAlchemyError

from app.api.schemas import RegisterIn
from app.core.config import get_settings
from app.core.security.passwords import hash_password_async, validate_password_policy
from app.db.models import (
    AccessCode,
    AuditEvent,
    LoginChallenge,
    RateLimit,
    Release,
    TrustedDevice,
    User,
    UserSession,
    utcnow,
)
from app.db.session import get_engine, get_session_factory
from app.services.downloads import PLATFORMS, app_store_url


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(prog="python -m app.cli")
    commands = cli.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("bootstrap-admin", help="Создать первого администратора")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", default="Administrator")
    admin.add_argument(
        "--password-stdin", action="store_true", help="Прочитать пароль из stdin, не аргумента"
    )
    release = commands.add_parser("publish-release", help="Внести проверенный файл выпуска")
    release.add_argument("--platform", choices=[p for p in PLATFORMS if p != "ios"], required=True)
    release.add_argument("--version", required=True)
    release.add_argument("--file", type=Path, required=True)
    store = commands.add_parser("set-ios", help="Внести существующую ссылку App Store")
    store.add_argument("--url", required=True)
    store.add_argument("--version", required=True)
    disable = commands.add_parser("disable-release")
    disable.add_argument("--platform", choices=PLATFORMS, required=True)
    commands.add_parser("prune", help="Удалить истекшие временные записи и аудит старше90дней")
    return cli


def version(value: str) -> str:
    if len(value) > 64 or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", value):
        raise ValueError("Version must be a release version such as 1.2.3")
    return value


async def run(args: argparse.Namespace) -> None:
    settings = get_settings()
    async with get_session_factory()() as db:
        if args.command == "bootstrap-admin":
            password = (
                sys.stdin.readline().rstrip("\r\n")
                if args.password_stdin
                else getpass.getpass("Password: ")
            )
            if not args.password_stdin and password != getpass.getpass("Repeat password: "):
                raise ValueError("Passwords differ")
            data = RegisterIn(
                invite_code="bootstrap", email=args.email, display_name=args.name, password=password
            )
            validate_password_policy(password)
            password_hash = await hash_password_async(password)
            await db.execute(text("SELECT pg_advisory_xact_lock(74623019)"))
            if await db.scalar(select(func.count()).select_from(User)):
                raise ValueError("Bootstrap only works on an empty installation; use invitations")
            user = User(
                email=data.email,
                display_name=data.display_name,
                role="admin",
                password_hash=password_hash,
            )
            db.add(user)
            await db.flush()
            db.add(AuditEvent(actor_id=user.id, action="admin.bootstrapped"))
            await db.commit()
            print("Administrator created. Sign in and configure 2FA before accessing the cabinet.")
        elif args.command == "publish-release":
            release_version = version(args.version)
            source = args.file.resolve(strict=True)
            if not source.is_file() or not source.stat().st_size:
                raise ValueError("Release must be a nonempty regular file")
            filename = source.name
            if len(filename) > 200 or any(ord(c) < 32 for c in filename):
                raise ValueError("Invalid release filename")
            root = settings.download_root.resolve()
            root.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            size = 0
            fd, temporary = tempfile.mkstemp(prefix=".release-", dir=root)
            try:
                with os.fdopen(fd, "wb") as output, source.open("rb") as content:
                    while block := content.read(1024 * 1024):
                        digest.update(block)
                        output.write(block)
                        size += len(block)
                    output.flush()
                    os.fsync(output.fileno())
                storage_name = digest.hexdigest() + ".bin"
                os.chmod(temporary, 0o640)
                os.replace(temporary, root / storage_name)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            release = await db.get(Release, args.platform)
            if release is None:
                release = Release(platform=args.platform, version=release_version)
                db.add(release)
            release.version = release_version
            release.filename = filename
            release.storage_name = storage_name
            release.size_bytes = size
            release.sha256 = digest.hexdigest()
            release.enabled = True
            await db.commit()
            print(
                f"Release catalog updated: {args.platform}, {release_version}, {size} bytes, "
                f"SHA256 {digest.hexdigest()}"
            )
        elif args.command == "set-ios":
            if not app_store_url(args.url):
                raise ValueError("Expected existing HTTPS apps.apple.com URL with numeric app id")
            release_version = version(args.version)
            release = await db.get(Release, "ios")
            if release is None:
                release = Release(platform="ios", version=release_version)
                db.add(release)
            release.version, release.store_url, release.enabled = release_version, args.url, True
            await db.commit()
            print("iOS catalog entry updated")
        elif args.command == "disable-release":
            await db.execute(
                update(Release).where(Release.platform == args.platform).values(enabled=False)
            )
            await db.commit()
            print("Release disabled")
        elif args.command == "prune":
            now = utcnow()
            for model in (RateLimit, UserSession, TrustedDevice, LoginChallenge, AccessCode):
                await db.execute(delete(model).where(model.expires_at < now))
            await db.execute(delete(AuditEvent).where(AuditEvent.at < now - timedelta(days=90)))
            await db.commit()
            print("Expired records pruned")


def main() -> None:
    args = parser().parse_args()

    async def operation():
        try:
            await run(args)
        finally:
            await get_engine().dispose()

    try:
        asyncio.run(operation())
    except SQLAlchemyError:
        print("Database operation failed", file=sys.stderr)
        raise SystemExit(1) from None
    except (ValueError, FileNotFoundError) as error:
        # Сообщения ошибок не содержат введенный пароль или ключи.
        if type(error).__name__ == "ValidationError":
            print("Invalid input or configuration", file=sys.stderr)
        else:
            print(str(error), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
