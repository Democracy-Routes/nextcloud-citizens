# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deleting audio must delete every copy of it.

An export archive contains a complete second copy of an assembly's audio.
Nothing but full assembly deletion ever reclaimed one, so the retention sweep
logged audio_retention_purge with a freed_bytes figure while an entire copy of
the audio sat in exports/<assembly>/audio-*.zip indefinitely. The operator's
retention policy said the recordings were gone; the disk disagreed.

They accumulate in the first place because _zip_response unlinks the archive in
a background task that never runs when a client disconnects mid-download —
which, downloading gigabytes over venue WiFi, is the ordinary outcome.
"""

import os
import time

from citizens.config import get_settings
from citizens.jobs import sweep
from citizens.storage.paths import exports_dir


def _assembly(client, name="TEST Export Retention"):
    return client.post(
        "/api/v1/assemblies",
        json={
            "name": name,
            "default_table_count": 1,
            "rounds": [{"title": "R1", "question": "Q?", "duration_minutes": 30}],
        },
    ).json()


def _exports(assembly_id):
    directory = exports_dir(get_settings().app_persistent_storage, assembly_id)
    return sorted(directory.glob("*.zip")) if directory.is_dir() else []


def _abandoned_archive(assembly_id, name="audio-20260101-000000.zip", age_minutes=0):
    """An archive left behind by a download nobody finished."""
    directory = exports_dir(get_settings().app_persistent_storage, assembly_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(b"PK\x03\x04" + b"0" * 1024)
    if age_minutes:
        old = time.time() - age_minutes * 60
        os.utime(path, (old, old))
    return path


def test_deleting_all_audio_removes_the_export_archives(client):
    assembly = _assembly(client)
    _abandoned_archive(assembly["id"])
    assert _exports(assembly["id"]), "fixture did not create an archive"

    response = client.delete(f"/api/v1/assemblies/{assembly['id']}/audio")

    assert response.status_code == 200, response.text
    assert _exports(assembly["id"]) == [], (
        "a full copy of the audio survives inside an export archive, so the "
        "audio was not really deleted"
    )


def test_the_retention_purge_removes_the_export_archives(client, monkeypatch):
    """The compliance case: an automatic purge must not leave a copy behind."""
    from citizens.services import provider_config

    assembly = _assembly(client)
    _abandoned_archive(assembly["id"])
    client.post(f"/api/v1/assemblies/{assembly['id']}/close")
    monkeypatch.setattr(
        provider_config, "get_setting", lambda _store, _key: "1"
    )
    monkeypatch.setattr(provider_config, "default_store", lambda: object())

    # retention of 1 day, closed "two days ago"
    from datetime import timedelta

    from citizens.db.models import Assembly
    from citizens.db.models.base import utcnow
    from citizens.db.session import session_scope

    with session_scope() as session:
        db_assembly = session.get(Assembly, assembly["id"])
        db_assembly.closed_at = utcnow() - timedelta(days=2)
        db_assembly.audio_retention_days = 1

    assert sweep.sweep_expired_audio() == 1
    assert _exports(assembly["id"]) == [], (
        "the retention sweep reported the audio purged while a complete copy "
        "of it remained in an export archive"
    )


def test_an_abandoned_archive_is_swept_after_its_ttl(client):
    assembly = _assembly(client)
    _abandoned_archive(assembly["id"], age_minutes=sweep.EXPORT_TTL_MINUTES + 10)

    assert sweep.sweep_stale_exports() == 1
    assert _exports(assembly["id"]) == []


def test_a_fresh_archive_is_left_alone(client):
    """Someone may be downloading it right now."""
    assembly = _assembly(client)
    _abandoned_archive(assembly["id"], age_minutes=1)

    assert sweep.sweep_stale_exports() == 0
    assert len(_exports(assembly["id"])) == 1


def test_building_a_second_archive_replaces_the_first(client):
    """Otherwise every abandoned download leaves another full copy on disk."""
    assembly = _assembly(client)

    client.get(f"/api/v1/assemblies/{assembly['id']}/audio.zip")
    client.get(f"/api/v1/assemblies/{assembly['id']}/audio.zip")

    audio_archives = [p for p in _exports(assembly["id"]) if p.name.startswith("audio-")]
    assert len(audio_archives) <= 1, (
        f"{len(audio_archives)} archives accumulated, each a full copy of the audio"
    )


def test_the_sweep_runs_with_the_others(client):
    """It has to be registered, or none of the above ever happens."""
    import inspect

    assert "sweep_stale_exports" in inspect.getsource(sweep.run_sweeps)


def test_retention_keeps_audio_that_has_no_transcript(client, monkeypatch):
    """A recording that never got a transcript (failed STT, a stranded partial,
    both switches off) has audio that is the ONLY representation of that part of
    the discussion. Deleting it on the retention timer turned a failed
    transcription plus an expiry into a silently lost conversation."""
    import hashlib
    import re
    from datetime import timedelta

    from citizens.db.models import Assembly, Recording
    from citizens.db.models.base import utcnow
    from citizens.db.session import session_scope
    from citizens.services import files as files_svc
    from citizens.services import provider_config

    # a real recording, via the recorder flow, then forced to TRANSCRIPTION_FAILED
    assembly = _assembly(client, name="TEST Keep untranscribed")
    round_id = assembly["rounds"][0]["id"]
    client.post(f"/api/v1/rounds/{round_id}/start")
    invites = client.post(f"/api/v1/assemblies/{assembly['id']}/invites/generate").json()
    token = re.search(r"#/join/(.+)$", invites[0]["url"]).group(1)
    joined = client.post("/api/v1/public/join", json={"token": token},
                         headers={"X-Origin-IP": "203.0.113.2"}).json()
    headers = {"Authorization": f"Bearer {joined['session_token']}"}
    rec_id = client.post("/api/v1/public/recorder/start",
                         json={"round_id": round_id, "mime_type": "audio/webm"},
                         headers=headers).json()["recording_id"]
    blob = b"audio-bytes"
    client.post(f"/api/v1/public/recorder/recordings/{rec_id}/chunks/0", content=blob,
                headers={**headers, "Content-Type": "application/octet-stream",
                         "X-Chunk-SHA256": hashlib.sha256(blob).hexdigest()})
    with session_scope() as session:
        session.get(Recording, rec_id).state = "TRANSCRIPTION_FAILED"

    monkeypatch.setattr(provider_config, "get_setting", lambda _store, _key: "1")
    monkeypatch.setattr(provider_config, "default_store", lambda: object())
    with session_scope() as session:
        db_assembly = session.get(Assembly, assembly["id"])
        db_assembly.closed_at = utcnow() - timedelta(days=2)
        db_assembly.audio_retention_days = 1

    sweep.sweep_expired_audio()

    with session_scope() as session:
        assert session.get(Recording, rec_id).audio_deleted_at is None, (
            "retention deleted the only copy of an untranscribed discussion"
        )
        listing = files_svc.list_files(session, session.get(Assembly, assembly["id"]))
        assert listing["totals"]["kept_past_retention"] == 1
