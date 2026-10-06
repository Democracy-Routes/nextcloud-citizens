# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A read-only session must see what was committed before it opened.

The read engine never emitted BEGIN (so a poll would not take the writer
slot), and pysqlite runs with isolation_level=None. A result left partly
consumed on a pooled connection then kept an SQLite statement open — and an
open statement pins the WAL snapshot: the next request on that connection
read the database as it was minutes ago. On the dev instance a row created
100 ms earlier came back 404, and a hand raised by a table was missing from
the next monitor read. Every read session now runs in a deferred
transaction that is rolled back when the session closes, which resets every
statement and releases the snapshot."""

from sqlalchemy import select

from citizens.db.models import Assembly
from citizens.db.session import read_only_scope, session_scope


def _create(client, name):
    return client.post(
        "/api/v1/assemblies",
        json={"name": name, "default_table_count": 1, "rounds": [{"title": "R", "question": "Q"}]},
    ).json()["id"]


def test_a_read_session_sees_rows_committed_before_it_even_after_a_partial_read(client):
    _create(client, "TEST snapshot seed 1")
    _create(client, "TEST snapshot seed 2")
    # a result object that outlives its session, as one does in practice until
    # the garbage collector gets to it (a reference cycle, a closure): the
    # statement behind it stays open on the pooled connection
    lingering = []
    for attempt in range(12):  # enough to land on every pooled connection
        with read_only_scope() as session:
            rows = session.execute(select(Assembly).order_by(Assembly.created_at)).scalars()
            next(iter(rows))  # read one row and walk away
            lingering.append(rows)
        with session_scope() as session:
            session.add(Assembly(name=f"TEST snapshot {attempt}", created_by="t"))
        with read_only_scope() as session:
            found = session.execute(
                select(Assembly.id).where(Assembly.name == f"TEST snapshot {attempt}")
            ).scalar_one_or_none()
            assert found is not None, f"attempt {attempt}: a committed row is invisible to a fresh read"
