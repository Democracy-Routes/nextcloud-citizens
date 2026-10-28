# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Operator commands for a standalone instance, run inside the container:

    python -m citizens.standalone create-admin --username anna [--email a@b.c]
    python -m citizens.standalone set-password --username anna
    python -m citizens.standalone list-users

The password is asked for on the terminal, or read from the CITIZENS_PASSWORD
environment variable for scripted use — never from an argument, which would
land in the shell history and the process list. The app may be running at
the same time: every command is one short write transaction.
"""

import argparse
import getpass
import os
import sys

from sqlalchemy import select

from citizens.config import get_settings
from citizens.db.migrate import run_migrations
from citizens.db.models.accounts import AppUser
from citizens.db.session import configure_database, session_scope, sqlite_url
from citizens.logging_setup import setup_logging
from citizens.services import accounts
from citizens.storage.paths import db_path, ensure_storage_layout


def _open_database() -> None:
    settings = get_settings()
    ensure_storage_layout(settings.app_persistent_storage)
    setup_logging(settings)
    url = sqlite_url(db_path(settings.app_persistent_storage))
    configure_database(url)
    run_migrations(url)


def _password() -> str:
    env = os.environ.get("CITIZENS_PASSWORD")
    if env:
        return env
    first = getpass.getpass("Password: ")
    second = getpass.getpass("Again: ")
    if first != second:
        sys.exit("The passwords differ")
    return first


def create_admin(args: argparse.Namespace) -> int:
    password = _password()
    with session_scope() as session:
        try:
            user = accounts.create_user(
                session,
                username=args.username,
                display_name=args.display_name or "",
                email=args.email,
                role="admin",
                language=args.language,
                password=password,
            )
        except accounts.AccountError as exc:
            sys.exit(str(exc))
        print(f"Administrator {user.username} created ({user.id})")
    return 0


def set_password(args: argparse.Namespace) -> int:
    password = _password()
    with session_scope() as session:
        user = session.scalar(
            select(AppUser).where(AppUser.username == accounts.normalize_username(args.username))
        )
        if user is None:
            sys.exit("No such account")
        try:
            accounts.set_password(session, user, password)
        except accounts.AccountError as exc:
            sys.exit(str(exc))
        print(f"Password set for {user.username}")
    return 0


def list_users(_args: argparse.Namespace) -> int:
    with session_scope() as session:
        rows = session.scalars(select(AppUser).order_by(AppUser.username)).all()
        for user in rows:
            state = "disabled" if user.disabled else "active"
            password = "password" if user.password_hash else "no password"
            print(f"{user.username:30} {user.role:10} {state:9} {password:12} {user.email or ''}")
        if not rows:
            print("No accounts yet")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m citizens.standalone")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-admin", help="create an administrator account")
    create.add_argument("--username", required=True)
    create.add_argument("--email")
    create.add_argument("--display-name")
    create.add_argument("--language", default="en", choices=["en", "it", "de", "fr", "es"])
    create.set_defaults(run=create_admin)

    password = sub.add_parser("set-password", help="set an account's password")
    password.add_argument("--username", required=True)
    password.set_defaults(run=set_password)

    listing = sub.add_parser("list-users", help="list the accounts")
    listing.set_defaults(run=list_users)

    args = parser.parse_args(argv)
    if not get_settings().is_standalone():
        sys.exit("These commands are for standalone mode (CITIZENS_MODE=standalone)")
    _open_database()
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
