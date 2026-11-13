import re
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import schemas
from app.core.config import get_settings
from app.core.cookies import cookie_name, set_cookie
from app.core.security.tokens import new_token
from app.db.session import get_db
from app.services import account, admin, auth, devices, downloads, updates

router = APIRouter(prefix="/api")
Db = Annotated[AsyncSession, Depends(get_db)]


@router.get("/health", response_model=schemas.HealthOut)
async def health() -> dict:
    return {"status": "ok", "version": get_settings().version}


@router.get("/ready", response_model=schemas.StatusOut)
async def ready(db: Db) -> dict:
    await db.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/auth/csrf", response_model=schemas.CsrfOut)
async def csrf(request: Request, response: Response) -> dict:
    token = request.cookies.get(cookie_name("csrf"), "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
        token = new_token()
    set_cookie(response, "csrf", token)
    return {"csrf_token": token}


@router.get("/me", response_model=schemas.UserOut)
async def me(request: Request, db: Db):
    return await auth.current_user(db, request)


@router.get("/me/devices", response_model=schemas.DevicesOut)
async def my_devices(request: Request, db: Db) -> dict:
    user = await auth.current_user(db, request)
    return await devices.overview(db, user, request)


@router.post("/me/sessions/{session_id}/revoke", status_code=204)
async def revoke_my_session(session_id: int, request: Request, db: Db) -> Response:
    user = await auth.current_user(db, request)
    await devices.revoke_session(db, user, session_id, user.id)
    return Response(status_code=204)


@router.post("/me/devices/{device_id}/revoke", status_code=204)
async def revoke_my_device(device_id: int, request: Request, db: Db) -> Response:
    user = await auth.current_user(db, request)
    await devices.revoke_device(db, user, device_id, user.id)
    return Response(status_code=204)


@router.post("/me/password", response_model=schemas.StatusOut)
async def change_password(
    body: schemas.PasswordChangeIn, request: Request, response: Response, db: Db
) -> dict:
    return await account.change_password(db, request, response, body)


@router.post("/me/sign-out-everywhere", response_model=schemas.StatusOut)
async def sign_out_everywhere(
    body: schemas.AdminCodeIn, request: Request, response: Response, db: Db
) -> dict:
    return await account.sign_out_everywhere(db, request, response, body)


@router.post("/auth/login", response_model=schemas.LoginOut)
async def login(body: schemas.LoginIn, request: Request, response: Response, db: Db) -> dict:
    return await auth.password_login(db, request, response, body.email, body.password)


@router.post("/auth/register", response_model=schemas.LoginOut)
async def register(body: schemas.RegisterIn, request: Request, response: Response, db: Db) -> dict:
    return await auth.register(db, request, response, body)


@router.post("/auth/2fa/setup", response_model=schemas.SetupOut)
async def setup(request: Request, db: Db) -> dict:
    return await auth.start_setup(db, request)


@router.post("/auth/2fa/setup/confirm", response_model=schemas.SetupDoneOut)
async def confirm(body: schemas.ConfirmIn, request: Request, response: Response, db: Db) -> dict:
    return await auth.confirm_setup(db, request, response, body.code)


@router.post("/auth/2fa", response_model=schemas.LoginOut)
async def factor(body: schemas.FactorIn, request: Request, response: Response, db: Db) -> dict:
    return await auth.second_factor(db, request, response, body)


@router.post("/auth/logout", status_code=204)
async def logout(request: Request, db: Db) -> Response:
    response = Response(status_code=204)
    await auth.logout(db, request, response)
    return response


@router.post("/auth/reset", response_model=schemas.StatusOut)
async def reset(body: schemas.ResetIn, request: Request, db: Db) -> dict:
    await auth.reset_password(db, request, body)
    return {"status": "ok"}


@router.get("/admin/members", response_model=schemas.MembersOut)
async def members(
    request: Request,
    db: Db,
    q: str = Query(default="", max_length=100),
    status: Literal["active", "blocked"] | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    return await admin.members(db, request, q, status, limit, offset)


@router.patch("/admin/members/{user_id}", response_model=schemas.UserOut)
async def update_member(user_id: int, body: schemas.MemberIn, request: Request, db: Db):
    return await admin.update_member(db, request, user_id, body)


@router.post("/admin/members/{user_id}/delete", status_code=204)
async def delete_member(user_id: int, body: schemas.ConfirmIn, request: Request, db: Db):
    await admin.delete_member(db, request, user_id, body.code)
    return Response(status_code=204)


@router.post("/admin/members/{user_id}/reset-code", response_model=schemas.ResetCodeOut)
async def reset_code(user_id: int, body: schemas.ConfirmIn, request: Request, db: Db) -> dict:
    return await admin.reset_code(db, request, user_id, body.code)


@router.get("/admin/members/{user_id}/devices", response_model=schemas.DevicesOut)
async def member_devices(user_id: int, request: Request, db: Db) -> dict:
    return await admin.member_devices(db, request, user_id)


@router.post("/admin/members/{user_id}/sessions/{session_id}/revoke", status_code=204)
async def revoke_member_session(user_id: int, session_id: int, request: Request, db: Db):
    await admin.revoke_member_session(db, request, user_id, session_id)
    return Response(status_code=204)


@router.post("/admin/members/{user_id}/devices/{device_id}/revoke", status_code=204)
async def revoke_member_device(user_id: int, device_id: int, request: Request, db: Db):
    await admin.revoke_member_device(db, request, user_id, device_id)
    return Response(status_code=204)


@router.get("/admin/downloads", response_model=schemas.DownloadEventsOut)
async def download_history(
    request: Request,
    db: Db,
    user_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    return await admin.download_history(db, request, user_id, limit, offset)


@router.get("/admin/invites", response_model=schemas.InvitesOut)
async def invites(
    request: Request,
    db: Db,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    return await admin.invites(db, request, limit, offset)


@router.post("/admin/invites", status_code=201, response_model=schemas.InviteCreatedOut)
async def create_invite(body: schemas.InviteIn, request: Request, db: Db) -> dict:
    return await admin.create_invite(db, request, body)


@router.post("/admin/invites/{invite_id}/revoke", response_model=schemas.InviteOut)
async def revoke_invite(invite_id: int, body: schemas.ConfirmIn, request: Request, db: Db):
    return await admin.revoke_invite(db, request, invite_id, body.code)


@router.post("/admin/invites/{invite_id}/delete", status_code=204)
async def delete_invite(invite_id: int, body: schemas.ConfirmIn, request: Request, db: Db):
    await admin.delete_invite(db, request, invite_id, body.code)
    return Response(status_code=204)


@router.get("/downloads", response_model=schemas.DownloadsOut)
async def catalog(request: Request, db: Db) -> dict:
    return await downloads.catalog(db, request)


@router.get("/downloads/{platform}/file")
async def download(platform: str, request: Request, db: Db):
    return await downloads.download(db, request, platform)


# Приложение Private Gateway: вход по аккаунту сайта, затем только заголовок Authorization.
# Cookie сайта эти маршруты не читают, поэтому CSRF к ним не применяется (main.py).
@router.post("/app/login", response_model=schemas.AppLoginOut)
async def app_login(body: schemas.AppLoginIn, request: Request, db: Db) -> dict:
    return await devices.app_login(db, request, body)


@router.get("/app/status", response_model=schemas.AppStatusOut)
async def app_status(request: Request, db: Db) -> dict:
    return await devices.app_status(db, request)


@router.post("/app/logout", status_code=204)
async def app_logout(request: Request, db: Db) -> Response:
    await devices.app_logout(db, request)
    return Response(status_code=204)


# Лента обновлений программы: подписанные манифесты и билеты на файлы своей платформы
@router.get("/app/updates", response_model=schemas.AppUpdatesOut)
async def app_updates(
    request: Request,
    db: Db,
    platform: schemas.UpdatePlatform,
    channel: schemas.UpdateChannel = "stable",
) -> dict:
    return await updates.feed(db, request, platform, channel)


# Файл обновления по билету из ленты: Authorization не нужен, билет сам дает право
@router.get("/app/updates/files/{ticket}")
async def app_update_file(ticket: str, request: Request, db: Db):
    return await updates.download(db, request, ticket)
