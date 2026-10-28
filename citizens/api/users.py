# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Account management for standalone mode (the Users card of Settings).
Registered only in standalone mode; under /admin so the AppAPI route table,
were it ever consulted, would still mark it ADMIN."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from citizens.api.admin import AdminUser
from citizens.db.models.accounts import AppUser
from citizens.db.session import get_db
from citizens.services import accounts, mail
from citizens.services.audit import record_audit_event

router = APIRouter(prefix="/admin/users")

DB = Annotated[Session, Depends(get_db, scope="function")]

Language = Literal["en", "it", "de", "fr", "es"]


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=120)
    display_name: str = Field(default="", max_length=200)
    email: str | None = Field(default=None, max_length=254)
    role: Literal["admin", "organizer"] = "organizer"
    language: Language = "en"


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=254)
    role: Literal["admin", "organizer"] | None = None
    language: Language | None = None
    disabled: bool | None = None


def _get(session: Session, user_id: str) -> AppUser:
    user = session.get(AppUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="No such account")
    return user


def _invite(session: Session, user: AppUser) -> bool:
    """Mail a set-password link if the account has an address. True when a
    mail was queued."""
    if not user.email:
        return False
    kind = "invite" if not user.password_hash else "reset"
    token = accounts.issue_token(session, user, kind)
    mail.enqueue_account_mail(session, token.id)
    return True


@router.get("")
def list_users(user: AdminUser, session: DB):
    rows = session.scalars(select(AppUser).order_by(AppUser.username)).all()
    return {"users": [accounts.public_user(row) for row in rows], "mail": mail.configured()}


@router.post("", status_code=201)
def create_user(data: UserCreate, user: AdminUser, session: DB):
    try:
        created = accounts.create_user(
            session,
            username=data.username,
            display_name=data.display_name,
            email=data.email,
            role=data.role,
            language=data.language,
        )
    except accounts.AccountError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    invited = _invite(session, created)
    record_audit_event(
        session, "account_created", "user", created.id, actor=user, data={"role": created.role}
    )
    return {**accounts.public_user(created), "invited": invited}


@router.put("/{user_id}")
def update_user(user_id: str, data: UserUpdate, user: AdminUser, session: DB):
    account = _get(session, user_id)
    losing_admin = account.role == "admin" and not account.disabled and (
        data.role == "organizer" or data.disabled is True
    )
    if losing_admin and accounts.count_admins(session) <= 1:
        raise HTTPException(status_code=409, detail="The last administrator cannot be demoted or disabled")
    if data.disabled is True and account.id == user:
        raise HTTPException(status_code=409, detail="You cannot disable your own account")
    if data.display_name is not None and data.display_name.strip():
        account.display_name = data.display_name.strip()
    if data.email is not None:
        email = accounts.normalize_email(data.email)
        if email != account.email:
            if email:
                try:
                    accounts.validate_new_user(account.username, email, account.role)
                except accounts.AccountError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from None
                other = session.scalar(select(AppUser).where(AppUser.email == email))
                if other is not None and other.id != account.id:
                    raise HTTPException(status_code=422, detail="That email address is already used")
            account.email = email
            account.email_verified_at = None
    if data.role is not None:
        account.role = data.role
    if data.language is not None:
        account.language = data.language
    if data.disabled is not None:
        account.disabled = data.disabled
    record_audit_event(session, "account_updated", "user", account.id, actor=user)
    return accounts.public_user(account)


@router.post("/{user_id}/invite", status_code=202)
def resend_invite(user_id: str, user: AdminUser, session: DB):
    account = _get(session, user_id)
    if account.disabled:
        raise HTTPException(status_code=409, detail="The account is disabled")
    if not _invite(session, account):
        raise HTTPException(status_code=409, detail="The account has no email address")
    record_audit_event(session, "account_invited", "user", account.id, actor=user)
    return {"ok": True, "mail": mail.configured()}


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: str, user: AdminUser, session: DB):
    account = _get(session, user_id)
    if account.id == user:
        raise HTTPException(status_code=409, detail="You cannot delete your own account")
    if account.role == "admin" and not account.disabled and accounts.count_admins(session) <= 1:
        raise HTTPException(status_code=409, detail="The last administrator cannot be deleted")
    # the person's assemblies stay, owned by an id nobody can sign in as:
    # an administrator reassigns them before deleting, or keeps the account
    # disabled instead
    session.delete(account)
    record_audit_event(session, "account_deleted", "user", user_id, actor=user)
    return Response(status_code=204)
