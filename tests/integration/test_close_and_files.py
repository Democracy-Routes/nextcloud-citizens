# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Closing a session (interim → final, frozen snapshot, recording lock) and the
Files tab (inventory, audio deletion, portable export)."""

import hashlib
import io
import json
import re
import subprocess
import time
import zipfile


def _audio(tmp_path) -> bytes:
    path = tmp_path / "close.webm"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=2",
         "-c:a", "libopus", "-b:a", "32k", str(path)],
        check=True,
        timeout=120,
    )
    return path.read_bytes()


def _assembly(client, name, tables=2, mode="independent"):
    return client.post(
        "/api/v1/assemblies",
        json={"name": name, "recording_mode": mode, "default_table_count": tables,
              "rounds": [{"title": "R1", "question": "Q1", "duration_minutes": 10}]},
    ).json()


def _join(client, assembly, table_index, ip):
    token = re.search(r"#/join/(.+)$", assembly["invites"][table_index]["url"]).group(1)
    joined = client.post(
        "/api/v1/public/join", json={"token": token}, headers={"X-Forwarded-For": ip}
    ).json()
    return {"Authorization": f"Bearer {joined['session_token']}"}, joined


def _record(client, headers, round_id, audio):
    recording_id = client.post(
        "/api/v1/public/recorder/start",
        json={"round_id": round_id, "mime_type": "audio/webm"},
        headers=headers,
    ).json()["recording_id"]
    client.post(
        f"/api/v1/public/recorder/recordings/{recording_id}/chunks/0",
        content=audio,
        headers={**headers, "Content-Type": "application/octet-stream",
                 "X-Chunk-SHA256": hashlib.sha256(audio).hexdigest()},
    )
    client.post(
        f"/api/v1/public/recorder/recordings/{recording_id}/complete",
        json={"total_chunks": 1},
        headers=headers,
    )
    _wait_assembled(client, headers, recording_id)
    return recording_id


def _wait_assembled(client, headers, recording_id, timeout=30.0):
    """The audio file only exists once the background job assembled it."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = client.get(
            f"/api/v1/public/recorder/recordings/{recording_id}", headers=headers
        ).json()["state"]
        if state not in ("WAITING_FOR_CHUNKS", "FINALIZING", "ASSEMBLING", "RECORDING"):
            return state
        time.sleep(0.4)
    raise AssertionError(f"recording {recording_id} never assembled")


def test_close_locks_recording_and_finalizes(client, tmp_path):
    assembly = _assembly(client, "TEST Close Lock")
    headers, joined = _join(client, assembly, 0, "10.8.8.1")
    round_id = joined["rounds"][0]["id"]
    _record(client, headers, round_id, _audio(tmp_path))

    # only 1 of 2 tables: interim, and the assembly is under way (not Draft)
    report = client.get(f"/api/v1/assemblies/{assembly['id']}/report").json()
    assert report["is_final"] is False
    assert report["progress"]["tables_complete"] == 1
    assert report["progress"]["tables_expected"] == 2
    assert report["progress"]["tables_missing"] == [2]
    assert client.get(f"/api/v1/assemblies/{assembly['id']}").json()["status"] == "ACTIVE"

    closed = client.post(f"/api/v1/assemblies/{assembly['id']}/close")
    assert closed.status_code == 200 and closed.json()["closed_at"]
    detail = client.get(f"/api/v1/assemblies/{assembly['id']}").json()
    assert detail["status"] == "COMPLETE" and detail["closed_at"]

    report = client.get(f"/api/v1/assemblies/{assembly['id']}/report").json()
    assert report["is_final"] is True

    # a late table can no longer record
    late_headers, late_joined = _join(client, assembly, 1, "10.8.8.2")
    blocked = client.post(
        "/api/v1/public/recorder/start",
        json={"round_id": late_joined["rounds"][0]["id"], "mime_type": "audio/webm"},
        headers=late_headers,
    )
    assert blocked.status_code == 409
    assert "closed" in blocked.json()["detail"].lower()

    # reopening lets them record again
    assert client.delete(f"/api/v1/assemblies/{assembly['id']}/close").status_code == 204
    allowed = client.post(
        "/api/v1/public/recorder/start",
        json={"round_id": late_joined["rounds"][0]["id"], "mime_type": "audio/webm"},
        headers=late_headers,
    )
    assert allowed.status_code == 201


