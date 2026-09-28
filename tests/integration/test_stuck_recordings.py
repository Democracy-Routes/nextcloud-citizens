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

import hashlib
import re
from datetime import timedelta

import pytest
from sqlalchemy import select

from citizens.db.models import AppJob, Recording
from citizens.db.models.assembly import Table
from citizens.db.models.base import utcnow
from citizens.db.session import session_scope
from citizens.jobs import sweep
from citizens.jobs.handlers import handle_assemble_audio
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


def _phone(client, assembly):
    """A phone at table 1 that has scanned the QR code."""
    invites = client.post(f"/api/v1/assemblies/{assembly['id']}/invites/generate").json()
    token = re.search(r"#/join/(.+)$", invites[0]["url"]).group(1)
    joined = client.post(
        "/api/v1/public/join", json={"token": token}, headers={"X-Origin-IP": "203.0.113.9"}
    )
    assert joined.status_code == 200, joined.text
    return {"Authorization": f"Bearer {joined.json()['session_token']}"}


def _uploaded(client, assembly, sequences, complete=None):
    """A recording with these chunk sequences on the server, optionally with
    /complete declaring `complete` chunks in total."""
    headers = _phone(client, assembly)
    started = client.post(
        "/api/v1/public/recorder/start",
        json={"round_id": assembly["rounds"][0]["id"], "mime_type": "audio/webm"},
        headers=headers,
    )
    assert started.status_code == 201, started.text
    recording_id = started.json()["recording_id"]
    for sequence in sequences:
        blob = f"audio-{sequence}".encode()
        response = client.post(
            f"/api/v1/public/recorder/recordings/{recording_id}/chunks/{sequence}",
            content=blob,
            headers={
                **headers,
                "Content-Type": "application/octet-stream",
                "X-Chunk-SHA256": hashlib.sha256(blob).hexdigest(),
            },
        )
        assert response.status_code == 200, response.text
    if complete is not None:
        client.post(
            f"/api/v1/public/recorder/recordings/{recording_id}/complete",
            json={"total_chunks": complete},
            headers=headers,
        )
    return recording_id


def _age(recording_id, minutes):
    with session_scope() as session:
        session.get(Recording, recording_id).updated_at = utcnow() - timedelta(minutes=minutes)


def _assemble_jobs(recording_id):
    with session_scope() as session:
        return session.execute(
            select(AppJob).where(
                AppJob.type == "ASSEMBLE_AUDIO", AppJob.payload_json.contains(recording_id)
            )
        ).scalars().all()


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


# ------------------------ audio a dead phone left behind, nobody replaced it


def test_a_timed_out_recording_with_audio_is_assembled_by_the_sweep(client):
    """The 24 September 2026 rehearsal: a phone died mid-round, nobody rescanned
    the table, the twenty-minute sweep marked it UPLOAD_TIMED_OUT — and its
    five minutes of audio sat on disk for days, absent from the report, because
    the salvage sweep only looked at recordings a takeover had superseded."""
    assembly = _assembly(client, name="TEST Stranded")
    recording_id = _uploaded(client, assembly, sequences=(0, 1))
    _age(recording_id, sweep.STALLED_UPLOAD_MINUTES + 5)
    assert sweep.sweep_stalled_uploads() == 1
    assert _state(recording_id) == "UPLOAD_INCOMPLETE"
    _age(recording_id, sweep.SUPERSEDED_SALVAGE_MINUTES + 5)

    assert sweep.sweep_superseded_partials() == 1

    with session_scope() as session:
        recording = session.get(Recording, recording_id)
        assert recording.superseded_at is None, "nothing replaced this phone"
        assert recording.total_chunks == 2, "the contiguous prefix is the recording"
        # the runner may already have picked the job up (and rejected the fake
        # bytes): what matters is that it left UPLOAD_INCOMPLETE for assembly
        assert recording.state in ("ASSEMBLING", "AUDIO_READY", "AUDIO_INVALID")
    assert _assemble_jobs(recording_id), "no assembly was queued for the stranded audio"


def test_a_recording_that_never_uploaded_anything_is_left_alone(client):
    assembly = _assembly(client, name="TEST Stranded empty")
    recording_id = _uploaded(client, assembly, sequences=())
    _age(recording_id, sweep.STALLED_UPLOAD_MINUTES + 5)
    sweep.sweep_stalled_uploads()
    _age(recording_id, sweep.SUPERSEDED_SALVAGE_MINUTES + 5)

    assert sweep.sweep_superseded_partials() == 0
    assert _state(recording_id) == "UPLOAD_INCOMPLETE"


def test_a_recently_released_recording_waits_for_its_phone(client):
    """Half an hour of grace: a merely-offline phone still uploads its backlog."""
    assembly = _assembly(client, name="TEST Stranded recent")
    recording_id = _uploaded(client, assembly, sequences=(0, 1))
    _age(recording_id, sweep.STALLED_UPLOAD_MINUTES + 5)
    sweep.sweep_stalled_uploads()

    assert sweep.sweep_superseded_partials() == 0
    assert _state(recording_id) == "UPLOAD_INCOMPLETE"


def test_retry_on_a_timed_out_recording_salvages_the_prefix(client):
    """/complete declared 4 chunks, 3 never arrived, the sweep gave up. Retry
    used to re-declare the 4 and bounce straight back to WAITING_FOR_CHUNKS,
    where the sweep timed it out again twenty minutes later — a loop."""
    assembly = _assembly(client, name="TEST Retry salvage")
    recording_id = _uploaded(client, assembly, sequences=(0, 1, 3), complete=4)
    assert _state(recording_id) == "WAITING_FOR_CHUNKS"
    _age(recording_id, sweep.STALLED_UPLOAD_MINUTES + 5)
    sweep.sweep_stalled_uploads()
    assert _state(recording_id) == "UPLOAD_INCOMPLETE"

    response = client.post(f"/api/v1/recordings/{recording_id}/assemble")

    assert response.status_code == 202, response.text
    assert response.json()["salvaged_chunks"] == 2
    with session_scope() as session:
        recording = session.get(Recording, recording_id)
        assert recording.total_chunks == 2
        assert recording.state in ("ASSEMBLING", "AUDIO_READY", "AUDIO_INVALID")


def test_retry_is_refused_when_no_audio_ever_arrived(client):
    assembly = _assembly(client, name="TEST Retry empty")
    recording_id = _recording(assembly, "UPLOAD_INCOMPLETE")

    response = client.post(f"/api/v1/recordings/{recording_id}/assemble")

    assert response.status_code == 409
    assert "nothing to assemble" in response.json()["detail"]


def test_a_bounced_assembly_queues_no_transcription(client):
    """Chunks missing → back to WAITING_FOR_CHUNKS. The handler then queued
    TRANSCRIBE_FINAL anyway, which failed at once with "cannot transcribe": a
    red job on the operator's screen for a recording that was simply not ready."""
    assembly = _assembly(client, name="TEST Bounce")
    recording_id = _recording(assembly, "ASSEMBLING")
    with session_scope() as session:
        session.get(Recording, recording_id).total_chunks = 3

    with session_scope() as session:
        handle_assemble_audio(session, {"recording_id": recording_id})

    assert _state(recording_id) == "WAITING_FOR_CHUNKS"
    with session_scope() as session:
        queued = session.execute(
            select(AppJob).where(
                AppJob.type == "TRANSCRIBE_FINAL", AppJob.payload_json.contains(recording_id)
            )
        ).scalars().all()
    assert queued == [], "a transcription was queued for audio that does not exist yet"


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
