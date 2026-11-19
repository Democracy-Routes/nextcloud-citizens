# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Record now finishes by itself (0.9): the server closes a session nobody
records in any more, approves every finding, freezes and publishes the report
and, with Polis configured, carries the statements to the voting link. The
model, the speech engine and Polis are faked; the job runner, the routes, the
sweeps and the audio are real."""

import hashlib
import json
import re
import subprocess
import time
from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from citizens.db.models import AppJob, Assembly, AuditEvent, Finding, Recording, StatementSeed
from citizens.db.models.base import utcnow
from citizens.db.session import session_scope
from citizens.domain.analysis_schemas import (
    RoundAnalysis,
    SeedClaim,
    SeedClaims,
    SeedClaimsForFinding,
    SeedDraft,
    SeedDrafts,
    SeedReview,
    SeedReviews,
    TableAnalysis,
)
from citizens.jobs import sweep
from citizens.services import auto_organized, zero_retention
from citizens.services import recording as rec_svc
from tests.integration.test_analysis_flow import FAKE_TRANSCRIPT, MemoryStore

BASE = {
    "deepgram_api_key": "dg-test", "stt_provider": "deepgram", "stt_batch_enabled": "1",
}
ANALYSIS = {"analysis_api_key": "an-test", "analysis_enabled": "1"}
POLIS = {"polis_url": "https://polis.example.org", "polis_api_key": "polis-secret-key"}
_ips = iter(f"10.77.{n // 200}.{n % 200 + 1}" for n in range(2000))


class FakeResponse:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body
        self.text = json.dumps(body) if body is not None else ""
        self.headers = {}

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


@pytest.fixture
def world(client, tmp_path, monkeypatch):
    """Factory for a configured world: `make(analysis=True, polis=False)` ->
    the handles every test needs. Record now, as the organizer's home does."""
    audio = tmp_path / "s.webm"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    "-c:a", "libopus", str(audio)], check=True, timeout=120)
    blob = audio.read_bytes()

    def make(*, analysis=True, polis=False, push_status=200):
        values = dict(BASE)
        if analysis:
            values.update(ANALYSIS)
        if polis:
            values.update(POLIS)
        store = MemoryStore(values)
        monkeypatch.setattr("citizens.services.provider_config.default_store", lambda: store)
        monkeypatch.setattr(
            "citizens.services.transcription.deepgram_provider.transcribe_file",
            lambda *a, **k: FAKE_TRANSCRIPT,
        )

        def fake_chat_json(base_url, key, model, system, user, schema):
            assert key == "an-test"
            if schema is TableAnalysis:
                first_ids = re.search(r"\[([0-9a-f|-]+)\]", user).group(1)
                return TableAnalysis.model_validate({
                    "summary": "The table discussed evening bus service.",
                    "findings": [{
                        "type": "proposal", "title": "Extend evening bus service",
                        "summary": "Buses should run later, especially weekends.",
                        "support": "mixed", "evidence_segment_ids": [first_ids.split("|")[0]],
                    }],
                })
            finding_id = re.search(r"\[([0-9a-f-]{36})\]", user).group(1)
            return RoundAnalysis.model_validate({
                "summary": "Across tables, later buses were the main topic.",
                "clusters": [{"type": "proposal", "title": "Later buses (recurring)",
                              "summary": "Raised across tables.", "source_finding_ids": [finding_id]}],
            })

        monkeypatch.setattr("citizens.services.analysis.chat_json", fake_chat_json)

        def fake_seed_chat(base_url, key, model, system, user, schema):
            if schema is SeedClaims:
                ids = [
                    line.split("finding_id: ", 1)[1]
                    for line in user.splitlines() if "finding_id: " in line
                ]
                return SeedClaims(findings=[
                    SeedClaimsForFinding(
                        finding_id=fid,
                        claims=[SeedClaim(
                            text=f"The city should run evening buses later, option {n}.", quote=None
                        )],
                    )
                    for n, fid in enumerate(ids, start=1)
                ])
            if schema is SeedDrafts:
                return SeedDrafts(statements=[
                    SeedDraft(ref=line.split(": ", 1)[0], text=line.split(": ", 1)[1])
                    for line in user.splitlines() if re.match(r"^F\d+\.\d+: ", line)
                ])
            if schema is SeedReviews:
                return SeedReviews(reviews=[
                    SeedReview(ref=line.strip(), grounded=2, contestable=2, single_idea=2, clear=2,
                               verdict="keep", text="")
                    for line in user.splitlines() if re.match(r"^F\d+\.\d+$", line.strip())
                ])
            raise AssertionError(schema)

        monkeypatch.setattr("citizens.services.seed_pipeline.chat_json", fake_seed_chat)

        pushes: list[dict] = []

        import httpx

        def fake_post(url, headers=None, json=None, timeout=None):
            if "polis.example.org" not in url:
                # anything else (the session's AI title) has no network here
                raise httpx.ConnectError("offline")
            pushes.append({"url": url, "auth": headers["Authorization"], "body": json})
            if push_status != 200:
                return FakeResponse(push_status, {"error": "polis_err_auth_no_such_api_token"})
            return FakeResponse(200, {
                "conversation_id": "conv1", "url": "https://polis.example.org/conv1",
                "created": True, "statements": {"added": len(json["statements"]), "results": []},
            })

        from citizens.services import polis as polis_svc
        monkeypatch.setattr(polis_svc.httpx, "post", fake_post)

        made = client.post("/api/v1/sessions/record-now", json={"language": "en"}).json()
        return {
            "client": client, "blob": blob, "made": made, "container": made["container_id"],
            "pushes": pushes, "store": store,
        }

    return make


