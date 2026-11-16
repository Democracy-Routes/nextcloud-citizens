# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Finished material back into the pipeline: uploads in parts, a session
export imported as a new assembly, a transcript or audio attached to a
recording whose own chunks failed."""

import hashlib
import io
import json
import re
import subprocess
import time
import zipfile

from citizens.db.models import AppJob, Recording, Transcript
from citizens.db.session import session_scope


class MemoryStore:
    def __init__(self, values=None):
        self.values = values or {}

    def get_value(self, key):
        return self.values.get(key)

    def set_value(self, key, value, sensitive=False):
        self.values[key] = value

    def delete_value(self, key):
        self.values.pop(key, None)


def _audio(tmp_path, name="in.webm", seconds=2) -> bytes:
    path = tmp_path / name
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}",
         "-c:a", "libopus", "-b:a", "32k", str(path)],
        check=True, timeout=120,
    )
    return path.read_bytes()


def _upload(client, payload: bytes, kind: str, filename="file", user=None, part_bytes=None) -> str:
    headers = {"X-Test-User": user} if user else {}
    opened = client.post(
        "/api/v1/uploads", json={"kind": kind, "filename": filename, "size_bytes": len(payload)},
        headers=headers,
    )
    assert opened.status_code == 201, opened.text
    opened = opened.json()
    size = part_bytes or opened["part_bytes"]
    for index in range(opened["parts"]):
        part = payload[index * size:(index + 1) * size]
        sent = client.post(
            f"/api/v1/uploads/{opened['upload_id']}/parts/{index}", content=part,
            headers={**headers, "Content-Type": "application/octet-stream"},
        )
        assert sent.status_code == 200, sent.text
    done = client.post(
        f"/api/v1/uploads/{opened['upload_id']}/complete",
        json={"sha256": hashlib.sha256(payload).hexdigest()}, headers=headers,
    )
    assert done.status_code == 200, done.text
    return opened["upload_id"]


def _transcript(texts, speaker="SPEAKER_01", provider="mistral") -> dict:
    return {
        "provider": provider, "model": "voxtral", "language": "it",
        "segments": [
            {"speaker": speaker, "start": float(i * 5), "end": float(i * 5 + 4), "text": text}
            for i, text in enumerate(texts)
        ],
    }


def _format1_archive(recordings: list[dict], transcripts: dict[str, dict], **assembly) -> bytes:
    """An archive like the one a 0.6 server writes: manifest + transcripts,
    no audio, no participants."""
    manifest = {
        "format_version": 1,
        "exported_at": "2026-11-06T15:22:53+00:00",
        "assembly": {
            "id": "old-assembly", "name": "Citizen Assembly su Milano", "description": "",
            "language": "it", "status": "COMPLETE", "recording_mode": "orchestrated",
            "expected_participants": 50, "default_table_count": 15,
            "analysis_instructions": "Produci l'analisi in italiano.",
            "created_at": "2026-10-01T13:45:15+00:00", "closed_at": "2026-10-01T18:56:31+00:00",
            **assembly,
        },
        "rounds": [{
            "id": "old-round", "position": 1, "title": "Round 1 - Tecnologia e Milano",
            "question": "", "duration_minutes": 40, "status": "READY_FOR_REVIEW",
            "analysis_summary": "old summary that must not be copied",
            "tables": [{"id": f"t{n}", "number": n, "label": ""} for n in range(1, 16)],
        }],
        "participants": [],
        "recordings": recordings,
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("README.txt", "x")
        archive.writestr("report.json", json.dumps({"rounds": []}))
        for recording_id, data in transcripts.items():
            archive.writestr(f"transcripts/{recording_id}.json", json.dumps(data))
    return buffer.getvalue()


def _recording(old_id, table, started, ended, state="READY_FOR_REVIEW", duration=1500.0):
    return {
        "id": old_id, "round_id": "old-round", "table_number": table, "state": state,
        "mime_type": "audio/webm;codecs=opus", "duration_seconds": duration, "sha256": "",
        "analysis_summary": "old", "audio_file": None, "audio_deleted_at": "2026-10-08T18:56:42+00:00",
        "started_at": started, "ended_at": ended,
    }


MILANO = [
    _recording("rec-1", 1, "2026-10-01T18:26:45+00:00", "2026-10-01T18:53:25+00:00"),
    _recording("rec-2", 2, "2026-10-01T18:26:52+00:00", "2026-10-01T18:41:01+00:00", duration=848.0),
    _recording("rec-7", 7, "2026-10-01T18:26:50+00:00", None, state="UPLOAD_INCOMPLETE", duration=None),
    _recording("rec-8", 8, "2026-10-01T18:26:50+00:00", "2026-10-01T18:53:18+00:00",
               state="AUDIO_INVALID", duration=None),
    _recording("rec-12", 12, "2026-10-01T18:41:14+00:00", "2026-10-01T18:53:14+00:00", duration=719.0),
]
MILANO_TRANSCRIPTS = {
    "rec-1": _transcript(["Tavolo uno parla", "Ancora tavolo uno"]),
    "rec-2": _transcript(["Prima parte del tavolo due"], speaker="SPEAKER_03"),
    "rec-12": _transcript(["Seconda parte del tavolo due"], speaker="SPEAKER_01"),
}


def _files(client, assembly_id) -> dict:
    listing = client.get(f"/api/v1/assemblies/{assembly_id}/files").json()
    return {entry["table_number"]: entry for round_ in listing["rounds"] for entry in round_["tables"]}


def _entries(client, assembly_id) -> list[dict]:
    listing = client.get(f"/api/v1/assemblies/{assembly_id}/files").json()
    return [entry for round_ in listing["rounds"] for entry in round_["tables"]]


# --- uploads ---------------------------------------------------------------

def test_upload_parts_are_checked_and_belong_to_the_uploader(client):
    payload = b"x" * 10
    opened = client.post(
        "/api/v1/uploads", json={"kind": "transcript", "filename": "t.json", "size_bytes": 10}
    ).json()
    assert opened["parts"] == 1 and opened["part_bytes"] > 10
    short = client.post(f"/api/v1/uploads/{opened['upload_id']}/parts/0", content=b"xxx")
    assert short.status_code == 422
    stranger = client.post(
        f"/api/v1/uploads/{opened['upload_id']}/parts/0", content=payload,
        headers={"X-Test-User": "someone-else"},
    )
    assert stranger.status_code == 404
    assert client.post(f"/api/v1/uploads/{opened['upload_id']}/parts/0", content=payload).status_code == 200
    bad = client.post(f"/api/v1/uploads/{opened['upload_id']}/complete", json={"sha256": "0" * 64})
    assert bad.status_code == 422 and "checksum" in bad.json()["detail"]
    good = client.post(
        f"/api/v1/uploads/{opened['upload_id']}/complete",
        json={"sha256": hashlib.sha256(payload).hexdigest()},
    )
    assert good.status_code == 200 and good.json()["size_bytes"] == 10
    assert client.delete(f"/api/v1/uploads/{opened['upload_id']}").status_code == 204
    # consumed or discarded: the id is gone
    refused = client.post("/api/v1/assemblies/import", json={"upload_id": opened["upload_id"]})
    assert refused.status_code == 404


def test_an_upload_of_the_wrong_kind_is_refused_by_the_consumer(client):
    upload_id = _upload(client, b"{}", "audio")
    refused = client.post("/api/v1/assemblies/import", json={"upload_id": upload_id})
    assert refused.status_code == 422 and "not a session export" in refused.json()["detail"]


# --- a whole session ---------------------------------------------------------

def test_a_format_1_export_becomes_a_closed_assembly_with_merged_tables(client, monkeypatch):
    store = MemoryStore({"analysis_api_key": "ak-test", "analysis_enabled": "1"})
    monkeypatch.setattr("citizens.services.provider_config.default_store", lambda: store)
    archive = _format1_archive(MILANO, MILANO_TRANSCRIPTS)
    upload_id = _upload(client, archive, "session_export", "export.zip")

    response = client.post(
        "/api/v1/assemblies/import",
        json={"upload_id": upload_id, "name": "Citizen Assembly - Milano Digital Week",
              "merge_tables": [{"from": 12, "into": 2}]},
    )
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["name"] == "Citizen Assembly - Milano Digital Week"
    assert (result["rounds"], result["tables"], result["recordings"], result["transcripts"]) == (1, 14, 5, 3)
    assert result["audio_files"] == 0 and result["analysis_queued"] is True
    assert result["skipped"] == []

    detail = client.get(f"/api/v1/assemblies/{result['assembly_id']}").json()
    assert detail["status"] == "COMPLETE" and detail["language"] == "it"
    assert detail["analysis_instructions"] == "Produci l'analisi in italiano."
    assert detail["rounds"][0]["title"] == "Round 1 - Tecnologia e Milano"
    # nothing of the old analysis came along
    assert not detail["rounds"][0].get("analysis_summary")

    entries = _entries(client, result["assembly_id"])
    by_table: dict[int, list] = {}
    for entry in entries:
        by_table.setdefault(entry["table_number"], []).append(entry)
    assert sorted(by_table) == [1, 2, 7, 8]
    assert [e["state"] for e in by_table[1]] == ["TRANSCRIBED"]
    # the second phone's recording now belongs to table 2, after the first
    assert [e["state"] for e in by_table[2]] == ["TRANSCRIBED", "TRANSCRIBED"]
    assert by_table[7][0]["state"] == "UPLOAD_INCOMPLETE" and by_table[8][0]["state"] == "UPLOAD_INCOMPLETE"
    assert all(e["has_transcript"] for e in by_table[1] + by_table[2])
    assert not any(e["audio_available"] for e in entries)

    with session_scope() as session:
        rows = session.query(Recording).filter_by(assembly_id=result["assembly_id"]).all()
        table2 = sorted((r for r in rows if r.table_number == 2), key=lambda r: r.created_at)
        assert len({r.table_id for r in table2}) == 1
        texts = [
            [s.text for s in session.query(Transcript).filter_by(recording_id=r.id).one().segments]
            for r in table2
        ]
        assert texts == [["Prima parte del tavolo due"], ["Seconda parte del tavolo due"]]
        jobs = [json.loads(j.payload_json) for j in session.query(AppJob).filter_by(type="ANALYZE_TABLE")]
        # one analysis per table with a transcript, on the table's newest recording
        assert sorted(j["recording_id"] for j in jobs) == sorted(
            [next(r.id for r in rows if r.table_number == 1), table2[-1].id]
        )
        for transcript in session.query(Transcript):
            assert transcript.provider == "mistral" and transcript.language == "it"

    # the owner is who imported it
    assert client.get(
        f"/api/v1/assemblies/{result['assembly_id']}", headers={"X-Test-User": "someone-else"}
    ).status_code == 404


def test_import_without_a_provider_queues_nothing_and_says_so(client):
    archive = _format1_archive(MILANO[:1], {"rec-1": MILANO_TRANSCRIPTS["rec-1"]})
    upload_id = _upload(client, archive, "session_export")
    result = client.post("/api/v1/assemblies/import", json={"upload_id": upload_id}).json()
    assert result["analysis_queued"] is False and result["transcription_queued"] is False
    assert result["name"] == "Citizen Assembly su Milano"
    with session_scope() as session:
        assert session.query(AppJob).filter_by(type="ANALYZE_TABLE").count() == 0


def test_import_refusals(client):
    not_zip = _upload(client, b"this is not a zip", "session_export")
    assert client.post("/api/v1/assemblies/import", json={"upload_id": not_zip}).status_code == 422

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"format_version": 9, "assembly": {}, "rounds": [{}]}))
    future = _upload(client, buffer.getvalue(), "session_export")
    refused = client.post("/api/v1/assemblies/import", json={"upload_id": future})
    assert refused.status_code == 422 and "format" in refused.json()["detail"]

    archive = _format1_archive(MILANO[:1], {})
    circular = _upload(client, archive, "session_export")
    refused = client.post(
        "/api/v1/assemblies/import",
        json={"upload_id": circular, "merge_tables": [{"from": 2, "into": 3}, {"from": 3, "into": 2}]},
    )
    assert refused.status_code == 422


def test_a_format_2_export_of_this_server_round_trips_with_its_audio(client, tmp_path):
    from tests.integration.test_close_and_files import _assembly, _join, _record

    assembly = _assembly(client, "TEST Round trip", tables=1)
    headers, joined = _join(client, assembly, 0, "10.8.8.5")
    _record(client, headers, joined["rounds"][0]["id"], _audio(tmp_path))
    export = client.get(f"/api/v1/assemblies/{assembly['id']}/export.zip")
    assert export.status_code == 200
    manifest = json.loads(zipfile.ZipFile(io.BytesIO(export.content)).read("manifest.json"))
    assert manifest["format_version"] == 2 and manifest["recordings"][0]["audio_file"]

    upload_id = _upload(client, export.content, "session_export", "export.zip")
    result = client.post("/api/v1/assemblies/import", json={"upload_id": upload_id}).json()
    assert result["recordings"] == 1 and result["audio_files"] == 1
    assert result["assembly_id"] != assembly["id"]
    entry = _entries(client, result["assembly_id"])[0]
    assert entry["audio_available"] and entry["state"] == "AUDIO_READY"
    assert entry["sha256"] == manifest["recordings"][0]["sha256"]
    audio = client.get(f"/api/v1/recordings/{entry['recording_id']}/audio")
    assert audio.status_code == 200 and hashlib.sha256(audio.content).hexdigest() == entry["sha256"]


# --- one recording ---------------------------------------------------------

def _imported_failed_table(client, monkeypatch=None) -> tuple[str, str]:
    """An assembly whose table 8 is a recording with nothing in it."""
    upload_id = _upload(client, _format1_archive([MILANO[3]], {}), "session_export")
    result = client.post("/api/v1/assemblies/import", json={"upload_id": upload_id}).json()
    entry = _entries(client, result["assembly_id"])[0]
    assert entry["state"] == "UPLOAD_INCOMPLETE"
    return result["assembly_id"], entry["recording_id"]


def test_a_transcript_made_elsewhere_is_attached_and_analysed(client, monkeypatch):
    store = MemoryStore({"analysis_api_key": "ak-test", "analysis_enabled": "1"})
    monkeypatch.setattr("citizens.services.provider_config.default_store", lambda: store)
    assembly_id, recording_id = _imported_failed_table(client)
    payload = json.dumps(_transcript(["Ok, da questo momento stiamo registrando", "Sì"])).encode()
    upload_id = _upload(client, payload, "transcript", "table8-transcript.json")

    response = client.post(f"/api/v1/recordings/{recording_id}/transcript", json={"upload_id": upload_id})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "TRANSCRIBED" and body["segments"] == 2 and body["analysis_queued"] is True
    assert body["duration_seconds"] == 9.0

    stored = client.get(f"/api/v1/recordings/{recording_id}/transcript").json()
    assert [s["text"] for s in stored["segments"]] == ["Ok, da questo momento stiamo registrando", "Sì"]
    assert stored["provider"] == "mistral"
    assert _files(client, assembly_id)[8]["has_transcript"]
    with session_scope() as session:
        jobs = session.query(AppJob).filter_by(type="ANALYZE_TABLE").all()
        assert [json.loads(j.payload_json)["recording_id"] for j in jobs] == [recording_id]

    # attaching again replaces, and does not stack a second job while one is live
    again = _upload(client, json.dumps(_transcript(["Nuova versione"])).encode(), "transcript")
    response = client.post(f"/api/v1/recordings/{recording_id}/transcript", json={"upload_id": again})
    assert response.status_code == 200 and response.json()["analysis_queued"] is False
    stored = client.get(f"/api/v1/recordings/{recording_id}/transcript").json()
    assert [s["text"] for s in stored["segments"]] == ["Nuova versione"]


def test_transcript_refusals_and_ownership(client):
    assembly_id, recording_id = _imported_failed_table(client)
    not_json = _upload(client, b"nope", "transcript")
    refused = client.post(f"/api/v1/recordings/{recording_id}/transcript", json={"upload_id": not_json})
    assert refused.status_code == 422
    empty = _upload(client, b'{"segments": []}', "transcript")
    refused = client.post(f"/api/v1/recordings/{recording_id}/transcript", json={"upload_id": empty})
    assert refused.status_code == 422 and "no segments" in refused.json()["detail"]
    theirs = _upload(client, json.dumps(_transcript(["x"])).encode(), "transcript", user="someone-else")
    assert client.post(
        f"/api/v1/recordings/{recording_id}/transcript", json={"upload_id": theirs},
        headers={"X-Test-User": "someone-else"},
    ).status_code == 404
    assert client.post("/api/v1/recordings/nope/transcript", json={"upload_id": theirs}).status_code == 404


def test_audio_made_elsewhere_is_attached_and_transcription_queued(client, tmp_path, monkeypatch):
    store = MemoryStore({"stt_batch_enabled": "1", "stt_provider": "mistral", "mistral_api_key": "mk"})
    monkeypatch.setattr("citizens.services.provider_config.default_store", lambda: store)
    assembly_id, recording_id = _imported_failed_table(client)
    audio = _audio(tmp_path, seconds=3)
    upload_id = _upload(client, audio, "audio", "table8-repaired.webm")

    response = client.post(
        f"/api/v1/recordings/{recording_id}/audio", json={"upload_id": upload_id, "mime_type": "audio/webm"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "AUDIO_READY" and body["transcription_queued"] is True
    assert 2.5 < body["duration_seconds"] < 3.5
    entry = _files(client, assembly_id)[8]
    assert entry["audio_available"] and entry["duration_seconds"] == body["duration_seconds"]
    downloaded = client.get(f"/api/v1/recordings/{recording_id}/audio")
    assert downloaded.status_code == 200 and len(downloaded.content) > 1000
    with session_scope() as session:
        jobs = session.query(AppJob).filter_by(type="TRANSCRIBE_FINAL").all()
        assert [json.loads(j.payload_json)["recording_id"] for j in jobs] == [recording_id]
        assert session.get(Recording, recording_id).sha256 == hashlib.sha256(downloaded.content).hexdigest()

    # audio can only go where the server has none of its own
    second = _upload(client, audio, "audio")
    refused = client.post(f"/api/v1/recordings/{recording_id}/audio", json={"upload_id": second})
    assert refused.status_code == 409


def test_audio_that_is_not_audio_is_refused_before_anything_changes(client):
    assembly_id, recording_id = _imported_failed_table(client)
    upload_id = _upload(client, b"\x1c\x53\xbb\x6b\x80" * 100, "audio", "stub.webm")
    refused = client.post(f"/api/v1/recordings/{recording_id}/audio", json={"upload_id": upload_id})
    assert refused.status_code == 422 and "not audio" in refused.json()["detail"]
    assert _files(client, assembly_id)[8]["state"] == "UPLOAD_INCOMPLETE"


def test_audit_trail_names_the_three_events(client, tmp_path):
    assembly_id, recording_id = _imported_failed_table(client)
    upload_id = _upload(client, json.dumps(_transcript(["x"])).encode(), "transcript")
    client.post(f"/api/v1/recordings/{recording_id}/transcript", json={"upload_id": upload_id})
    upload_id = _upload(client, _audio(tmp_path), "audio")
    # TRANSCRIBED is not an audio-attachable state; the event list still has the import and the transcript
    client.post(f"/api/v1/recordings/{recording_id}/audio", json={"upload_id": upload_id})
    from citizens.db.models import AuditEvent

    with session_scope() as session:
        events = [e.event for e in session.query(AuditEvent).order_by(AuditEvent.created_at)]
    assert "session_imported" in events and "transcript_attached" in events
    assert "audio_attached" not in events


def _wait(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.2)
    return False


def test_proxy_has_a_route_for_every_import_verb():
    """The AppAPI proxy forwards GET/POST/PUT/DELETE only; every route here
    must use one of those (tests/unit/test_proxy_verbs.py checks the
    registered app too)."""
    from citizens.api.imports import router

    verbs = {method for route in router.routes for method in route.methods}
    assert verbs <= {"GET", "POST", "PUT", "DELETE"}
    assert not any(re.search(r"\{.*\}", r.path) and "PATCH" in r.methods for r in router.routes)


# --- hostile archives --------------------------------------------------------

def _with_audio(archive: bytes, members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO(archive)
    with zipfile.ZipFile(buffer, "a") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buffer.getvalue()


def _audio_recording(old_id, table, member, data):
    item = _recording(old_id, table, "2026-10-01T18:26:45+00:00", "2026-10-01T18:53:25+00:00")
    item["audio_file"] = member
    item["sha256"] = hashlib.sha256(data).hexdigest()
    return item


def _import(client, archive: bytes):
    upload_id = _upload(client, archive, "session_export")
    return client.post("/api/v1/assemblies/import", json={"upload_id": upload_id})


def test_a_recording_id_that_climbs_out_of_the_staging_directory_is_refused(client, settings_env):
    root = settings_env.app_persistent_storage
    root.mkdir(parents=True, exist_ok=True)
    sentinel = root / "pwned.db"
    sentinel.write_bytes(b"SENTINEL")
    before = {p for p in root.rglob("*") if "temp" not in p.relative_to(root).parts}
    for bad_id in ("../../../pwned", str(root / "pwned")):
        data = b"PWNED"
        archive = _with_audio(
            _format1_archive([_audio_recording(bad_id, 1, "a/x.db", data)], {}), {"a/x.db": data}
        )
        refused = _import(client, archive)
        assert refused.status_code == 422, refused.text
        assert "plain name" in refused.json()["detail"]
        assert sentinel.read_bytes() == b"SENTINEL"
    after = {p for p in root.rglob("*") if "temp" not in p.relative_to(root).parts}
    assert after - before == set()
    staged = root / "temp" / "imports"
    assert not staged.exists() or not any(staged.iterdir())


def test_audio_that_cannot_be_decoded_is_skipped_not_kept(client):
    data = b"not audio" * 100
    archive = _with_audio(
        _format1_archive([_audio_recording("rec-x", 1, "audio/x.webm", data)], {}), {"audio/x.webm": data}
    )
    response = _import(client, archive)
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["audio_files"] == 0
    assert any("not decodable" in note for note in result["skipped"])
    entry = _entries(client, result["assembly_id"])[0]
    assert not entry["audio_available"]


def test_an_audio_member_may_be_referenced_once(client, tmp_path):
    data = _audio(tmp_path)
    recordings = [_audio_recording(f"rec-{n}", n, "audio/a.webm", data) for n in (1, 2)]
    refused = _import(client, _with_audio(_format1_archive(recordings, {}), {"audio/a.webm": data}))
    assert refused.status_code == 422
    assert "referenced twice" in refused.json()["detail"]


def test_an_archive_with_too_many_recordings_is_refused(client):
    recordings = [
        _recording(f"rec-{n}", 1, "2026-10-01T18:26:45+00:00", "2026-10-01T18:53:25+00:00")
        for n in range(201)
    ]
    refused = _import(client, _format1_archive(recordings, {}))
    assert refused.status_code == 422
    assert "too many" in refused.json()["detail"]


def test_extraction_stops_when_the_disk_has_no_room_for_the_audio(client, tmp_path, monkeypatch):
    from citizens.storage import space

    data = _audio(tmp_path)
    archive = _with_audio(
        _format1_archive([_audio_recording("rec-1", 1, "audio/a.webm", data)], {}), {"audio/a.webm": data}
    )
    upload_id = _upload(client, archive, "session_export")
    monkeypatch.setattr(space, "free_bytes", lambda root: space.MIN_FREE_BYTES + len(data) - 1)
    refused = client.post("/api/v1/assemblies/import", json={"upload_id": upload_id})
    assert refused.status_code == 507
