# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Record now, polished (0.7): no planned time (R12), another session from
the phone (R13), a spent code scanned again by the same phone (R14), and a
title from what was said (R16)."""

import re

from sqlalchemy import select

from citizens.db.models import Assembly, AuditEvent, RecorderSession, Round
from citizens.db.session import session_scope
from citizens.services import analysis


def _join(client, url, ip="10.9.0.1", device_id=None):
    token = re.search(r"#/join/(.+)$", url).group(1)
    body = {"token": token}
    if device_id:
        body["device_id"] = device_id
    return client.post("/api/v1/public/join", json=body, headers={"X-Forwarded-For": ip})


def _auth(joined):
    return {"Authorization": f"Bearer {joined['session_token']}"}


def test_record_now_has_no_planned_time(client):
    made = client.post("/api/v1/sessions/record-now", json={"language": "it"}).json()
    detail = client.get(f"/api/v1/sessions/{made['session_id']}").json()
    assert detail["duration_minutes"] == 0
    joined = _join(client, made["recorder_url"]).json()
    assert joined["rounds"][0]["duration_minutes"] == 0
    # a planned Session may still say 0 — and the old floor of one minute is gone
    planned = client.post("/api/v1/sessions", json={"question": "Q", "duration_minutes": 0})
    assert planned.status_code == 201, planned.text
    assert client.put(f"/api/v1/rounds/{planned.json()['session_id']}",
                      json={"duration_minutes": 0}).status_code == 200


def test_the_phone_records_another_session_like_this_one(client):
    made = client.post("/api/v1/sessions/record-now", json={"language": "it"}).json()
    joined = _join(client, made["recorder_url"]).json()
    headers = _auth(joined)
    another = client.post("/api/v1/public/recorder/sessions",
                          json={"round_id": made["session_id"]}, headers=headers)
    assert another.status_code == 201, another.text
    body = another.json()
    assert body["session_id"] != made["session_id"] and body["recorder_url"]
    new = client.get(f"/api/v1/assemblies/{body['container_id']}").json()
    assert new["kind"] == "session" and new["language"] == "it" and new["language_auto"] is True
    assert new["recording_mode"] == "independent"
    assert client.get(f"/api/v1/sessions/{body['session_id']}").json()["duration_minutes"] == 0
    # the new link joins the new table: a different session, table 1 again
    second = _join(client, body["recorder_url"], ip="10.9.0.2")
    assert second.status_code == 200 and second.json()["assembly"]["id"] == body["container_id"]
    # a round of another assembly is not this phone's to follow
    other = client.post("/api/v1/sessions/record-now", json={}).json()
    refused = client.post("/api/v1/public/recorder/sessions",
                          json={"round_id": other["session_id"]}, headers=headers)
    assert refused.status_code == 404


def test_an_orchestrated_assembly_cannot_be_followed_from_a_phone(client):
    assembly = client.post(
        "/api/v1/assemblies",
        json={"name": "TEST Org", "default_table_count": 1,
              "rounds": [{"title": "R1", "question": "Q?", "duration_minutes": 30}]},
    ).json()
    joined = _join(client, assembly["invites"][0]["url"]).json()
    refused = client.post("/api/v1/public/recorder/sessions",
                          json={"round_id": assembly["rounds"][0]["id"]}, headers=_auth(joined))
    assert refused.status_code == 409


def test_a_spent_code_scanned_again_by_the_same_phone_resumes_its_session(client):
    assembly = client.post(
        "/api/v1/assemblies",
        json={"name": "TEST Resume", "default_table_count": 1,
              "rounds": [{"title": "R1", "question": "Q?", "duration_minutes": 30}]},
    ).json()
    phone_a = _join(client, assembly["invites"][0]["url"]).json()
    card = client.post("/api/v1/public/recorder/capabilities",
                       json={"purpose": "ADD_RECORDER_TO_TABLE"}, headers=_auth(phone_a)).json()
    first = _join(client, card["url"], ip="10.9.0.3", device_id="phone-b-0123456789")
    assert first.status_code == 200, first.text
    # the same phone, its storage gone: back in, with a fresh bearer
    again = _join(client, card["url"], ip="10.9.0.3", device_id="phone-b-0123456789")
    assert again.status_code == 200, again.text
    assert again.json()["session_token"] != first.json()["session_token"]
    assert again.json()["joined"]["slot"] == first.json()["joined"]["slot"] == 2
    ok = client.get("/api/v1/public/recorder/status", headers=_auth(again.json()))
    assert ok.status_code == 200 and ok.json()["slot"] == 2
    # the old bearer is gone with the rotation
    assert client.get("/api/v1/public/recorder/status", headers=_auth(first.json())).status_code == 401
    with session_scope() as session:
        sessions = session.execute(
            select(RecorderSession).where(RecorderSession.device_id == "phone-b-0123456789")
        ).scalars().all()
        assert len(sessions) == 1
        assert session.execute(
            select(AuditEvent.event).where(AuditEvent.event == "capability_resumed")
        ).scalars().all() == ["capability_resumed"]
    # any other phone — or one that says nothing about itself — still gets the 410
    assert _join(client, card["url"], ip="10.9.0.4", device_id="phone-c-0123456789").status_code == 410
    assert _join(client, card["url"], ip="10.9.0.5").status_code == 410
    # a malformed id is refused before anything is read
    assert _join(client, card["url"], ip="10.9.0.6", device_id="x y").status_code == 422


def test_the_table_code_remembers_the_phone_too(client):
    assembly = client.post(
        "/api/v1/assemblies",
        json={"name": "TEST Table", "default_table_count": 1,
              "rounds": [{"title": "R1", "question": "Q?", "duration_minutes": 30}]},
    ).json()
    joined = _join(client, assembly["invites"][0]["url"], device_id="phone-a-0123456789").json()
    with session_scope() as session:
        row = session.execute(
            select(RecorderSession).where(RecorderSession.device_id == "phone-a-0123456789")
        ).scalar_one()
        assert row.assembly_id == assembly["id"] and joined["slot"] == 1


def test_the_model_names_a_record_now_session_once(client, monkeypatch):
    made = client.post("/api/v1/sessions/record-now", json={}).json()
    # the analysis provider runs in JSON mode, so the usual answer is an object
    answers = iter(['{"title": "Parcheggi nel centro storico."}', "Should not be used"])
    monkeypatch.setattr(analysis, "_chat", lambda *args: next(answers))
    with session_scope() as session:
        container = session.get(Assembly, made["container_id"])
        round_ = session.get(Round, made["session_id"])
        assert container.name.startswith("Recording ")
        analysis._name_record_now_session(
            session, "https://llm.test", "k", "m", container, round_, "People discussed parking.", "Italian"
        )
        assert round_.title == "Parcheggi nel centro storico"
        assert container.name == "Parcheggi nel centro storico"
        # once: a named session keeps its name
        analysis._name_record_now_session(
            session, "https://llm.test", "k", "m", container, round_, "More talk.", "Italian"
        )
        assert container.name == "Parcheggi nel centro storico"
    shown = client.get(f"/api/v1/assemblies/{made['container_id']}").json()
    assert shown["name"] == "Parcheggi nel centro storico"


def test_the_title_parser_takes_json_or_text_and_refuses_the_rest():
    parse = analysis._title_from_answer
    assert parse('{"title": "Parcheggi nel centro storico."}') == "Parcheggi nel centro storico"
    assert parse('"Bike lanes downtown"') == "Bike lanes downtown"
    assert parse("  Mobilità   dolce.  ") == "Mobilità dolce"
    assert parse('{"name": "x"}') == ""
    assert parse("{not json") == ""
    assert parse('{"title": {"x": 1}}') == ""
    assert parse("") == ""


def test_a_record_now_report_has_no_session_heading_and_says_its_kind(client):
    from citizens.services.report import build_report

    made = client.post("/api/v1/sessions/record-now", json={}).json()
    with session_scope() as session:
        report = build_report(session, session.get(Assembly, made["container_id"]))
    assert report["assembly"]["kind"] == "session" and report["assembly"]["tables"] == 1
    assert report["rounds"][0]["heading"] == ""
    assert "reviewed by a human" not in report["methodology_note"]


def test_a_planned_session_keeps_the_name_it_was_given(client, monkeypatch):
    made = client.post("/api/v1/sessions", json={"question": "Where should the bike lanes go?"}).json()
    monkeypatch.setattr(analysis, "_chat", lambda *args: "Bike lanes")
    with session_scope() as session:
        container = session.get(Assembly, made["container_id"])
        round_ = session.get(Round, made["session_id"])
        analysis._name_record_now_session(
            session, "https://llm.test", "k", "m", container, round_, "Bikes.", "English"
        )
        assert round_.title == "" and container.name == "Where should the bike lanes go?"
