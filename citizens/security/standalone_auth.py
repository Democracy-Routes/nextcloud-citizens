# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Standalone mode's request authentication: the session cookie to an
account, with the account looked up on every request so a disabled account
stops at once, and the client header required on every unsafe request
(security/sessions.py explains why that defeats cross-site forgery).

Only reached in standalone mode (security/identity.py dispatches)."""

from dataclasses import dataclass

from fastapi import HTTPException, Request
from sqlalchemy import select

from citizens.db.models.accounts import AppUser
from citizens.db.session import read_only_scope
from citizens.logging_setup import get_logger
from citizens.security import sessions

log = get_logger(__name__)

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class Account:
    """The three facts a request needs — read inside a short session and
    carried out of it as plain values, never as a detached ORM row."""

    id: str
    role: str
    disabled: bool


def _load(user_id: str) -> Account | None:
    with read_only_scope() as session:
        row = session.execute(
            select(AppUser.id, AppUser.role, AppUser.disabled).where(AppUser.id == user_id)
        ).first()
    return Account(*row) if row else None


def current_account(request: Request) -> Account:
    """The signed-in account, or 401. 403 for an unsafe request without the
    client header, which is how a cross-site form would arrive."""
    user_id = sessions.user_id_from(request)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    if request.method not in SAFE_METHODS and not sessions.has_client_header(request):
        log.warning("client_header_missing", path=request.url.path)
        raise HTTPException(status_code=403, detail="Request refused: missing client header")
    account = _load(user_id)
    if account is None or account.disabled:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    return account


def current_user_id(request: Request) -> str:
    return current_account(request).id


def require_admin(user_id: str) -> str:
    """The admin guard of standalone mode: the account's role."""
    account = _load(user_id)
    if account is None or account.disabled or account.role != "admin":
        log.warning("admin_route_refused", user=user_id)
        raise HTTPException(status_code=403, detail="Administrator rights are required")
    return user_id
