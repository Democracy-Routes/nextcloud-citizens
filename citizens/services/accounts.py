# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Standalone accounts: organizers and administrators, their passwords and
the one-time links that set them.

Nothing here is reached in Nextcloud mode. An account's id is what
`Assembly.created_by` stores, exactly as a Nextcloud user id is today, so
every ownership check in the app works unchanged.
"""

import hashlib
import re
import secrets
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from citizens.config import get_settings
from citizens.db.models.accounts import AccountToken, AppUser
from citizens.db.models.base import utcnow
from citizens.logging_setup import get_logger
from citizens.security.invite_vault import decrypt_token, encrypt_token
from citizens.security.passwords import hash_password, password_problem, verify_password

log = get_logger(__name__)

ROLES = ("admin", "organizer")
TOKEN_KINDS = ("invite", "reset")
INVITE_TTL = timedelta(days=7)
RESET_TTL = timedelta(hours=2)
_USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{2,119}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AccountError(ValueError):
    """A refused account operation, with a message fit for the admin."""


def normalize_username(username: str) -> str:
    return (username or "").strip().lower()


def normalize_email(email: str | None) -> str | None:
    value = (email or "").strip().lower()
    return value or None


def validate_new_user(username: str, email: str | None, role: str) -> None:
    if not _USERNAME.match(username):
        raise AccountError(
            "The username must be 3 to 120 characters: letters, digits, dot, dash, underscore"
        )
    if email is not None and not _EMAIL.match(email):
        raise AccountError("The email address is not valid")
    if role not in ROLES:
        raise AccountError("The role must be admin or organizer")


def create_user(
    session: Session,
    *,
    username: str,
    display_name: str = "",
    email: str | None = None,
    role: str = "organizer",
    language: str = "en",
    password: str | None = None,
) -> AppUser:
    username = normalize_username(username)
    email = normalize_email(email)
    validate_new_user(username, email, role)
    if session.scalar(select(AppUser).where(AppUser.username == username)) is not None:
        raise AccountError("That username is already taken")
    if email and session.scalar(select(AppUser).where(AppUser.email == email)) is not None:
        raise AccountError("That email address is already used by another account")
    if password is not None:
        problem = password_problem(password)
        if problem:
            raise AccountError(problem)
    user = AppUser(
        username=username,
        display_name=(display_name or "").strip() or username,
        email=email,
        role=role,
        language=(language or "en")[:8],
        password_hash=hash_password(password) if password is not None else None,
    )
    session.add(user)
    session.flush()
    log.info("account_created", user_id=user.id, role=role)
    return user


def authenticate(session: Session, username: str, password: str) -> AppUser | None:
    """The account for a correct username and password, else None. A
    disabled account or one without a password yet never signs in. Constant
    work for an unknown username too: the hash is checked against a dummy."""
    user = session.scalar(select(AppUser).where(AppUser.username == normalize_username(username)))
    if user is None or user.disabled or not user.password_hash:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, user.password_hash):
        return None
    user.last_login_at = utcnow()
    return user


_DUMMY_HASH = hash_password("not-a-real-password-just-constant-time")


def set_password(session: Session, user: AppUser, password: str) -> None:
    problem = password_problem(password)
    if problem:
        raise AccountError(problem)
    user.password_hash = hash_password(password)
    session.flush()


def count_admins(session: Session) -> int:
    return int(
        session.scalar(
            select(func.count()).select_from(AppUser).where(
                AppUser.role == "admin", AppUser.disabled.is_(False)
            )
        )
        or 0
    )


def user_count(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(AppUser)) or 0)


# --- one-time links -------------------------------------------------------

def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def issue_token(session: Session, user: AppUser, kind: str) -> AccountToken:
    """A fresh invitation or reset link for `user`; any earlier unused one
    of the same kind stops working. The raw token exists only encrypted,
    for the mail job to read once (token_for_mail)."""
    if kind not in TOKEN_KINDS:
        raise AccountError(f"Unknown token kind {kind}")
    for old in session.scalars(
        select(AccountToken).where(
            AccountToken.user_id == user.id, AccountToken.kind == kind, AccountToken.used_at.is_(None)
        )
    ):
        old.used_at = utcnow()
        old.token_encrypted = None
    raw = secrets.token_urlsafe(32)
    token = AccountToken(
        user_id=user.id,
        kind=kind,
        token_hash=_hash(raw),
        token_encrypted=encrypt_token(raw),
        expires_at=utcnow() + (INVITE_TTL if kind == "invite" else RESET_TTL),
    )
    session.add(token)
    session.flush()
    return token


def token_for_mail(session: Session, token_id: str) -> tuple[AccountToken, AppUser, str] | None:
    """The token row, its account and the RAW token, for the mail that
    carries the link — and the encrypted copy is cleared, so the link can be
    read from the database only until the mail went out."""
    token = session.get(AccountToken, token_id)
    if token is None or token.used_at is not None or not token.token_encrypted:
        return None
    user = session.get(AppUser, token.user_id)
    if user is None or user.disabled:
        return None
    raw = decrypt_token(token.token_encrypted)
    token.token_encrypted = None
    session.flush()
    if raw is None:
        return None
    return token, user, raw


def consume_token(session: Session, raw: str, kinds: str | tuple[str, ...]) -> AppUser | None:
    """The account a valid, unused, unexpired link of one of `kinds` belongs
    to, marking the link used; None otherwise (and nothing is said about why)."""
    if isinstance(kinds, str):
        kinds = (kinds,)
    if not raw or len(raw) > 200:
        return None
    token = session.scalar(select(AccountToken).where(AccountToken.token_hash == _hash(raw)))
    if token is None or token.kind not in kinds or token.used_at is not None:
        return None
    if token.expires_at <= utcnow():
        return None
    user = session.get(AppUser, token.user_id)
    if user is None or user.disabled:
        return None
    token.used_at = utcnow()
    token.token_encrypted = None
    if user.email and user.email_verified_at is None:
        # the link reached that mailbox: the address is verified
        user.email_verified_at = utcnow()
    session.flush()
    return user


def bootstrap_admin(session: Session) -> AppUser | None:
    """The first administrator from CITIZENS_BOOTSTRAP_ADMIN_USER/PASSWORD,
    only while no account exists at all. Returns the account it made."""
    settings = get_settings()
    username = normalize_username(settings.citizens_bootstrap_admin_user)
    password = settings.citizens_bootstrap_admin_password
    if not username or not password:
        return None
    if user_count(session) > 0:
        return None
    user = create_user(session, username=username, role="admin", password=password)
    log.info("bootstrap_admin_created", user_id=user.id)
    return user


def public_user(user: AppUser) -> dict:
    """What the API says about an account. Never the hash, never a token."""
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "email_verified": user.email_verified_at is not None,
        "role": user.role,
        "language": user.language,
        "has_password": bool(user.password_hash),
        "oidc": bool(user.oidc_subject),
        "disabled": user.disabled,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


def expired_before(now: datetime) -> datetime:
    """Helper for the sweep: tokens older than this can be deleted."""
    return now - timedelta(days=30)
