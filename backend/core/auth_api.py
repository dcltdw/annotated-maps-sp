from __future__ import annotations

from uuid import UUID

from django.contrib.auth.hashers import check_password, make_password
from ninja import Router, Schema, Status
from ninja.errors import HttpError
from pydantic import field_validator

from core.auth import authed_user, create_session
from core.models import User

router = Router()


class SignupIn(Schema):
    email: str
    password: str
    display_name: str

    @field_validator("password")
    @classmethod
    def _min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        return v

    @field_validator("display_name")
    @classmethod
    def _name_required(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("display_name is required")
        return v


class LoginIn(Schema):
    email: str
    password: str


class UserOut(Schema):
    id: UUID
    email: str | None
    display_name: str
    reputation: int


class AuthOut(Schema):
    token: str
    user: UserOut


@router.post("/signup", response={201: AuthOut})
def signup(request, payload: SignupIn):
    if User.objects.filter(email=payload.email).exists():
        raise HttpError(409, "That email is already registered.")
    user = User.objects.create(
        email=payload.email,
        password=make_password(payload.password),
        display_name=payload.display_name,
    )
    return Status(201, {"token": create_session(user, request), "user": user})


@router.post("/login", response=AuthOut)
def login(request, payload: LoginIn):
    user = User.objects.filter(email=payload.email).first()
    # ALWAYS run a hash check (dummy hash when no user / blank password) so response timing
    # doesn't leak whether the email exists. Generic error → no user enumeration.
    stored = user.password if user and user.password else make_password(None)
    password_ok = check_password(payload.password, stored)
    if user is None or not user.password or not password_ok:
        raise HttpError(401, "Invalid email or password.")
    return {"token": create_session(user, request), "user": user}


@router.post("/logout", response={204: None})
def logout(request):
    user = authed_user(request)
    if user is None:
        raise HttpError(401, "Not signed in.")
    # delete the specific presenting session
    from core.auth import hash_token

    header = request.headers.get("Authorization", "")
    token = header[len("Bearer ") :].strip()
    user.auth_sessions.filter(token_hash=hash_token(token)).delete()
    return Status(204, None)


@router.get("/me", response=UserOut)
def me(request):
    user = authed_user(request)
    if user is None:
        raise HttpError(401, "Not signed in.")
    return user
