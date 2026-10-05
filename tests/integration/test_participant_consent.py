# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Individual consent at the table (0.7): a person registers on the table's
phone against the notice the server rendered, the record is stored as given
with the notice hash, a required assembly records only once someone at the
table consents, an optional one never blocks, the organizer's list and the
export carry the record, and nothing crosses tables or events."""

import io
import json
import re
import zipfile

from sqlalchemy import select

from citizens.db.models import AuditEvent, ConsentNotice, ParticipantConsent
from citizens.db.session import session_scope


def _assembly(client, consent="required", tables=2, name="TEST Consent"):
    created = client.post(
        "/api/v1/assemblies",
        json={
            "name": name,
            "default_table_count": tables,
            "participant_consent": consent,
            "rounds": [{"title": "R1", "question": "Q"}, {"title": "R2", "question": "Q"}],
        },
    ).json()
    client.post(f"/api/v1/rounds/{created['rounds'][0]['id']}/start")
    return created


def _phone(client, assembly, index, ip):
    token = re.search(r"#/join/(.+)$", assembly["invites"][index]["url"]).group(1)
    joined = client.post(
        "/api/v1/public/join", json={"token": token}, headers={"X-Forwarded-For": ip}
    ).json()
    return {"Authorization": f"Bearer {joined['session_token']}"}


def _notice(client, headers):
    response = client.get("/api/v1/public/recorder/consent-notice", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _register(client, headers, name, notice_hash, **ticks):
    body = {
        "name": name, "notice_hash": notice_hash, "notice_read": True,
        "recording_consent": True, "transcription_consent": True, "analysis_consent": True,
        "publication_consent": False, **ticks,
    }
    return client.post("/api/v1/public/recorder/participants", json=body, headers=headers)


def _start(client, headers, round_id):
    return client.post(
        "/api/v1/public/recorder/start",
        json={"round_id": round_id, "mime_type": "audio/webm"},
        headers=headers,
    )


def test_registration_is_stored_as_given_with_the_notice_and_seats_the_person(client):
    assembly = _assembly(client)
    assert assembly["participant_consent"] == "required"
    round1 = assembly["rounds"][0]["id"]
    table1 = _phone(client, assembly, 0, "10.9.0.1")

    notice = _notice(client, table1)
    assert notice["mode"] == "required" and notice["participants"] == []
    assert notice["version"] and len(notice["hash"]) == 64
    assert any("responsible for your data" in p for p in notice["paragraphs"])
    assert notice["acceptance"] == notice["paragraphs"][-1]

    # a required assembly: no consenting person, no recording — and the Live
    # tab says so before anyone tries
    blocked = _start(client, table1, round1)
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["detail"]["code"] == "PARTICIPANT_CONSENT_REQUIRED"
    monitor = client.get(f"/api/v1/rounds/{round1}/monitor").json()
    row = next(t for t in monitor["tables"] if t["number"] == 1)
    assert row["consent"] == {"mode": "required", "registered": 0, "consenting": 0, "can_record": False}
    assert row["readiness"]["status"] == "BLOCKED"
    assert any(r["code"] == "PARTICIPANT_CONSENT_MISSING" for r in row["readiness"]["reasons"])
    assert client.get("/api/v1/public/recorder/status", headers=table1).json()["consent"] == {
        "mode": "required", "registered": 0, "consenting": 0, "can_record": False,
    }

    # one person refuses: a record, not a right to record
    refused = _register(client, table1, "Anna", notice["hash"], recording_consent=False,
                        transcription_consent=False, analysis_consent=False, email="anna@example.org")
    assert refused.status_code == 201, refused.text
    assert refused.json()["can_record"] is False
    assert refused.json()["table"]["registered"] == 1 and refused.json()["table"]["consenting"] == 0
    assert _start(client, table1, round1).status_code == 409

    # one person consents: the table may record
    agreed = _register(client, table1, "  Bruno ", notice["hash"])
    assert agreed.status_code == 201, agreed.text
    body = agreed.json()
    assert body["participant"]["name"] == "Bruno" and body["participant"]["label"] == "P002"
    assert body["consent"]["method"] == "TABLE_DEVICE"
    assert body["consent"]["notice_hash"] == notice["hash"]
    assert body["can_record"] is True and body["table"]["can_record"] is True
    roster = _notice(client, table1)["participants"]
    assert roster == [
        {"label": "P001", "name": "Anna", "recording_consent": False},
        {"label": "P002", "name": "Bruno", "recording_consent": True},
    ]
    assert _start(client, table1, round1).status_code == 201
    row = next(
        t for t in client.get(f"/api/v1/rounds/{round1}/monitor").json()["tables"] if t["number"] == 1
    )
    assert row["consent"]["consenting"] == 1 and row["consent"]["can_record"] is True
    assert not any(r["code"] == "PARTICIPANT_CONSENT_MISSING" for r in row["readiness"]["reasons"])
    # the report documents the basis it rests on
    note = client.get(f"/api/v1/assemblies/{assembly['id']}/report").json()["methodology_note"]
    assert "2 participants registered individually at the tables" in note
    assert "1 consented to being recorded" in note

    # the organizer's list shows the record; email stays off the phone's roster
    listed = client.get(f"/api/v1/assemblies/{assembly['id']}/participants").json()
    anna = next(p for p in listed if p["name"] == "Anna")
    assert anna["source"] == "TABLE_DEVICE" and anna["registered_table_number"] == 1
    assert anna["email"] == "anna@example.org"
    assert (anna["consent"]["recording"], anna["consent"]["notice_version"]) == (False, notice["version"])
    bruno = next(p for p in listed if p["name"] == "Bruno")
    assert bruno["consent"]["recording"] is True and bruno["consent"]["notice_read"] is True
    # ...and both are seated at table 1 for the round being set up
    tables = client.get(f"/api/v1/rounds/{round1}/tables").json()
    seated = next(t for t in tables if t["number"] == 1)
    assert sorted(p["name"] for p in seated["participants"]) == ["Anna", "Bruno"]

    with session_scope() as session:
        stored = session.execute(select(ConsentNotice)).scalars().all()
        assert [n.hash for n in stored] == [notice["hash"]]
        assert stored[0].text == "\n".join(notice["paragraphs"])
        acts = session.execute(select(ParticipantConsent)).scalars().all()
        assert len(acts) == 2 and all(a.table_number == 1 for a in acts)
        audit = session.execute(
            select(AuditEvent).where(AuditEvent.event == "participant_registered")
        ).scalars().all()
        assert len(audit) == 2
        assert "Anna" not in (audit[0].data_json or "") and "anna@" not in (audit[0].data_json or "")


def test_a_stale_notice_is_refused_and_a_name_is_required(client):
    assembly = _assembly(client)
    table1 = _phone(client, assembly, 0, "10.9.1.1")
    notice = _notice(client, table1)
    stale = _register(client, table1, "Carla", "0" * 64)
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "NOTICE_CHANGED"
    assert _register(client, table1, "   ", notice["hash"]).status_code == 422


def test_optional_mode_never_blocks_and_each_table_has_its_own_roster(client):
    assembly = _assembly(client, consent="optional")
    round1 = assembly["rounds"][0]["id"]
    table1 = _phone(client, assembly, 0, "10.9.2.1")
    table2 = _phone(client, assembly, 1, "10.9.2.2")
    assert _notice(client, table1)["mode"] == "optional"
    assert _start(client, table1, round1).status_code == 201
    notice = _notice(client, table2)
    assert _register(client, table2, "Dario", notice["hash"]).status_code == 201
    assert [p["name"] for p in _notice(client, table2)["participants"]] == ["Dario"]
    assert _notice(client, table1)["participants"] == []
    status = client.get("/api/v1/public/recorder/status", headers=table2).json()["consent"]
    assert status == {"mode": "optional", "registered": 1, "consenting": 1, "can_record": True}


def test_a_session_is_optional_and_the_rule_can_be_changed(client):
    session_ = client.post(
        "/api/v1/sessions", json={"question": "Q", "recording_mode": "independent"}
    ).json()
    container = client.get(f"/api/v1/assemblies/{session_['container_id']}").json()
    assert container["participant_consent"] == "optional"
    changed = client.put(
        f"/api/v1/assemblies/{session_['container_id']}", json={"participant_consent": "required"}
    )
    assert changed.status_code == 200 and changed.json()["participant_consent"] == "required"


def test_the_export_carries_the_record_and_the_notice_text(client):
    assembly = _assembly(client, consent="optional")
    table1 = _phone(client, assembly, 0, "10.9.3.1")
    notice = _notice(client, table1)
    _register(client, table1, "Elena", notice["hash"], email="e@example.org")
    response = client.get(f"/api/v1/assemblies/{assembly['id']}/export.zip")
    assert response.status_code == 200, response.text
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["format_version"] == 2
    elena = next(p for p in manifest["participants"] if p["name"] == "Elena")
    assert elena["email"] == "e@example.org" and elena["source"] == "TABLE_DEVICE"
    assert elena["consent"]["notice_hash"] == notice["hash"]
    assert elena["consent"]["recording"] is True and elena["consent"]["method"] == "TABLE_DEVICE"
    assert archive.read(f"consent-notices/{notice['hash']}.txt").decode() == "\n".join(notice["paragraphs"])


def test_the_consent_register_exports_what_was_signed(client):
    assembly = _assembly(client, consent="optional")
    table1 = _phone(client, assembly, 0, "10.9.5.1")
    notice = _notice(client, table1)
    _register(client, table1, "Gaia", notice["hash"], email="g@example.org")
    _register(client, table1, "Hugo", notice["hash"], recording_consent=False,
              transcription_consent=False, analysis_consent=False)
    client.post(f"/api/v1/assemblies/{assembly['id']}/participants",
                json={"participants": [{"label": "P900", "name": "From the list"}]})

    csv_body = client.get(f"/api/v1/assemblies/{assembly['id']}/consent-register.csv")
    assert csv_body.status_code == 200 and csv_body.headers["content-type"].startswith("text/csv")
    lines = csv_body.text.strip().splitlines()
    assert lines[0].startswith("label,name,email,source,table,method,notice_version,notice_hash,recording")
    assert len(lines) == 3  # two records; the list-only person signed nothing
    gaia = next(line for line in lines if "Gaia" in line)
    assert "Gaia,g@example.org,TABLE_DEVICE,1,TABLE_DEVICE" in gaia and ",yes,yes,yes," in gaia
    assert any("Hugo" in line and ",no,no,no,no," in line for line in lines)
    assert notice["hash"] in csv_body.text

    pdf = client.get(f"/api/v1/assemblies/{assembly['id']}/consent-register.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    # somebody else's register is not ours to read
    assert client.get(f"/api/v1/assemblies/{assembly['id']}/consent-register.csv",
                      headers={"X-Test-User": "someone-else"}).status_code == 404


def test_deleting_the_person_erases_the_record(client):
    assembly = _assembly(client, consent="optional")
    table1 = _phone(client, assembly, 0, "10.9.4.1")
    notice = _notice(client, table1)
    created = _register(client, table1, "Fabio", notice["hash"]).json()
    assert client.delete(f"/api/v1/participants/{created['participant']['id']}").status_code == 204
    with session_scope() as session:
        assert session.execute(select(ParticipantConsent)).scalars().all() == []
    assert _notice(client, table1)["participants"] == []
