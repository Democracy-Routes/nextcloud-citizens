# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Endpoints moved onto the read session must not have been writing.

`read_only_scope` never commits, so an endpoint converted to it that still
flushes a change loses that change SILENTLY — no error, no log, just data that
stops being saved. That is a worse failure than the lock starvation the
conversion fixes, so it gets its own guard.

The listener below turns any attempted write on a read-only session into a
loud failure, and every converted endpoint is exercised against it.
"""

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session


class ReadOnlySessionWrote(AssertionError):
    pass


@pytest.fixture
def forbid_writes_on_read_sessions():
    """Raise if any read-only session tries to flush a change."""

    def before_flush(session: Session, _flush_context, _instances):
        if not session.get_bind().get_execution_options().get("citizens_read_only"):
            return
        changed = list(session.new) + list(session.dirty) + list(session.deleted)
        if changed:
            raise ReadOnlySessionWrote(
                "a read-only endpoint tried to write "
                f"{[type(o).__name__ for o in changed]} — that write would be "
                "discarded without any error"
            )

    event.listen(Session, "before_flush", before_flush)
    yield
    event.remove(Session, "before_flush", before_flush)


def _assembly(client):
    assembly = client.post(
        "/api/v1/assemblies",
        json={
            "name": "TEST Read Only",
            "default_table_count": 2,
            "rounds": [{"title": "R1", "question": "Q?", "duration_minutes": 30}],
        },
    ).json()
    return assembly


CONVERTED_ENDPOINTS = [
    "/api/v1/assemblies",
    "/api/v1/assemblies/{assembly_id}",
    "/api/v1/assemblies/{assembly_id}/files",
    "/api/v1/assemblies/{assembly_id}/invites",
    "/api/v1/assemblies/{assembly_id}/invites/links",
    "/api/v1/assemblies/{assembly_id}/progress",
    "/api/v1/assemblies/{assembly_id}/report",
    "/api/v1/assemblies/{assembly_id}/participants",
    "/api/v1/rounds/{round_id}/monitor",
    "/api/v1/rounds/{round_id}/tables",
]


@pytest.mark.parametrize("path", CONVERTED_ENDPOINTS)
def test_a_read_endpoint_never_writes(client, forbid_writes_on_read_sessions, path):
    assembly = _assembly(client)
    url = path.format(assembly_id=assembly["id"], round_id=assembly["rounds"][0]["id"])
    response = client.get(url)
    # 404 is fine (a route that moved); a write attempt is not
    assert response.status_code in (200, 404), response.text


def test_the_guard_itself_catches_a_write(client, forbid_writes_on_read_sessions):
    """If this passes trivially the parametrized tests above prove nothing."""
    from citizens.db.models import Assembly
    from citizens.db.session import read_only_scope

    with pytest.raises(ReadOnlySessionWrote):
        with read_only_scope() as session:
            session.add(Assembly(name="written on a read session", language="en"))
            session.flush()
