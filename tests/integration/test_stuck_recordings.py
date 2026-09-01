# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A recording must never reach a state nothing can move it out of.

ASSEMBLING was exactly that. StorageFullError is retryable, so it deliberately
leaves the state alone; when the five attempts ran out the job went FAILED and
the recording stayed ASSEMBLING forever. From there it could not be
re-recorded (not in RERECORDABLE_STATES), abandoned, re-transcribed, or swept —
and because ASSEMBLING counts as healthy-pending, it also stopped the round's
cross-table analysis for good. One full disk wedged the whole round with no
organizer action able to resolve it.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from citizens.db.models import AppJob, Recording
from citizens.db.models.assembly import Table
from citizens.db.models.base import utcnow
from citizens.db.session import session_scope
from citizens.jobs import sweep
from citizens.services.jobs import enqueue_job


def _assembly(client, name="TEST Stuck"):
    assembly = client.post(
        "/api/v1/assemblies",
        json={
            "name": name,
            "default_table_count": 1,
            "rounds": [{"title": "R1", "question": "Q?", "duration_minutes": 30}],
        },
    ).json()
    client.post(f"/api/v1/rounds/{assembly['rounds'][0]['id']}/start")
    return assembly


def _recording(assembly, state="ASSEMBLING", age_minutes=0):
    """A recording in the given state, optionally aged past a sweep cutoff."""
    round_id = assembly["rounds"][0]["id"]
    with session_scope() as session:
        table = session.execute(
            select(Table).where(Table.round_id == round_id, Table.number == 1)
        ).scalar_one()
        recording = Recording(
            assembly_id=assembly["id"],
            round_id=round_id,
            table_id=table.id,
            table_number=1,
            state=state,
            mime_type="audio/webm",
            error_code="STORAGE_FULL" if state == "ASSEMBLING" else "",
        )
        session.add(recording)
        session.flush()
        recording_id = recording.id
        if age_minutes:
            recording.updated_at = utcnow() - timedelta(minutes=age_minutes)
    return recording_id


def _state(recording_id):
    with session_scope() as session:
        return session.get(Recording, recording_id).state


# --------------------------------------------------------------- the sweep


def test_a_wedged_assembling_recording_is_released(client):
    assembly = _assembly(client)
    recording_id = _recording(assembly, "ASSEMBLING", age_minutes=sweep.STALLED_ASSEMBLY_MINUTES + 5)

    assert sweep.sweep_stalled_uploads() == 1
    assert _state(recording_id) == "UPLOAD_INCOMPLETE", (
        "a recording whose assembly failed for good is still stuck in "
        "ASSEMBLING, where nothing can reach it and the round's analysis "
        "never runs"
    )


def test_a_recording_still_being_assembled_is_left_alone(client):
    """The guard: a long remux must not be abandoned out from under its job."""
    assembly = _assembly(client)
    recording_id = _recording(assembly, "ASSEMBLING", age_minutes=sweep.STALLED_ASSEMBLY_MINUTES + 5)
    with session_scope() as session:
        enqueue_job(session, "ASSEMBLE_AUDIO", {"recording_id": recording_id})

    assert sweep.sweep_stalled_uploads() == 0
    assert _state(recording_id) == "ASSEMBLING"


def test_a_recently_assembling_recording_is_left_alone(client):
    assembly = _assembly(client)
    recording_id = _recording(assembly, "ASSEMBLING", age_minutes=1)

    assert sweep.sweep_stalled_uploads() == 0
    assert _state(recording_id) == "ASSEMBLING"


def test_releasing_it_unblocks_the_round_analysis(client):
    """The reason this matters: ASSEMBLING counts as healthy-pending, so one
    wedged table stops the whole round being clustered."""
    assembly = _assembly(client)
    _recording(assembly, "ASSEMBLING", age_minutes=sweep.STALLED_ASSEMBLY_MINUTES + 5)

    sweep.sweep_stalled_uploads()

    with session_scope() as session:
        queued = session.execute(
            select(AppJob).where(AppJob.type == "ANALYZE_ROUND")
        ).scalars().all()
    assert queued, "the round's cross-table analysis was never enqueued"


# ------------------------------------------------------- organizer actions


def test_the_organizer_can_abandon_a_wedged_assembly(client):
    assembly = _assembly(client)
    recording_id = _recording(assembly, "ASSEMBLING")

    response = client.post(f"/api/v1/recordings/{recording_id}/abandon-upload")

    assert response.status_code == 200, response.text
    assert _state(recording_id) == "UPLOAD_INCOMPLETE"


def test_abandoning_is_refused_while_assembly_is_actually_running(client):
    assembly = _assembly(client)
    recording_id = _recording(assembly, "ASSEMBLING")
    with session_scope() as session:
        enqueue_job(session, "ASSEMBLE_AUDIO", {"recording_id": recording_id})

    response = client.post(f"/api/v1/recordings/{recording_id}/abandon-upload")

    assert response.status_code == 409


def test_the_organizer_can_retry_assembly(client):
    """Once the disk has space again, this is the way back."""
    assembly = _assembly(client)
    recording_id = _recording(assembly, "ASSEMBLING")

    response = client.post(f"/api/v1/recordings/{recording_id}/assemble")

    assert response.status_code == 202, response.text
    with session_scope() as session:
        jobs = session.execute(
            select(AppJob).where(AppJob.type == "ASSEMBLE_AUDIO")
        ).scalars().all()
    assert len(jobs) == 1, "no assembly job was enqueued"
    assert recording_id in jobs[0].payload_json


def test_retrying_twice_does_not_stack_two_jobs(client):
    assembly = _assembly(client)
    recording_id = _recording(assembly, "ASSEMBLING")

    assert client.post(f"/api/v1/recordings/{recording_id}/assemble").status_code == 202
    assert client.post(f"/api/v1/recordings/{recording_id}/assemble").status_code == 409


def test_retry_is_refused_for_a_recording_with_nothing_to_assemble(client):
    assembly = _assembly(client)
    recording_id = _recording(assembly, "TRANSCRIBED")

    assert client.post(f"/api/v1/recordings/{recording_id}/assemble").status_code == 409


# -------------------------------------------------- deleting audio mid-job


def test_deleting_audio_is_refused_while_the_recording_is_being_assembled(client):
    """assemble_recording releases the write lock before its ffmpeg work, so
    this delete could unlink the very chunks the job was about to read — which
    failed five times and then wedged the recording in ASSEMBLING."""
    assembly = _assembly(client)
    recording_id = _recording(assembly, "ASSEMBLING")
    with session_scope() as session:
        enqueue_job(session, "ASSEMBLE_AUDIO", {"recording_id": recording_id})

    response = client.delete(f"/api/v1/recordings/{recording_id}/audio")

    assert response.status_code == 409, (
        "the audio was deleted out from under a running assembly job"
    )


def test_deleting_audio_is_allowed_once_assembly_has_finished(client):
    assembly = _assembly(client)
    recording_id = _recording(assembly, "AUDIO_READY")

    assert client.delete(f"/api/v1/recordings/{recording_id}/audio").status_code == 200


@pytest.mark.parametrize("target", ["ASSEMBLING"])
def test_assembling_can_escape_to_upload_incomplete(target):
    """The transition itself — declared, and reachable."""
    from citizens.services.recording_states import ALLOWED_TRANSITIONS

    assert "UPLOAD_INCOMPLETE" in ALLOWED_TRANSITIONS[target]
