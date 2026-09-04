# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Analysis chain: transcription → table findings → cross-table → review → report.
Also the recorder duplicate-recording guard (one healthy recording per table+round).
"""

import hashlib
import re
import subprocess
import time

import pytest

from citizens.domain.analysis_schemas import RoundAnalysis, TableAnalysis
from citizens.providers.transcription.base import NormalizedSegment, NormalizedTranscript


class MemoryStore:
    def __init__(self, values=None):
        self.values = values or {}

    def get_value(self, key):
        return self.values.get(key)

    def set_value(self, key, value, sensitive=False):
        self.values[key] = value

    def delete_value(self, key):
        self.values.pop(key, None)


FAKE_TRANSCRIPT = NormalizedTranscript(
    provider="deepgram", model="nova-3", language="en",
    segments=[
        NormalizedSegment(speaker="SPEAKER_01", start=0.5, end=4.0,
                          text="The evening buses should run much later on weekends."),
        NormalizedSegment(speaker="SPEAKER_02", start=4.5, end=8.0,
                          text="I disagree, the money should go to bike lanes instead."),
    ],
    raw={},
)


@pytest.fixture
def pipeline(client, tmp_path, monkeypatch):
    store = MemoryStore({
        "deepgram_api_key": "dg-test", "stt_provider": "deepgram", "stt_batch_enabled": "1",
        "analysis_api_key": "an-test", "analysis_enabled": "1",
    })
    monkeypatch.setattr("citizens.services.provider_config.default_store", lambda: store)
    monkeypatch.setattr(
        "citizens.services.transcription.deepgram_provider.transcribe_file",
        lambda *a, **k: FAKE_TRANSCRIPT,
    )

    calls = {"table": 0, "round": 0}
    # kept separately from the counters, which a test asserts on exactly: this
    # is what actually LEFT the server, for the redaction tests
    prompts: list[str] = []

    def fake_chat_json(base_url, key, model, system, user, schema):
        assert key == "an-test"
        prompts.append(user)
        if schema is TableAnalysis:
            calls["table"] += 1
            # cite the first segment id embedded in the prompt: "[id1|id2] SPEAKER..."
            first_ids = re.search(r"\[([0-9a-f|-]+)\]", user).group(1)
            return TableAnalysis.model_validate({
                "summary": "The table discussed evening bus service and possible alternatives.",
                "findings": [
                    {"type": "proposal", "title": "Extend evening bus service",
                     "summary": "Buses should run later, especially weekends.",
                     "support": "mixed", "evidence_segment_ids": [first_ids.split("|")[0]]},
                    {"type": "concern", "title": "Invented claim",
                     "summary": "This one cites a fake segment.",
                     "evidence_segment_ids": ["not-a-real-segment"]},
                ]
            })
        calls["round"] += 1
        finding_id = re.search(r"\[([0-9a-f-]{36})\]", user).group(1)
        return RoundAnalysis.model_validate({
            "summary": "Across tables, extending evening bus service was the main topic.",
            "clusters": [{"type": "proposal", "title": "Later buses (recurring)",
                          "summary": "Raised across tables.", "source_finding_ids": [finding_id]}]
        })

    monkeypatch.setattr("citizens.services.analysis.chat_json", fake_chat_json)

    assembly = client.post(
        "/api/v1/assemblies",
        json={"name": "TEST Analysis", "default_table_count": 1,
              "rounds": [{"title": "R1", "question": "Transport?", "duration_minutes": 30}]},
    ).json()
    client.post(f"/api/v1/rounds/{assembly['rounds'][0]['id']}/start")
    invites = client.post(f"/api/v1/assemblies/{assembly['id']}/invites/generate").json()
    token = re.search(r"#/join/(.+)$", invites[0]["url"]).group(1)
    joined = client.post("/api/v1/public/join", json={"token": token},
                         headers={"X-Forwarded-For": "10.4.4.4"}).json()
    headers = {"Authorization": f"Bearer {joined['session_token']}"}

    audio = tmp_path / "s.webm"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    "-c:a", "libopus", str(audio)], check=True, timeout=120)
    blob = audio.read_bytes()
    round_id = joined["rounds"][0]["id"]
    recording_id = client.post(
        "/api/v1/public/recorder/start",
        json={"round_id": round_id, "mime_type": "audio/webm"}, headers=headers,
    ).json()["recording_id"]
    client.post(
        f"/api/v1/public/recorder/recordings/{recording_id}/chunks/0", content=blob,
        headers={**headers, "Content-Type": "application/octet-stream",
                 "X-Chunk-SHA256": hashlib.sha256(blob).hexdigest()},
    )
    client.post(f"/api/v1/public/recorder/recordings/{recording_id}/complete",
                json={"total_chunks": 1}, headers=headers)
    return {"client": client, "assembly": assembly, "round_id": round_id,
            "recording_id": recording_id, "headers": headers, "calls": calls,
            "prompts": prompts, "blob": blob}


def _wait(client, headers, recording_id, targets, timeout=40.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f"/api/v1/public/recorder/recordings/{recording_id}",
                            headers=headers).json()
        if status["state"] in targets:
            return status
        time.sleep(0.4)
    return status


def test_full_analysis_chain_and_report(pipeline):
    client = pipeline["client"]
    status = _wait(client, pipeline["headers"], pipeline["recording_id"], ("READY_FOR_REVIEW",))
    assert status["state"] == "READY_FOR_REVIEW", status

    # cross-table clustering follows automatically
    deadline = time.time() + 30
    findings = None
    while time.time() < deadline:
        findings = client.get(f"/api/v1/rounds/{pipeline['round_id']}/findings").json()
        if findings["cross_table"]:
            break
        time.sleep(0.5)
    assert findings["cross_table"], findings
    assert pipeline["calls"] == {"table": 1, "round": 1}

    # the invented-evidence finding was dropped; the real one has evidence text
    table_findings = findings["tables"][0]["findings"]
    assert len(table_findings) == 1
    assert table_findings[0]["title"] == "Extend evening bus service"
    assert table_findings[0]["status"] == "DRAFT"
    assert table_findings[0]["evidence"][0]["text"].startswith("The evening buses")
    cross = findings["cross_table"][0]
    assert cross["mentioned_table_count"] == 1

    # report excludes drafts by default, includes them on request (marked)
    report = client.get(f"/api/v1/assemblies/{pipeline['assembly']['id']}/report").json()
    assert all(not r["cross_table"] and not any(t["findings"] for t in r["tables"])
               for r in report["rounds"])
    draft_report = client.get(
        f"/api/v1/assemblies/{pipeline['assembly']['id']}/report?include_drafts=true"
    ).json()
    assert draft_report["rounds"][0]["cross_table"][0]["is_draft"] is True

    # review: approve table finding with an edit → EDITED_AND_APPROVED
    updated = client.put(
        f"/api/v1/findings/{table_findings[0]['id']}",
        json={"status": "APPROVED", "title": "Extend evening and weekend bus service"},
    ).json()
    assert updated["status"] == "EDITED_AND_APPROVED"
    client.put(f"/api/v1/findings/{cross['id']}", json={"status": "APPROVED"})

    report = client.get(f"/api/v1/assemblies/{pipeline['assembly']['id']}/report").json()
    round_report = report["rounds"][0]
    assert round_report["cross_table"][0]["title"] == "Later buses (recurring)"
    assert round_report["tables"][0]["findings"][0]["title"] == "Extend evening and weekend bus service"
    assert "not a measure of participant support" in report["methodology_note"]

    # exports are the FINAL artifact: blocked until the session is closed
    assembly_id = pipeline["assembly"]["id"]
    assert client.get(f"/api/v1/assemblies/{assembly_id}/report.md").status_code == 409

    client.post(f"/api/v1/assemblies/{assembly_id}/close")
    markdown = client.get(f"/api/v1/assemblies/{assembly_id}/report.md")
    assert markdown.status_code == 200
    assert "FINAL REPORT" in markdown.text
    assert "Extend evening and weekend bus service" in markdown.text
    assert "Mentioned at 1 table(s)" in markdown.text


def test_duplicate_recording_blocked(pipeline):
    client = pipeline["client"]
    _wait(client, pipeline["headers"], pipeline["recording_id"], ("READY_FOR_REVIEW",))

    # second recording for the same table+round is refused
    blocked = client.post(
        "/api/v1/public/recorder/start",
        json={"round_id": pipeline["round_id"], "mime_type": "audio/webm"},
        headers=pipeline["headers"],
    )
    assert blocked.status_code == 409
    assert "already recorded" in blocked.json()["detail"]

    # the public status exposes the recorded state for the phone UI
    status = client.get("/api/v1/public/recorder/status", headers=pipeline["headers"]).json()
    assert status["rounds"][0]["recorded_state"] == "READY_FOR_REVIEW"


def test_manual_analysis_requires_configuration(client, monkeypatch):
    store = MemoryStore({})  # no analysis key
    monkeypatch.setattr("citizens.services.provider_config.default_store", lambda: store)
    assembly = client.post(
        "/api/v1/assemblies",
        json={"name": "TEST NoKey", "default_table_count": 1,
              "rounds": [{"title": "R1", "question": "Q", "duration_minutes": 10}]},
    ).json()
    response = client.post(f"/api/v1/rounds/{assembly['rounds'][0]['id']}/analyze", json={})
    assert response.status_code == 409
    assert "not configured" in response.json()["detail"]
    findings = client.get(f"/api/v1/rounds/{assembly['rounds'][0]['id']}/findings").json()
    assert findings["analysis_configured"] is False


# ------------------------------------------------------ approving in one go


def _drafts_ready(pipeline) -> dict:
    """Run the fixture's pipeline through to reviewable findings."""
    client = pipeline["client"]
    _wait(client, pipeline["headers"], pipeline["recording_id"], ("READY_FOR_REVIEW",))
    deadline = time.time() + 30
    while time.time() < deadline:
        findings = client.get(f"/api/v1/rounds/{pipeline['round_id']}/findings").json()
        if findings["cross_table"]:
            return findings
        time.sleep(0.5)
    return findings


