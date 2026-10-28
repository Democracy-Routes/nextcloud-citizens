# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Standalone mode's own tables (0.9): settings, accounts, account tokens.

In Nextcloud mode these tables exist (the migration is unconditional) and
stay empty: settings live in Nextcloud's app config and identity comes from
the AppAPI proxy. Standalone mode has neither, so Settings are rows here and
an organizer is an `AppUser` who signed in with a password or, later,
through OpenID Connect.
"""

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from citizens.db.models.base import Base, TZDateTime, new_uuid, utcnow


class AppConfig(Base):
    """One Settings value. `sensitive` rows (API keys) hold a Fernet token
    keyed on APP_SECRET, so a copy of the database alone reveals no key —
    the same protection Nextcloud's app config gives them."""

    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)


class AppUser(Base):
    """An organizer or administrator of a standalone instance. `id` is what
    `Assembly.created_by` stores, so an account can be renamed."""

    __tablename__ = "app_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str | None] = mapped_column(String(254), unique=True, nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    #: None until the person set one through an invitation link
    password_hash: Mapped[str | None] = mapped_column(String(300), nullable=True)
    #: "admin" | "organizer"
    role: Mapped[str] = mapped_column(String(16), default="organizer")
    #: the organizer UI's language for this person (one of SUPPORTED_LOCALES)
    language: Mapped[str] = mapped_column(String(8), default="en")
    oidc_issuer: Mapped[str | None] = mapped_column(String(300), nullable=True)
    oidc_subject: Mapped[str | None] = mapped_column(String(300), nullable=True)
    notify_opt_out: Mapped[bool] = mapped_column(Boolean, default=False)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow, onupdate=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)


class AccountToken(Base):
    """A one-time link: invitation (set the first password), password reset.

    Looked up by the hash of the token the link carries; the encrypted copy
    exists only until the mail that carries it has been sent, so the raw
    token is never written to a job payload or a log.
    """

    __tablename__ = "account_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("app_users.id", ondelete="CASCADE"), index=True
    )
    #: "invite" | "reset"
    kind: Mapped[str] = mapped_column(String(16))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime())
    used_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