def _join(client, url):
    token = re.search(r"#/join/(.+)$", url).group(1)
    joined = client.post("/api/v1/public/join", json={"token": token},
                         headers={"X-Forwarded-For": next(_ips)}).json()
    return joined, {"Authorization": f"Bearer {joined['session_token']}"}


def _start(w, headers, round_id, *, complete=True):
    client = w["client"]
    recording_id = client.post(
        "/api/v1/public/recorder/start", json={"round_id": round_id, "mime_type": "audio/webm"},
        headers=headers,
    ).json()["recording_id"]
    client.post(
        f"/api/v1/public/recorder/recordings/{recording_id}/chunks/0", content=w["blob"],
        headers={**headers, "Content-Type": "application/octet-stream",
                 "X-Chunk-SHA256": hashlib.sha256(w["blob"]).hexdigest()},
    )
    if complete:
        client.post(f"/api/v1/public/recorder/recordings/{recording_id}/complete",
                    json={"total_chunks": 1}, headers=headers)
    return recording_id


def _until(predicate, timeout=40.0, step=0.4):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    return predicate()


def _recording_state(recording_id):
    with session_scope() as session:
        return session.get(Recording, recording_id).state


def _analysed(container_id):
    """Every recording past analysis and the round summary in."""
    with session_scope() as session:
        assembly = session.get(Assembly, container_id)
        states = [r.state for r in session.execute(
            select(Recording).where(Recording.assembly_id == container_id)).scalars()]
        summarised = all(r.analysis_summary for r in assembly.rounds)
        jobs = session.execute(
            select(AppJob).where(AppJob.state.in_(("QUEUED", "RUNNING", "RETRY")))
        ).scalars().all()
        return bool(states) and all(s == "READY_FOR_REVIEW" for s in states) and summarised and not jobs


def _record_and_analyse(w, *, phones=1):
    joined, headers = _join(w["client"], w["made"]["recorder_url"])
    recording_id = _start(w, headers, joined["rounds"][0]["id"])
    assert _until(lambda: _analysed(w["container"])), "analysis never landed"
    return joined, headers, recording_id


def _age(container_id, **delta):
    with session_scope() as session:
        for recording in session.execute(
            select(Recording).where(Recording.assembly_id == container_id)
        ).scalars():
            moment = utcnow() - timedelta(**delta)
            recording.updated_at = moment
            if recording.ended_at is not None:
                recording.ended_at = moment


def _sweep(minutes=10, analysis=True, polis=False):
    return auto_organized.sweep_idle_close(
        utcnow(), minutes=minutes, analysis_on=analysis, polis_on=polis
    )


def _assembly(container_id):
    with session_scope() as session:
        row = session.get(Assembly, container_id)
        session.expunge(row)
        return row


def _findings(container_id):
    with session_scope() as session:
        rows = session.execute(select(Finding).where(Finding.assembly_id == container_id)).scalars().all()
        return [(f.status, f.reviewed_by, f.scope) for f in rows]


def _events(event):
    with session_scope() as session:
        return session.execute(select(AuditEvent).where(AuditEvent.event == event)).scalars().all()


def _job_errors():
    with session_scope() as session:
        return [(j.type, j.state, j.last_error) for j in session.execute(
            select(AppJob).where(AppJob.type.in_(("SEED_STATEMENTS", "PUSH_POLIS")))).scalars()]