def _all_findings(payload: dict) -> list[dict]:
    return payload["cross_table"] + [f for t in payload["tables"] for f in t["findings"]]


def test_bulk_approve_takes_only_the_drafts(pipeline):
    """Reviewing one card at a time was tedious enough that the ask was for a
    way to skip review altogether. Approving in bulk is the version that keeps
    the guarantee: a person still decides, once, for a whole round."""
    client = pipeline["client"]
    round_id = pipeline["round_id"]
    drafts = [f for f in _all_findings(_drafts_ready(pipeline)) if f["status"] == "DRAFT"]
    assert drafts, "the pipeline should leave drafts to approve"
    rejected = drafts[0]["id"]
    client.put(f"/api/v1/findings/{rejected}", json={"status": "REJECTED"})

    result = client.post(f"/api/v1/rounds/{round_id}/findings/approve", json={})

    assert result.status_code == 200, result.text
    assert result.json()["approved"] == len(drafts) - 1
    after = {f["id"]: f["status"] for f in _all_findings(
        client.get(f"/api/v1/rounds/{round_id}/findings").json()
    )}
    # a rejection is a decision somebody made; a bulk approve must not reverse it
    assert after[rejected] == "REJECTED"
    assert "DRAFT" not in after.values()


def test_bulk_approve_records_who_reviewed(pipeline):
    from sqlalchemy import select

    from citizens.db.models import AuditEvent, Finding
    from citizens.db.session import session_scope

    client = pipeline["client"]
    round_id = pipeline["round_id"]
    _drafts_ready(pipeline)

    approved = client.post(
        f"/api/v1/rounds/{round_id}/findings/approve", json={}
    ).json()["approved"]

    with session_scope() as session:
        reviewed = session.execute(
            select(Finding).where(Finding.round_id == round_id, Finding.status == "APPROVED")
        ).scalars().all()
        assert reviewed and all(f.reviewed_by and f.reviewed_at for f in reviewed)
        ids = {f.id for f in reviewed}
        events = session.execute(
            select(AuditEvent).where(AuditEvent.event == "finding_reviewed")
        ).scalars().all()
        # one audit row per finding, not one for the batch
        assert len([e for e in events if e.object_id in ids]) >= approved


