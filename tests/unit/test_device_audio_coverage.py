# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A replaced or expired recorder can still hold somebody's conversation."""

import json
from datetime import timedelta

import pytest

from citizens.db.models import Assembly, RecorderInvite, RecorderSession
from citizens.db.models.base import utcnow
from citizens.db.session import session_scope
from citizens.services.files import device_audio_coverage


@pytest.mark.parametrize("mode", ["plenary", "orchestrated"])
def test_every_session_counts_even_after_replacement_expiry_or_revocation(database, mode):
    with session_scope() as session:
        assembly = Assembly(name="Coverage", created_by="tester", recording_mode=mode)
        other = Assembly(name="Other assembly", created_by="tester")
        session.add_all([assembly, other])
        session.flush()
        for owner, counts in ((assembly, [3, 2, None, 0]), (other, [8])):
            invite = RecorderInvite(assembly_id=owner.id, table_number=1, token_hash=owner.id)
            session.add(invite)
            session.flush()
            for index, remaining in enumerate(counts):
                session.add(RecorderSession(
                    assembly_id=owner.id, invite_id=invite.id, table_number=1,
                    token_hash=f"{owner.id}-{index}",
                    created_at=utcnow() + timedelta(seconds=index),
                    expires_at=utcnow() + timedelta(days=-1 if index == 1 else 1),
                    revoked_at=utcnow() if index == 0 else None,
                    last_status_json=json.dumps({"local_recordings": remaining}),
                ))
        session.flush()
        assert device_audio_coverage(session, assembly) == {
            "devices": 4, "cleared": 1, "still_holding": 2, "unknown": 1,
        }


@pytest.mark.parametrize("status", ["{}", "broken", "[]", "null", '{"local_recordings": true}',
                                    '{"local_recordings": -1}', '{"local_recordings": "0"}'])
def test_missing_or_invalid_counts_are_unknown(database, status):
    with session_scope() as session:
        assembly = Assembly(name="Unknown", created_by="tester")
        session.add(assembly)
        session.flush()
        invite = RecorderInvite(assembly_id=assembly.id, table_number=1, token_hash="invite")
        session.add(invite)
        session.flush()
        session.add(RecorderSession(
            assembly_id=assembly.id, invite_id=invite.id, table_number=1,
            token_hash="session", expires_at=utcnow() + timedelta(days=1),
            last_status_json=status,
        ))
        session.flush()
        assert device_audio_coverage(session, assembly) == {
            "devices": 1, "cleared": 0, "still_holding": 0, "unknown": 1,
        }