def test_phone_report_frozen_across_reopen(client, tmp_path, monkeypatch):
    from citizens.services import provider_config

    monkeypatch.setattr(provider_config, "analysis_enabled_cached", lambda: False)
    assembly = _assembly(client, "TEST Freeze", tables=1)
    headers, joined = _join(client, assembly, 0, "10.8.8.3")
    _record(client, headers, joined["rounds"][0]["id"], _audio(tmp_path))
    client.post(f"/api/v1/assemblies/{assembly['id']}/close")

    frozen = client.get("/api/v1/public/recorder/report", headers=headers).json()
    assert frozen["is_final"] is True

    # the organizer reopens; participants keep the version they were reading
    client.delete(f"/api/v1/assemblies/{assembly['id']}/close")
    after = client.get("/api/v1/public/recorder/report", headers=headers)
    assert after.status_code == 200
    assert after.json()["is_final"] is True
    assert after.json()["closed_at"] == frozen["closed_at"]


def test_files_listing_download_and_delete(client, tmp_path):
    assembly = _assembly(client, "TEST Files", tables=1)
    headers, joined = _join(client, assembly, 0, "10.8.8.4")
    recording_id = _record(client, headers, joined["rounds"][0]["id"], _audio(tmp_path))

    listing = client.get(f"/api/v1/assemblies/{assembly['id']}/files").json()
    assert listing["totals"]["recordings"] == 1
    assert listing["totals"]["audio_bytes"] > 0
    entry = listing["rounds"][0]["tables"][0]
    assert entry["audio_available"] is True and entry["audio_deleted_at"] is None

    audio = client.get(f"/api/v1/recordings/{recording_id}/audio")
    assert audio.status_code == 200
    assert len(audio.content) > 0
    assert "attachment" in audio.headers["content-disposition"]

    deleted = client.delete(f"/api/v1/recordings/{recording_id}/audio")
    assert deleted.status_code == 200 and deleted.json()["freed_bytes"] > 0

    listing = client.get(f"/api/v1/assemblies/{assembly['id']}/files").json()
    entry = listing["rounds"][0]["tables"][0]
    assert entry["audio_available"] is False and entry["audio_deleted_at"]
    assert listing["totals"]["audio_deleted"] == 1
    # the recording row survives so transcripts/findings keep their context
    assert client.get(f"/api/v1/recordings/{recording_id}/audio").status_code == 404


def test_session_export_zip_is_portable(client, tmp_path):
    assembly = _assembly(client, "TEST Export", tables=1)
    headers, joined = _join(client, assembly, 0, "10.8.8.5")
    _record(client, headers, joined["rounds"][0]["id"], _audio(tmp_path))

    response = client.get(f"/api/v1/assemblies/{assembly['id']}/export.zip")
    assert response.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    names = archive.namelist()
    assert "manifest.json" in names
    assert "report.json" in names and "report.md" in names
    assert "README.txt" in names
    assert any(name.startswith("audio/") for name in names), names

    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["format_version"] == 1
    assert manifest["assembly"]["name"] == "TEST Export"
    assert manifest["recordings"][0]["sha256"]
    assert manifest["recordings"][0]["audio_file"].startswith("audio/")


def test_audio_bundle_zip(client, tmp_path):
    assembly = _assembly(client, "TEST Bundle", tables=1)
    headers, joined = _join(client, assembly, 0, "10.8.8.6")
    _record(client, headers, joined["rounds"][0]["id"], _audio(tmp_path))

    response = client.get(f"/api/v1/assemblies/{assembly['id']}/audio.zip")
    assert response.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert len(archive.namelist()) == 1
    assert archive.namelist()[0].endswith(".webm")


