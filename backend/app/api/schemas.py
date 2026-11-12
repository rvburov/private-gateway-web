"""Контракты Capper сокращены до входа, доступа и скачивания клиента."""

import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)


def no_nul(value: str) -> str:
    if "\x00" in value:
        raise ValueError("nul")
    return value


def email(value: str) -> str:
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        raise ValueError("email")
    return value.lower()


Text = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=320),
    AfterValidator(no_nul),
]
Email = Annotated[Text, AfterValidator(email)]
Password = Annotated[str, StringConstraints(min_length=1, max_length=4096), AfterValidator(no_nul)]
Code = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    AfterValidator(no_nul),
]
Totp = Annotated[str, StringConstraints(pattern=r"^[0-9]{6}$")]
Role = Literal["admin", "member"]
Status = Literal["active", "blocked"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginIn(Input):
    email: Text
    password: Password


class RegisterIn(Input):
    invite_code: Code
    email: Email
    display_name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=2, max_length=100),
        AfterValidator(no_nul),
    ]
    password: Password


class FactorIn(Input):
    code: Totp | None = None
    recovery_code: Code | None = None
    remember_device: bool = False

    @model_validator(mode="after")
    def one_code(self) -> "FactorIn":
        if (self.code is None) == (self.recovery_code is None):
            raise ValueError("code_or_recovery_code")
        return self


class ConfirmIn(Input):
    code: Totp


class ResetIn(Input):
    email: Text
    code: Code
    new_password: Password


class InviteIn(ConfirmIn):
    email: Email
    role: Role = "member"
    expires_in_days: int = Field(default=7, ge=1, le=30)


class MemberIn(ConfirmIn):
    status: Status | None = None
    role: Role | None = None
    # Свой лимит устройств приложения; null — вернуть общий (PGWEB_DEVICE_LIMIT)
    device_limit: int | None = Field(default=None, ge=1, le=50)


DeviceUid = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{16,64}$")]
AppPlatform = Literal["windows", "macos", "linux", "android", "ios"]


class AppDeviceIn(Input):
    uid: DeviceUid
    name: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
        AfterValidator(no_nul),
    ]
    platform: AppPlatform
    app_version: Annotated[str, StringConstraints(pattern=r"^[0-9A-Za-z.+~-]{1,64}$")]


class AppLoginIn(Input):
    email: Text
    password: Password
    code: Totp | None = None
    recovery_code: Code | None = None
    device: AppDeviceIn

    @model_validator(mode="after")
    def one_code(self) -> "AppLoginIn":
        if (self.code is None) == (self.recovery_code is None):
            raise ValueError("code_or_recovery_code")
        return self


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    display_name: str
    role: Role
    status: Status
    totp_enabled: bool
    device_limit: int | None = None
    created_at: datetime


class InviteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    role: Role
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None
    revoked_at: datetime | None


class LoginOut(BaseModel):
    status: Literal["ok", "totp_required", "totp_setup_required"]
    user: UserOut | None = None


class CsrfOut(BaseModel):
    csrf_token: str


class StatusOut(BaseModel):
    status: Literal["ok"]


class HealthOut(StatusOut):
    version: str


class SetupOut(BaseModel):
    secret: str
    otpauth_uri: str
    qr_svg: str


class SetupDoneOut(BaseModel):
    status: Literal["ok"]
    user: UserOut
    recovery_codes: list[str]


class MembersOut(BaseModel):
    items: list[UserOut]
    total: int


class InvitesOut(BaseModel):
    items: list[InviteOut]
    total: int


class InviteCreatedOut(BaseModel):
    invite: InviteOut
    code: str


class ResetCodeOut(BaseModel):
    code: str
    expires_at: datetime


class DownloadOut(BaseModel):
    platform: Literal["windows", "macos", "ios", "linux", "android"]
    available: bool
    version: str | None
    filename: str | None
    size_bytes: int | None
    sha256: str | None
    url: str | None


class DownloadsOut(BaseModel):
    items: list[DownloadOut]


class AppUserOut(BaseModel):
    email: str
    display_name: str


class AppDeviceOut(BaseModel):
    id: int
    name: str
    platform: AppPlatform
    app_version: str
    ip_masked: str | None
    created_at: datetime
    last_seen_at: datetime


class AppLoginOut(BaseModel):
    token: str
    expires_at: datetime
    user: AppUserOut
    device: AppDeviceOut


class AppStatusOut(BaseModel):
    status: Literal["ok"]
    expires_at: datetime
    user: AppUserOut
    device: AppDeviceOut


class SessionOut(BaseModel):
    id: int
    label: str
    ip_masked: str | None
    created_at: datetime
    last_seen_at: datetime
    current: bool


class DevicesOut(BaseModel):
    sessions: list[SessionOut]
    devices: list[AppDeviceOut]
    session_limit: int
    device_limit: int


class DownloadUserOut(BaseModel):
    id: int
    email: str
    display_name: str


class DownloadEventOut(BaseModel):
    id: int
    at: datetime
    platform: Literal["windows", "macos", "ios", "linux", "android"]
    version: str
    filename: str | None
    ip_masked: str | None
    device: str
    user: DownloadUserOut | None


class DownloadEventsOut(BaseModel):
    items: list[DownloadEventOut]
    total: int
