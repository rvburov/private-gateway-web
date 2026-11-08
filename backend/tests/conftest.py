"""Изолированная тестовая БД и настоящие HTTP-запросы к приложению."""

import os
import secrets

import httpx
import pytest
from sqlalchemy.engine import make_url

# Значения создаются только для процесса тестов, реальные настройки не читаются.
os.environ["PGWEB_SECRET_KEY"] = secrets.token_hex(32)
os.environ["PGWEB_MASTER_KEYS"] = "1:" + secrets.token_hex(32)
os.environ["PGWEB_COOKIE_SECURE"] = "false"
os.environ["PGWEB_PUBLIC_ORIGIN"] = "http://testserver"
if "PGWEB_TEST_DATABASE_URL" in os.environ:
    os.environ["PGWEB_DATABASE_URL"] = os.environ["PGWEB_TEST_DATABASE_URL"]


from app.core.config import get_settings  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.db.session import get_engine, get_session_factory  # noqa: E402


@pytest.fixture
async def db_factory():
    url = os.environ.get("PGWEB_TEST_DATABASE_URL")
    if not url or "test" not in (make_url(url).database or "").lower():
        pytest.fail("PGWEB_TEST_DATABASE_URL must name a dedicated database containing 'test'")
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    engine = get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    yield get_session_factory()
    await engine.dispose()
    get_engine.cache_clear()
    get_session_factory.cache_clear()


@pytest.fixture
async def db(db_factory):
    async with db_factory() as session:
        yield session


@pytest.fixture
async def app(db_factory):
    from app.main import create_app

    return create_app()


@pytest.fixture
async def clients(app):
    opened: list[httpx.AsyncClient] = []

    async def create(*, csrf: bool = True, ip: str = "192.0.2.10"):
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=(ip, 12345)),
            base_url="http://testserver",
            headers={"Origin": "http://testserver"},
        )
        opened.append(client)
        if csrf:
            response = await client.get("/api/auth/csrf")
            assert response.status_code == 200, response.text
            client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        return client

    yield create
    for client in opened:
        await client.aclose()


@pytest.fixture
async def client(clients):
    return await clients()


@pytest.fixture
async def totp_clock(monkeypatch):
    import time

    from app.core.security import totp

    original = totp._timestamp
    clock = [time.time()]
    monkeypatch.setattr(totp, "_timestamp", lambda now: clock[0] if now is None else original(now))

    def next_code(user):
        clock[0] += totp.INTERVAL
        return totp.code_at_step(user["secret"], totp.current_step())

    return next_code
