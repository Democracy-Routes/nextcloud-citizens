# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reopening withdraws the close's purge request — keying on WHO asked.

The phone-facing flag is set-and-forget: a phone joining days later must still
honour a request it missed. But reopening an assembly for another day of
recordings must withdraw a request the CLOSE made, or every phone deletes each
fresh recording the moment the server confirms it. That withdrawal used to key
off the auto_purge_device_audio toggle's CURRENT value — flipping the toggle
off between close and reopen left the automatic request standing, deleting
new local recordings the organizer had just said to keep.
"""

import pytest
from sqlalchemy import select

from citizens.db.models import Assembly
from citizens.db.models.base import utcnow
from citizens.db.session import session_scope
from citizens.services import lifecycle


@pytest.fixture
def assembly_row(database):
    with session_scope() as session:
        assembly = Assembly(name="Purge origins", created_by="tester")
        session.add(assembly)
        session.flush()
        return assembly.id


def _get(assembly_id):
    with session_scope() as session:
        return _get_in(session, assembly_id)


def _get_in(session, assembly_id):
    return session.execute(
        select(Assembly).where(Assembly.id == assembly_id)
    ).scalar_one()


def test_reopen_withdraws_the_automatic_request(assembly_row):
    with session_scope() as session:
        assembly = _get_in(session, assembly_row)
        lifecycle.close_assembly(session, assembly)
        assert assembly.device_audio_purge_requested_at is not None
        assert assembly.purge_requested_automatically is True
    with session_scope() as session:
        lifecycle.reopen_assembly(session, _get_in(session, assembly_row))
    assembly = _get(assembly_row)
    assert assembly.device_audio_purge_requested_at is None
    assert assembly.purge_requested_automatically is None


def test_toggling_auto_purge_off_between_close_and_reopen_still_withdraws(assembly_row):
    """The regression: the withdrawal read the toggle's CURRENT value."""
    with session_scope() as session:
        lifecycle.close_assembly(session, _get_in(session, assembly_row))
    with session_scope() as session:
        assembly = _get_in(session, assembly_row)
        assembly.auto_purge_device_audio = False  # the organizer changed their mind
        lifecycle.reopen_assembly(session, assembly)
    assert _get(assembly_row).device_audio_purge_requested_at is None


def test_reopen_keeps_a_manual_request(assembly_row):
    """An organizer pressing the button by hand asked for something and meant
    it; a later reopen must not unsay it."""
    with session_scope() as session:
        assembly = _get_in(session, assembly_row)
        assembly.auto_purge_device_audio = False  # so close() stays out of it
        lifecycle.close_assembly(session, assembly)
        assert assembly.device_audio_purge_requested_at is None
        # the manual button (api/files.py request_device_audio_purge)
        assembly.device_audio_purge_requested_at = utcnow()
        assembly.purge_requested_automatically = False
        requested = assembly.device_audio_purge_requested_at
    with session_scope() as session:
        lifecycle.reopen_assembly(session, _get_in(session, assembly_row))
    assembly = _get(assembly_row)
    assert assembly.device_audio_purge_requested_at == requested
    assert assembly.purge_requested_automatically is False
