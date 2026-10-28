# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Standalone mode's Settings store: the `app_config` table, behind the same
`ConfigStore` protocol Nextcloud's app config implements in Nextcloud mode
(services/provider_config.py).

Every call opens its own short connection and closes it: a store read inside
somebody else's write transaction must not nest on that transaction, and a
store write must never be attempted while the caller holds SQLite's single
writer slot (it would wait on itself). The callers are the same ones as in
Nextcloud mode — the snapshot refresh at startup and each sweep, and the
Settings save — none of which runs inside a request's transaction.

Sensitive values (API keys) are stored as Fernet tokens keyed on APP_SECRET,
the key the invite vault already derives: a copy of the database alone
reveals no provider key, as with Nextcloud's sensitive app config.
"""

from datetime import UTC, datetime

from sqlalchemy import text

from citizens.db.session import get_engine
from citizens.logging_setup import get_logger
from citizens.security.invite_vault import decrypt_token, encrypt_token

log = get_logger(__name__)

_SELECT_ONE = text("SELECT value, sensitive FROM app_config WHERE key = :key")
_UPSERT = text(
    "INSERT INTO app_config (key, value, sensitive, updated_at) "
    "VALUES (:key, :value, :sensitive, :updated_at) "
    "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
    "sensitive = excluded.sensitive, updated_at = excluded.updated_at"
)
_DELETE = text("DELETE FROM app_config WHERE key = :key")


class SqliteConfigStore:
    """The ConfigStore of a standalone instance. One instance per process is
    enough (it holds no state); provider_config.default_store() keeps it."""

    _undecryptable_warned = False

    def _decode(self, key: str, value: str, sensitive: bool) -> str | None:
        if not sensitive:
            return value
        if value == "":
            return ""
        plain = decrypt_token(value)
        if plain is None and not SqliteConfigStore._undecryptable_warned:
            # APP_SECRET changed since the key was saved: the admin must
            # enter it again. Said once, not on every request.
            SqliteConfigStore._undecryptable_warned = True
            log.warning("config_value_undecryptable", key=key)
        return plain

    def get_value(self, key: str) -> str | None:
        engine = get_engine().execution_options(citizens_read_only=True)
        with engine.connect() as conn:
            row = conn.execute(_SELECT_ONE, {"key": key}).first()
        if row is None:
            return None
        return self._decode(key, row[0], bool(row[1]))

    def get_values(self, keys: list[str]) -> dict[str, str]:
        """Every stored key among `keys`, in one query (bulk_view)."""
        if not keys:
            return {}
        placeholders = ", ".join(f":k{i}" for i in range(len(keys)))
        statement = text(
            f"SELECT key, value, sensitive FROM app_config WHERE key IN ({placeholders})"
        )
        params = {f"k{i}": key for i, key in enumerate(keys)}
        engine = get_engine().execution_options(citizens_read_only=True)
        with engine.connect() as conn:
            rows = conn.execute(statement, params).all()
        values: dict[str, str] = {}
        for key, value, sensitive in rows:
            decoded = self._decode(key, value, bool(sensitive))
            if decoded is not None:
                values[key] = decoded
        return values

    def set_value(self, key: str, value: str, sensitive: bool = False) -> None:
        stored = encrypt_token(value) if sensitive and value != "" else value
        with get_engine().connect() as conn:
            with conn.begin():
                conn.execute(
                    _UPSERT,
                    {
                        "key": key,
                        "value": stored,
                        "sensitive": 1 if sensitive else 0,
                        "updated_at": datetime.now(UTC),
                    },
                )

    def delete_value(self, key: str) -> None:
        with get_engine().connect() as conn:
            with conn.begin():
                conn.execute(_DELETE, {"key": key})