def _transcript_and_finding(assembly_id, recording_id):
    """Give a recording a transcript with one segment and a finding citing it."""
    from citizens.db.models import Finding, FindingEvidence, Recording, Transcript
    from citizens.db.models.transcript import TranscriptSegment
    from citizens.db.session import session_scope

    with session_scope() as session:
        recording = session.get(Recording, recording_id)
        transcript = Transcript(
            recording_id=recording_id, provider="test", model="test", language="en",
            raw_response_path=f"transcripts/{assembly_id}/{recording_id}.raw.json",
        )
        segment = TranscriptSegment(
            transcript=transcript, sequence=0, speaker_label="SPEAKER_00",
            start_seconds=0.0, end_seconds=2.0, text="The last bus leaves too early.",
        )
        session.add(transcript)
        session.flush()  # the evidence link needs the segment's generated id
        finding = Finding(
            assembly_id=assembly_id, round_id=recording.round_id, table_id=recording.table_id,
            recording_id=recording_id, scope="table", type="proposal",
            title="Later buses", summary="Extend evening service.", status="APPROVED",
        )
        finding.evidence.append(FindingEvidence(transcript_segment_id=segment.id))
        session.add(finding)
        session.flush()
        return finding.id


def test_delete_transcript_keeps_findings_and_allows_retranscription(client, tmp_path, settings_env):
    from citizens.db.models import Finding, Recording, Transcript
    from citizens.db.session import session_scope

    assembly = _assembly(client, "TEST Del Transcript", tables=1)
    headers, joined = _join(client, assembly, 0, "10.8.8.7")
    recording_id = _record(client, headers, joined["rounds"][0]["id"], _audio(tmp_path))
    finding_id = _transcript_and_finding(assembly["id"], recording_id)

    raw = settings_env.app_persistent_storage / "transcripts" / assembly["id"] / f"{recording_id}.raw.json"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text('{"verbatim": "the last bus leaves too early"}')

    listing = client.get(f"/api/v1/assemblies/{assembly['id']}/files").json()
    assert listing["rounds"][0]["tables"][0]["has_transcript"] is True

    # the report quotes the transcript before deletion
    report = client.get(f"/api/v1/assemblies/{assembly['id']}/report").json()
    quoted = report["rounds"][0]["tables"][0]["findings"][0]
    assert quoted["evidence"][0]["text"] == "The last bus leaves too early."

    deleted = client.delete(f"/api/v1/recordings/{recording_id}/transcript")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True, "retranscribable": True}

    # verbatim text is gone from the DB and from disk
    assert not raw.exists()
    with session_scope() as session:
        assert session.query(Transcript).filter_by(recording_id=recording_id).one_or_none() is None
        finding = session.get(Finding, finding_id)
        assert finding is not None  # the finding survives…
        assert finding.evidence_removed_at is not None  # …flagged as quote-less
        assert session.get(Recording, recording_id).state == "AUDIO_READY"

    listing = client.get(f"/api/v1/assemblies/{assembly['id']}/files").json()
    assert listing["rounds"][0]["tables"][0]["has_transcript"] is False
    assert listing["rounds"][0]["tables"][0]["audio_available"] is True

    report = client.get(f"/api/v1/assemblies/{assembly['id']}/report").json()
    stripped = report["rounds"][0]["tables"][0]["findings"][0]
    assert stripped["evidence"] == []
    assert stripped["evidence_removed"] is True
    assert stripped["title"] == "Later buses"

    # the audio is still there, so transcription can run again
    assert client.post(f"/api/v1/recordings/{recording_id}/transcribe").status_code in (200, 202)


def test_delete_all_transcripts_and_frozen_report_refresh(client, tmp_path):
    assembly = _assembly(client, "TEST Del All Transcripts", tables=1)
    headers, joined = _join(client, assembly, 0, "10.8.8.8")
    recording_id = _record(client, headers, joined["rounds"][0]["id"], _audio(tmp_path))
    _transcript_and_finding(assembly["id"], recording_id)

    client.post(f"/api/v1/assemblies/{assembly['id']}/close")
    frozen = client.get("/api/v1/public/recorder/report", headers=headers).json()
    assert frozen["rounds"][0]["tables"][0]["findings"][0]["evidence"], "quotes expected before"

    result = client.delete(f"/api/v1/assemblies/{assembly['id']}/transcripts")
    assert result.status_code == 200 and result.json()["transcripts"] == 1

    # the frozen copy participants read is re-snapshotted without the quotes
    after = client.get("/api/v1/public/recorder/report", headers=headers).json()
    assert after["rounds"][0]["tables"][0]["findings"][0]["evidence"] == []


