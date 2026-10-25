# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Zero retention (0.7, S10): an assembly that keeps nothing but its report.
Closed and processed, its audio and transcripts go, a PDF of the frozen
report stays, and nothing can bring the assembly back."""

import time

from sqlalchemy import select

from citizens.db.models import Assembly, AuditEvent, Recording
from citizens.db.session import session_scope
from citizens.services import zero_retention
from citizens.services.consent import notice_for
from tests.integration.test_change_language import _recorded_assembly


def _wait_applied(assembly_id: str, timeout: float = 40.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with session_scope() as session:
            if session.get(Assembly, assembly_id).zero_retention_done_at is not None:
                return True
        zero_retention.sweep()
        time.sleep(0.5)
    return False


def test_zero_retention_keeps_only_the_report(client, tmp_path, monkeypatch, settings_env):
    seen: list[str] = []
    assembly, round_id, recording_id, headers = _recorded_assembly(
        client, tmp_path, monkeypatch, seen, zero_retention=True, audio_retention_days=30
    )
    detail = client.get(f"/api/v1/assemblies/{assembly['id']}").json()
    assert detail["zero_retention"] is True and detail["zero_retention_done_at"] is None
    assert detail["audio_retention_days"] == 30
    # the notice says so, in the assembly's language
    with session_scope() as session:
        notice = notice_for(session.get(Assembly, assembly["id"]))
    assert any("deleted as soon as the assembly is closed" in p for p in notice.paragraphs)

    assert client.post(f"/api/v1/assemblies/{assembly['id']}/close").status_code == 200
    assert _wait_applied(assembly["id"]), "zero retention never ran"

    with session_scope() as session:
        row = session.get(Assembly, assembly["id"])
        assert row.final_report_json and row.audio_purged_at is not None
        recording = session.get(Recording, recording_id)
        assert recording.audio_deleted_at is not None
        assert recording.transcript_deleted_at is not None
        events = session.execute(
            select(AuditEvent.event).where(AuditEvent.event == "zero_retention_applied")
        ).scalars().all()
        assert events == ["zero_retention_applied"]
    assert not list(settings_env.app_persistent_storage.rglob("*.ogg")) \
        and not list(settings_env.app_persistent_storage.rglob("*.webm"))
    assert client.get(f"/api/v1/recordings/{recording_id}/transcript").status_code == 404
    retained = zero_retention.retained_pdf_path(assembly["id"])
    assert retained.is_file() and retained.read_bytes().startswith(b"%PDF")
    served = client.get(f"/api/v1/assemblies/{assembly['id']}/report.pdf")
    assert served.status_code == 200 and served.content == retained.read_bytes()

    # once: the sweep has nothing more to do; and nothing brings it back
    assert zero_retention.sweep() == 0
    reopened = client.delete(f"/api/v1/assemblies/{assembly['id']}/close")
    assert reopened.status_code == 409 and "ZERO_RETENTION_APPLIED" in reopened.json()["detail"]
    language = client.post(f"/api/v1/assemblies/{assembly['id']}/language", json={"language": "fr"})
    assert language.status_code == 409 and "ZERO_RETENTION_APPLIED" in language.json()["detail"]


def test_an_assembly_that_did_not_ask_keeps_its_audio(client, tmp_path, monkeypatch, settings_env):
    seen: list[str] = []
    assembly, round_id, recording_id, headers = _recorded_assembly(client, tmp_path, monkeypatch, seen)
    assert client.post(f"/api/v1/assemblies/{assembly['id']}/close").status_code == 200
    assert zero_retention.sweep() == 0
    with session_scope() as session:
        assert session.get(Assembly, assembly["id"]).zero_retention_done_at is None
        assert session.get(Recording, recording_id).audio_deleted_at is None
    assert not zero_retention.retained_pdf_path(assembly["id"]).exists()


def test_the_flag_can_be_set_until_the_assembly_closes(client, tmp_path, monkeypatch):
    seen: list[str] = []
    assembly, round_id, recording_id, headers = _recorded_assembly(client, tmp_path, monkeypatch, seen)
    changed = client.put(f"/api/v1/assemblies/{assembly['id']}", json={"zero_retention": True})
    assert changed.status_code == 200 and changed.json()["zero_retention"] is True
    assert client.post(f"/api/v1/assemblies/{assembly['id']}/close").status_code == 200
    assert _wait_applied(assembly["id"])
