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
from app.services import admin, auth, downloads

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


@router.post("/admin/members/{user_id}/reset-code", response_model=schemas.ResetCodeOut)
async def reset_code(user_id: int, body: schemas.ConfirmIn, request: Request, db: Db) -> dict:
    return await admin.reset_code(db, request, user_id, body.code)


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


@router.get("/downloads", response_model=schemas.DownloadsOut)
async def catalog(request: Request, db: Db) -> dict:
    return await downloads.catalog(db, request)


@router.get("/downloads/{platform}/file")
async def download(platform: str, request: Request, db: Db):
    return await downloads.download(db, request, platform)
