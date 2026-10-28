# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sign-in for standalone mode, and `config`/`me` for both modes.

`GET /auth/config` is the one route the organizer page may call before
anyone is signed in: it says which mode runs and how one signs in. In
Nextcloud mode only `config` and `me` answer; the password routes 404 there
because Nextcloud is the identity provider.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from citizens.config import get_settings
from citizens.db.models.accounts import AppUser
from citizens.db.session import get_db
from citizens.logging_setup import get_logger
from citizens.security import sessions
from citizens.security.identity import CurrentUser
from citizens.security.passwords import verify_password
from citizens.security.rate_limit import SlidingWindowLimiter, client_ip
from citizens.services import accounts, mail
from citizens.services.audit import record_audit_event

log = get_logger(__name__)

router = APIRouter(prefix="/auth")

DB = Annotated[Session, Depends(get_db, scope="function")]

SUPPORTED_LANGUAGES = ("en", "it", "de", "fr", "es")

# a person mistypes a few times; a script does not get more than this per
# address or per account name before waiting a minute
LOGIN_IP_LIMITER = SlidingWindowLimiter(max_events=20, window_seconds=60)
LOGIN_NAME_LIMITER = SlidingWindowLimiter(max_events=8, window_seconds=60)
# reset mails: a handful an hour per address is a confused person, more is
# someone filling a stranger's mailbox
RESET_LIMITER = SlidingWindowLimiter(max_events=5, window_seconds=3600)
SET_PASSWORD_LIMITER = SlidingWindowLimiter(max_events=10, window_seconds=60)


def _standalone_only() -> None:
    if not get_settings().is_standalone():
        raise HTTPException(status_code=404, detail="Not available in Nextcloud mode")


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class ResetIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class SetPasswordIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class MeUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    language: Literal["en", "it", "de", "fr", "es"] | None = None
    current_password: str | None = Field(default=None, max_length=200)
    password: str | None = Field(default=None, max_length=200)


@router.get("/config")
def auth_config():
    """How this instance signs people in. Public: the login page needs it."""
    settings = get_settings()
    standalone = settings.is_standalone()
    return {
        "mode": "standalone" if standalone else "nextcloud",
        "version": settings.app_version,
        "login": {"password": standalone, "oidc": False},
        "mail": mail.configured() if standalone else False,
        "languages": list(SUPPORTED_LANGUAGES),
    }


@router.get("/me")
def me(request: Request, user: CurrentUser, session: DB):
    """The signed-in person. In Nextcloud mode only the id is known here."""
    if not get_settings().is_standalone():
        return {"id": user, "mode": "nextcloud"}
    account = session.get(AppUser, user)
    if account is None:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    return {**accounts.public_user(account), "mode": "standalone"}


@router.put("/me")
def update_me(data: MeUpdate, user: CurrentUser, session: DB):
    _standalone_only()
    account = session.get(AppUser, user)
    if account is None:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    if data.display_name is not None and data.display_name.strip():
        account.display_name = data.display_name.strip()
    if data.language is not None:
        account.language = data.language
    if data.password is not None:
        if not verify_password(data.current_password or "", account.password_hash):
            raise HTTPException(status_code=403, detail="The current password is wrong")
        try:
            accounts.set_password(session, account, data.password)
        except accounts.AccountError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        record_audit_event(session, "password_changed", "user", account.id, actor=user)
    return {**accounts.public_user(account), "mode": "standalone"}


@router.post("/login")
def login(data: LoginIn, request: Request, response: Response, session: DB):
    _standalone_only()
    LOGIN_IP_LIMITER.check(client_ip(request))
    LOGIN_NAME_LIMITER.check(accounts.normalize_username(data.username)[:120])
    account = accounts.authenticate(session, data.username, data.password)
    if account is None:
        log.info("login_refused", ip=client_ip(request))
        raise HTTPException(status_code=401, detail="Wrong username or password")
    sessions.set_cookie(response, account.id)
    record_audit_event(session, "login", "user", account.id, actor=account.id)
    return {**accounts.public_user(account), "mode": "standalone"}


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response):
    _standalone_only()
    # no account needed: a stale cookie may be cleared too
    if request.method not in ("GET", "HEAD", "OPTIONS") and not sessions.has_client_header(request):
        raise HTTPException(status_code=403, detail="Request refused: missing client header")
    # the injected response carries the cookie header; returning a new one
    # would drop it
    sessions.clear_cookie(response)
    return None


@router.post("/reset", status_code=202)
def request_reset(data: ResetIn, request: Request, session: DB):
    """Always 202: whether the address has an account is not revealed."""
    _standalone_only()
    RESET_LIMITER.check(client_ip(request))
    email = accounts.normalize_email(data.email)
    account = session.scalar(select(AppUser).where(AppUser.email == email)) if email else None
    if account is not None and not account.disabled:
        token = accounts.issue_token(session, account, "reset")
        mail.enqueue_account_mail(session, token.id)
        record_audit_event(session, "password_reset_requested", "user", account.id, actor=account.id)
    return {"ok": True}


@router.post("/set-password")
def set_password(data: SetPasswordIn, request: Request, response: Response, session: DB):
    """An invitation or reset link's landing: set the password, sign in."""
    _standalone_only()
    SET_PASSWORD_LIMITER.check(client_ip(request))
    account = accounts.consume_token(session, data.token, ("invite", "reset"))
    if account is None:
        raise HTTPException(status_code=404, detail="This link is not valid any more")
    try:
        accounts.set_password(session, account, data.password)
    except accounts.AccountError as exc:
        # the link is spent: say so clearly rather than letting them retry it
        raise HTTPException(status_code=422, detail=str(exc)) from None
    sessions.set_cookie(response, account.id)
    record_audit_event(session, "password_set", "user", account.id, actor=account.id)
    return {**accounts.public_user(account), "mode": "standalone"}
