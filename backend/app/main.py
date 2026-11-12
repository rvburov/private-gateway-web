"""HTTP API отдельного сайта. Никаких изменений VPN, сети или ОС при запуске."""

import hmac
import logging
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse

from app.api.routes import router
from app.core.config import get_settings
from app.core.cookies import cookie_name
from app.core.errors import AppError
from app.core.security.crypto import CryptoError
from app.db.session import get_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_settings()
    yield
    await get_engine().dispose()


class SecurityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        settings = get_settings()
        origin = request.headers.get("origin")
        referer = request.headers.get("referer")
        cross_site = request.headers.get("sec-fetch-site") == "cross-site"
        # Приложение входит и проверяет доступ по токену в Authorization, без cookie сайта:
        # подделка запроса из чужой страницы ничего не дает, поэтому CSRF к /api/app/ не нужен
        app_api = request.url.path.startswith("/api/app/")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if not origin and referer:
                ref = urlsplit(referer)
                origin = f"{ref.scheme}://{ref.netloc}"
            cookie = request.cookies.get(cookie_name("csrf"), "")
            token = request.headers.get("x-csrf-token", "")
            if not app_api and (
                cross_site
                or (origin is not None and origin != settings.public_origin)
                or not cookie
                or len(cookie) > 128
                or len(token) > 128
                or not hmac.compare_digest(cookie.encode(), token.encode())
            ):
                response = JSONResponse({"error": {"code": "csrf_failed"}}, status_code=403)
                response.headers["Cache-Control"] = "no-store"
                return await response(scope, receive, send)
            # API формы маленькие; не буферизуем произвольное тело в памяти.
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body.extend(message.get("body", b""))
                if len(body) > 16384:
                    return await JSONResponse(
                        {"error": {"code": "request_too_large"}}, status_code=413
                    )(scope, receive, send)
                if not message.get("more_body", False):
                    break
            sent = False
            original_receive = receive

            async def replay():
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await original_receive()

            receive = replay

        async def secure_send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"cache-control", b"no-store"),
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"x-frame-options", b"DENY"),
                    ]
                )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, secure_send)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Private Gateway Web",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.add_middleware(SecurityMiddleware)
    app.include_router(router)

    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError):
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        return JSONResponse({"error": {"code": exc.code}}, status_code=exc.status, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Pydantic input может содержать пароль; в ответах и логах его не показываем.
        return JSONResponse({"error": {"code": "validation_error"}}, status_code=422)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError):
        logging.getLogger("pgweb").error("database operation failed: %s", type(exc).__name__)
        return JSONResponse({"error": {"code": "service_unavailable"}}, status_code=503)

    @app.exception_handler(CryptoError)
    async def crypto_error(request: Request, exc: CryptoError):
        logging.getLogger("pgweb").error("encrypted value cannot be read")
        return JSONResponse({"error": {"code": "service_unavailable"}}, status_code=503)

    return app


app = create_app()