def test_audio_retention_purges_only_after_the_window(client, tmp_path, monkeypatch):
    """Retention is audio-only and clocked from closing, so an assembly that
    runs for weeks is never affected while it is still open."""
    from datetime import timedelta

    from citizens.db.models import Assembly, Recording
    from citizens.db.models.base import utcnow
    from citizens.db.session import session_scope
    from citizens.jobs.sweep import sweep_expired_audio
    from citizens.services import provider_config

    class _Store:
        def get_value(self, key):
            return "7" if key == "audio_retention_days" else None

        def set_value(self, key, value, sensitive=False):
            pass

        def delete_value(self, key):
            pass

    monkeypatch.setattr(provider_config, "default_store", lambda: _Store())

    assembly = _assembly(client, "TEST Retention", tables=1)
    headers, joined = _join(client, assembly, 0, "10.8.8.9")
    recording_id = _record(client, headers, joined["rounds"][0]["id"], _audio(tmp_path))
    client.post(f"/api/v1/assemblies/{assembly['id']}/close")

    assert sweep_expired_audio() == 0  # closed just now, nothing is due

    with session_scope() as session:
        session.get(Assembly, assembly["id"]).closed_at = utcnow() - timedelta(days=8)
        # a transcript exists, so retention treats the audio as redundant and
        # deletes it — the untranscribed case is kept, and covered elsewhere
        from citizens.db.models import Transcript

        session.add(Transcript(recording_id=recording_id, provider="test"))

    assert sweep_expired_audio() == 1
    with session_scope() as session:
        assert session.get(Assembly, assembly["id"]).audio_purged_at is not None
        assert session.get(Recording, recording_id).audio_deleted_at is not None
    assert sweep_expired_audio() == 0  # and never twice


def test_closing_mid_assembly_stops_phones_and_refuses_more_rounds(client):
    """The early-end bug: an orchestrated assembly ended during round 1, with
    later rounds still NOT_STARTED. Phones must learn it is over (they read only
    the round rows otherwise, and advanced into round 2), and the server must
    refuse to start another round on a closed assembly."""
    assembly = client.post(
        "/api/v1/assemblies",
        json={
            "name": "TEST early end", "recording_mode": "orchestrated",
            "default_table_count": 1,
            "rounds": [
                {"title": "R1", "question": "Q1", "duration_minutes": 10},
                {"title": "R2", "question": "Q2", "duration_minutes": 10},
            ],
        },
    ).json()
    r1, r2 = assembly["rounds"][0]["id"], assembly["rounds"][1]["id"]
    client.post(f"/api/v1/rounds/{r1}/start")
    headers, _ = _join(client, assembly, 0, "203.0.113.1")

    # while open, the phone is told nothing has ended
    status = client.get("/api/v1/public/recorder/status", headers=headers).json()
    assert status["assembly_closed"] is False

    # the organizer ends the assembly early, round 2 still NOT_STARTED
    assert client.post(f"/api/v1/assemblies/{assembly['id']}/close").status_code == 200

    # the phone now learns the assembly is over — the signal it was missing
    status = client.get("/api/v1/public/recorder/status", headers=headers).json()
    assert status["assembly_closed"] is True

    # and round 2 can no longer be started onto the closed assembly
    blocked = client.post(f"/api/v1/rounds/{r2}/start")
    assert blocked.status_code == 409
    assert "closed" in blocked.json()["detail"].lower()

    # reopening lifts the guard, so a genuine resume still works
    client.delete(f"/api/v1/assemblies/{assembly['id']}/close")
    assert client.post(f"/api/v1/rounds/{r2}/start").status_code == 200