def _jobs(kind):
    with session_scope() as session:
        return [j.state for j in session.execute(select(AppJob).where(AppJob.type == kind)).scalars()]


def test_one_phone_records_and_the_server_does_the_rest(world):
    w = world()
    client = w["client"]
    joined, headers, recording_id = _record_and_analyse(w)
    # a Record now container says so, and nothing is approved or closed yet
    assert client.get(f"/api/v1/assemblies/{w['container']}").json()["auto_organized"] is True
    state = client.get("/api/v1/public/recorder/status", headers=headers).json()
    assert state["assembly"]["auto_organized"] is True
    assert {s for s, _, _ in _findings(w["container"])} == {"DRAFT"}
    assert _sweep() == 0 and _assembly(w["container"]).closed_at is None
    # the recording ended just now: not silent long enough
    _age(w["container"], seconds=30)
    assert _sweep() == 0
    _age(w["container"], seconds=90)
    assert _sweep() == 1

    row = _assembly(w["container"])
    assert row.closed_at is not None and row.auto_finalized_at is not None
    assert row.report_published_at is not None and row.final_report_json
    findings = _findings(w["container"])
    assert findings and all(s == "APPROVED" and by == "system:auto" for s, by, _ in findings)
    assert {scope for _, _, scope in findings} == {"table", "round"}
    detail = client.get(f"/api/v1/assemblies/{w['container']}").json()
    assert detail["auto_finalized_at"] and detail["closed_at"]

    report = client.get("/api/v1/public/recorder/report", headers=headers)
    assert report.status_code == 200
    body = report.json()
    assert body["auto_generated"] is True and body["rounds"]
    assert "were not reviewed by a person" in body["methodology_note"]
    assert "reviewed by a human" not in body["methodology_note"]
    assert client.get("/api/v1/public/recorder/report.pdf", headers=headers).status_code == 200
    # once
    assert len(_events("session_auto_finalized")) == 1
    assert _sweep() == 0 and len(_events("session_auto_finalized")) == 1
    closed = _events("assembly_closed")
    assert closed and closed[-1].actor == "system"


def test_two_phones_close_only_when_both_are_quiet(world):
    w = world()
    client = w["client"]
    joined, headers_a = _join(client, w["made"]["recorder_url"])
    round_id = joined["rounds"][0]["id"]
    first = _start(w, headers_a, round_id)
    code = client.post("/api/v1/public/recorder/capabilities",
                       json={"purpose": "ADD_RECORDER_TO_TABLE"}, headers=headers_a)
    assert code.status_code == 201, code.text
    _, headers_b = _join(client, code.json()["url"])
    second = _start(w, headers_b, round_id, complete=False)
    assert _until(lambda: _recording_state(first) in ("TRANSCRIBED", "READY_FOR_REVIEW"))
    _age(w["container"], minutes=30)
    # one phone still records: silence is not total
    assert _sweep() == 0
    client.post(f"/api/v1/public/recorder/recordings/{second}/complete",
                json={"total_chunks": 1}, headers=headers_b)
    assert _until(lambda: _analysed(w["container"]))
    _age(w["container"], minutes=5)
    assert _sweep() == 0, "two phones joined: the ten minutes apply"
    _age(w["container"], minutes=11)
    assert _sweep(minutes=0) == 0, "0 means never"
    assert _assembly(w["container"]).closed_at is None
    assert _sweep(minutes=10) == 1
    assert _assembly(w["container"]).auto_finalized_at is not None


def test_the_account_closes_while_a_phone_records(world):
    w = world()
    client = w["client"]
    joined, headers = _join(client, w["made"]["recorder_url"])
    recording_id = _start(w, headers, joined["rounds"][0]["id"], complete=False)
    assert client.post(f"/api/v1/assemblies/{w['container']}/close").status_code == 200
    with session_scope() as session:
        recording = session.get(Recording, recording_id)
        assert recording.finish_requested_at is not None and recording.state == "RECORDING"
    reasons = [e.data_json for e in _events("recording_finish_requested")]
    assert any('"reason": "close"' in (r or "") for r in reasons)
    assert _assembly(w["container"]).auto_finalized_at is None
    # the phone does not answer: the server finishes it after the grace
    with session_scope() as session:
        session.get(Recording, recording_id).finish_requested_at = utcnow() - timedelta(
            seconds=rec_svc.FINISH_REQUEST_GRACE_SECONDS + 10)
    assert sweep.sweep_server_closes() == 1
    # the analysis lands after the close: the hook finalizes
    assert _until(lambda: _assembly(w["container"]).auto_finalized_at is not None), "never finalized"
    findings = _findings(w["container"])
    assert findings and all(s == "APPROVED" and by == "system:auto" for s, by, _ in findings)
    assert _sweep() == 0
    assert len(_events("session_auto_finalized")) == 1