def test_bulk_approve_can_be_scoped_to_one_table(pipeline):
    client = pipeline["client"]
    round_id = pipeline["round_id"]
    _drafts_ready(pipeline)

    result = client.post(
        f"/api/v1/rounds/{round_id}/findings/approve", json={"table_number": 1}
    )

    assert result.status_code == 200, result.text
    after = client.get(f"/api/v1/rounds/{round_id}/findings").json()
    # cross-table findings belong to no table, so they stay as drafts
    assert all(f["status"] == "DRAFT" for f in after["cross_table"])
    assert all(f["status"] == "APPROVED" for t in after["tables"] for f in t["findings"])


def test_bulk_approve_rejects_an_unknown_table(pipeline):
    result = pipeline["client"].post(
        f"/api/v1/rounds/{pipeline['round_id']}/findings/approve",
        json={"table_number": 99},
    )

    assert result.status_code == 404


# ------------------------------------------ names must not reach the model


def test_participant_names_are_masked_before_the_transcript_is_sent(pipeline):
    """The end-to-end version: whatever the table said, the prompt that leaves
    this server carries stand-ins.

    The stored transcript is deliberately untouched — it is the record, and the
    report's quotes come from it — so this asserts on what the provider was
    handed, not on what is in the database.
    """
    from citizens.db.models import Assembly
    from citizens.db.session import session_scope

    with session_scope() as session:
        assembly = session.get(Assembly, pipeline["assembly"]["id"])
        assembly.redact_names = "Simone, Alessandro"

    _drafts_ready(pipeline)

    prompts = pipeline["prompts"]
    assert prompts, "the analysis provider should have been called"
    sent = "\n".join(prompts)
    assert "Simone" not in sent
    assert "Alessandro" not in sent


def test_the_stored_transcript_keeps_the_real_words(pipeline):
    """Redaction protects what is SENT. The record must stay intact, or the
    report's evidence stops being what the table actually said."""
    from sqlalchemy import select

    from citizens.db.models import Assembly, TranscriptSegment
    from citizens.db.session import session_scope

    with session_scope() as session:
        assembly = session.get(Assembly, pipeline["assembly"]["id"])
        assembly.redact_names = "Simone"

    _drafts_ready(pipeline)

    with session_scope() as session:
        segments = session.execute(select(TranscriptSegment)).scalars().all()
        assert segments, "the pipeline should have produced a transcript"
        assert not any("[Person" in s.text for s in segments)
