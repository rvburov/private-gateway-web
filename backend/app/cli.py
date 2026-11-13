"""Локальное администрирование; секреты вводятся интерактивно или через stdin."""

import argparse
import asyncio
import getpass
import re
import sys
from pathlib import Path

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import SQLAlchemyError

from app.api.schemas import RegisterIn
from app.core.security.passwords import hash_password_async, validate_password_policy
from app.db.models import AuditEvent, Release, User
from app.db.session import get_engine, get_session_factory
from app.services import retention, updates
from app.services.downloads import PLATFORMS, app_store_url, store


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
    stored = commands.add_parser(
        "store-file", help="Положить проверенный файл в хранилище по SHA-256, без каталога"
    )
    stored.add_argument("--file", type=Path, required=True)
    feed = commands.add_parser(
        "publish-update", help="Внести подписанный манифест обновления (update.json)"
    )
    feed.add_argument("--version", required=True)
    feed.add_argument("--manifest", type=Path, required=True)
    feed.add_argument("--signature", type=Path, required=True)
    store = commands.add_parser("set-ios", help="Внести существующую ссылку App Store")
    store.add_argument("--url", required=True)
    store.add_argument("--version", required=True)
    disable = commands.add_parser("disable-release")
    disable.add_argument("--platform", choices=PLATFORMS, required=True)
    commands.add_parser(
        "purge", aliases=["prune"], help="Удалить ненужные записи (то же делает API раз в сутки)"
    )
    return cli


def version(value: str) -> str:
    if len(value) > 64 or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", value):
        raise ValueError("Version must be a release version such as 1.2.3")
    return value


def regular_file(path: Path) -> Path:
    source = path.resolve(strict=True)
    if not source.is_file() or not source.stat().st_size:
        raise ValueError(f"{path.name} must be a nonempty regular file")
    return source


def read_small(path: Path, limit: int) -> bytes:
    """Небольшой файл целиком; длиннее предела — отказ, а не обрезка."""
    with regular_file(path).open("rb") as content:
        data = content.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"{path.name} is larger than {limit} bytes")
    return data


async def run(args: argparse.Namespace) -> None:
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
            storage_name, size, sha256 = store(source)
            release = await db.get(Release, args.platform)
            if release is None:
                release = Release(platform=args.platform, version=release_version)
                db.add(release)
            release.version = release_version
            release.filename = filename
            release.storage_name = storage_name
            release.size_bytes = size
            release.sha256 = sha256
            release.enabled = True
            await db.commit()
            print(
                f"Release catalog updated: {args.platform}, {release_version}, {size} bytes, "
                f"SHA256 {sha256}"
            )
        elif args.command == "store-file":
            # Файл ленты обновлений (rpm и другие): только хранилище, каталог не меняется
            _, size, sha256 = store(regular_file(args.file))
            print(f"Stored {args.file.name}: {size} bytes, SHA256 {sha256}")
        elif args.command == "publish-update":
            manifest = read_small(args.manifest, updates.MANIFEST_MAX_BYTES)
            signature = read_small(args.signature, updates.SIGNATURE_MAX_BYTES + 64)
            result = await updates.publish(db, version(args.version), manifest, signature)
            print(
                f"Update feed: {result['version']}, rollout {result['rollout']} %, "
                f"files {', '.join(result['files'])}"
            )
            # Стоп-кран принимается и без файлов на сайте: до новой доли их нужно прислать заново
            if result["missing"]:
                print("Not in the download store yet: " + ", ".join(result["missing"]))
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
        elif args.command in ("purge", "prune"):
            counts = await retention.purge(db)
            if not counts:
                raise ValueError("Another purge is running; try again later")
            print("Purged: " + ", ".join(f"{name} {count}" for name, count in counts.items()))


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