def test_closing_after_the_analysis_finalizes_in_the_close(world):
    w = world()
    client = w["client"]
    _record_and_analyse(w)
    assert client.post(f"/api/v1/assemblies/{w['container']}/close").status_code == 200
    row = _assembly(w["container"])
    assert row.auto_finalized_at is not None and row.report_published_at is not None
    assert all(s == "APPROVED" for s, _, _ in _findings(w["container"]))


def test_with_the_analysis_off_the_sweep_publishes_the_transcript(world):
    w = world(analysis=False)
    client = w["client"]
    joined, headers = _join(client, w["made"]["recorder_url"])
    recording_id = _start(w, headers, joined["rounds"][0]["id"])
    assert _until(lambda: _recording_state(recording_id) == "TRANSCRIBED")
    _age(w["container"], minutes=2)
    assert _sweep(analysis=False) == 1

    def finalized():
        _sweep(analysis=False)
        return _assembly(w["container"]).auto_finalized_at is not None

    assert _until(finalized), "never finalized"
    row = _assembly(w["container"])
    assert row.report_published_at is not None
    report = client.get("/api/v1/public/recorder/report", headers=headers).json()
    assert report["auto_generated"] is True and report["rounds"]
    assert _findings(w["container"]) == []


def test_zero_retention_waits_for_the_automatic_approval(world):
    w = world()
    _record_and_analyse(w)
    with session_scope() as session:
        row = session.get(Assembly, w["container"])
        row.zero_retention = True
        # closed by hand in the database: no approval has happened yet
        row.closed_at = utcnow()
        row.status = "COMPLETE"
    with session_scope() as session:
        assert zero_retention.apply_if_ready(session, session.get(Assembly, w["container"])) is None
    assert zero_retention.sweep() == 0
    assert _assembly(w["container"]).zero_retention_done_at is None
    assert {s for s, _, _ in _findings(w["container"])} == {"DRAFT"}

    _sweep()
    assert _assembly(w["container"]).auto_finalized_at is not None
    assert _until(lambda: zero_retention.sweep() or _assembly(w["container"]).zero_retention_done_at)
    row = _assembly(w["container"])
    report = json.loads(row.final_report_json)

    def statuses(node):
        if isinstance(node, dict):
            if "is_draft" in node:
                yield node["status"]
            for value in node.values():
                yield from statuses(value)
        elif isinstance(node, list):
            for value in node:
                yield from statuses(value)

    kept = list(statuses(report))
    assert kept and set(kept) == {"APPROVED"}
    assert "were not reviewed by a person" in report["methodology_note"]
    assert zero_retention.retained_pdf_path(w["container"]).is_file()


def test_promoting_hands_the_session_to_a_person(world):
    w = world()
    client = w["client"]
    _record_and_analyse(w)
    promoted = client.post(f"/api/v1/sessions/{w['made']['session_id']}/promote", json={"name": "Our event"})
    assert promoted.status_code == 200, promoted.text
    assert client.get(f"/api/v1/assemblies/{w['container']}").json()["auto_organized"] is False
    promotion = _events("session_promoted")[-1]
    assert '"auto_organized": false' in promotion.data_json
    _age(w["container"], hours=3)
    assert _sweep() == 0
    assert _assembly(w["container"]).closed_at is None
    assert {s for s, _, _ in _findings(w["container"])} == {"DRAFT"}


def test_a_planned_independent_session_is_left_alone(world):
    w = world()
    client = w["client"]
    made = client.post("/api/v1/sessions", json={
        "question": "Where?", "recording_mode": "independent", "duration_minutes": 0,
    }).json()
    joined, headers = _join(client, made["invites"][0]["url"])
    _start(w, headers, joined["rounds"][0]["id"])
    assert _until(lambda: _analysed(made["container_id"]))
    assert client.get(f"/api/v1/assemblies/{made['container_id']}").json()["auto_organized"] is False
    _age(made["container_id"], hours=3)
    assert _sweep() == 0
    assert _assembly(made["container_id"]).closed_at is None
    assert {s for s, _, _ in _findings(made["container_id"])} == {"DRAFT"}


def test_migration_0044_round_trips(database):
    from citizens.db.session import sqlite_url as url_of

    cfg = Config()
    cfg.set_main_option("script_location", str(Path("citizens/db/migrations").resolve()))
    path = database.app_persistent_storage / "citizens.db"
    cfg.set_main_option("sqlalchemy.url", url_of(path))

    def columns():
        import sqlite3

        with sqlite3.connect(path) as db:
            return {row[1] for row in db.execute("PRAGMA table_info(assemblies)")}

    assert {"auto_organized", "auto_finalized_at"} <= columns()
    command.downgrade(cfg, "0043")
    assert not ({"auto_organized", "auto_finalized_at"} & columns())
    command.upgrade(cfg, "head")
    assert {"auto_organized", "auto_finalized_at"} <= columns()


def _statements(container_id):
    with session_scope() as session:
        return [(s.status, s.reviewed_by) for s in session.execute(
            select(StatementSeed).where(StatementSeed.assembly_id == container_id)).scalars()]


def test_polis_carries_the_statements_to_the_voting_link(world):
    w = world(polis=True)
    client = w["client"]
    joined, headers, _ = _record_and_analyse(w)
    _age(w["container"], minutes=2)
    assert _sweep(polis=True) == 1
    assert _until(lambda: _assembly(w["container"]).polis_published_at is not None, 60), (
        _jobs("SEED_STATEMENTS"), _jobs("PUSH_POLIS"), _job_errors()
    )
    row = _assembly(w["container"])
    seeds = _statements(w["container"])
    assert seeds and all(by == "system:auto" for _, by in seeds)
    assert all(status in ("APPROVED", "EXPORTED") for status, _ in seeds)
    assert len(w["pushes"]) == 1
    assert w["pushes"][0]["auth"] == "Bearer polis-secret-key"
    assert "not reviewed by a person" in w["pushes"][0]["body"]["description"]
    assert row.polis_url == "https://polis.example.org/conv1" and row.polis_conversation_id == "conv1"
    status = client.get("/api/v1/public/recorder/status", headers=headers).json()
    assert status["poll_url"] == "https://polis.example.org/conv1"
    assert status["report_available"] is True
    published = _events("polis_poll_published")
    assert published and published[-1].actor == "system"
    assert _jobs("SEED_STATEMENTS") == ["SUCCEEDED"] and _jobs("PUSH_POLIS") == ["SUCCEEDED"]


def test_without_polis_no_statements_are_made(world):
    w = world(polis=False)
    _record_and_analyse(w)
    _age(w["container"], minutes=2)
    assert _sweep(polis=False) == 1
    assert _assembly(w["container"]).auto_finalized_at is not None
    assert _jobs("SEED_STATEMENTS") == [] and _jobs("PUSH_POLIS") == []


def test_a_refused_push_leaves_the_report_published_and_no_link(world):
    w = world(polis=True, push_status=403)
    client = w["client"]
    joined, headers, _ = _record_and_analyse(w)
    _age(w["container"], minutes=2)
    assert _sweep(polis=True) == 1
    assert _until(lambda: _jobs("PUSH_POLIS") == ["FAILED"], 60), _jobs("PUSH_POLIS")
    row = _assembly(w["container"])
    assert row.report_published_at is not None and row.polis_published_at is None
    status = client.get("/api/v1/public/recorder/status", headers=headers).json()
    assert status["poll_url"] is None and status["report_available"] is True
    assert len(w["pushes"]) == 1
    assert client.get("/api/v1/public/recorder/report", headers=headers).status_code == 200


def test_the_organizer_still_approves_all_statements_by_hand(world):
    w = world(polis=False)
    client = w["client"]
    _record_and_analyse(w)
    client.post(f"/api/v1/assemblies/{w['container']}/close")
    # an organizer's own run, then approve-all as before. The route asks the
    # config snapshot, which may still hold a store from an earlier test for
    # up to 30 s: refresh it so it sees this world's analysis key.
    from citizens.services import provider_config

    provider_config.invalidate_snapshot()
    queued = client.post(f"/api/v1/assemblies/{w['container']}/seeds/generate", json={})
    assert queued.status_code in (200, 201, 202), queued.text
    assert _until(lambda: _jobs("SEED_STATEMENTS") == ["SUCCEEDED"])
    approved = client.post(f"/api/v1/assemblies/{w['container']}/seeds/approve-all")
    assert approved.status_code == 200 and approved.json()["approved"] >= 1
    assert all(by == "tester" for _, by in _statements(w["container"]))
    assert _events("seeds_approved_all")[-1].actor == "tester"
