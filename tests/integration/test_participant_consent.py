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
    assert notice["acceptance"] == notice["paragraphs"][-2]
    assert notice["acceptance_quotations"] == notice["paragraphs"][-1]

    # a required assembly: no consenting person, no recording — and the Live
    # tab says so before anyone tries
    blocked = _start(client, table1, round1)
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["detail"]["code"] == "PARTICIPANT_CONSENT_REQUIRED"
    monitor = client.get(f"/api/v1/rounds/{round1}/monitor").json()
    row = next(t for t in monitor["tables"] if t["number"] == 1)
    assert row["consent"] == {
        "mode": "required", "registered": 0, "consenting": 0, "refusing": 0, "can_record": False,
    }
    assert row["readiness"]["status"] == "BLOCKED"
    assert any(r["code"] == "PARTICIPANT_CONSENT_MISSING" for r in row["readiness"]["reasons"])
    assert client.get("/api/v1/public/recorder/status", headers=table1).json()["consent"] == {
        "mode": "required", "registered": 0, "consenting": 0, "refusing": 0, "can_record": False,
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
    # Bruno consents, but Anna, who refused, is still seated here: the table
    # waits until she is marked as moved to a table that is not recorded
    assert body["can_record"] is True and body["table"]["can_record"] is False
    assert body["table"]["consenting"] == 1 and body["table"]["refusing"] == 1
    roster = _notice(client, table1)["participants"]
    assert [(p["label"], p["name"], p["recording_consent"], p["refused"]) for p in roster] == [
        ("P001", "Anna", False, True),
        ("P002", "Bruno", True, False),
    ]
    assert _start(client, table1, round1).status_code == 409
    moved = client.post(
        f"/api/v1/public/recorder/participants/{refused.json()['participant']['id']}/moved",
        headers=table1,
    )
    assert moved.status_code == 200, moved.text
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
    # Anna was marked as moved above: her record stays, her seat is gone
    assert anna["source"] == "TABLE_DEVICE" and anna["registered_table_number"] is None
    assert anna["email"] == "anna@example.org"
    assert (anna["consent"]["recording"], anna["consent"]["notice_version"]) == (False, notice["version"])
    bruno = next(p for p in listed if p["name"] == "Bruno")
    assert bruno["consent"]["recording"] is True and bruno["consent"]["notice_read"] is True
    # ...and Bruno is seated at table 1 for the round being set up; Anna is not
    tables = client.get(f"/api/v1/rounds/{round1}/tables").json()
    seated = next(t for t in tables if t["number"] == 1)
    assert sorted(p["name"] for p in seated["participants"]) == ["Bruno"]

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
    assert status == {"mode": "optional", "registered": 1, "consenting": 1, "refusing": 0, "can_record": True}


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


# ---------------------------------------------------------------- refusals (0.7.0-alpha.1 stabilisation)

def _monitor_table(client, round_id, number):
    monitor = client.get(f"/api/v1/rounds/{round_id}/monitor").json()
    return next(t for t in monitor["tables"] if t["number"] == number)


def _reasons(table):
    return [r["code"] for r in table["readiness"]["reasons"]]


def test_a_refusal_blocks_the_table_until_the_person_is_marked_as_moved(client):
    """One consent is not enough when someone seated at the table refused:
    the server refuses to start with PARTICIPANT_REFUSED, the Live tab shows
    the blocker, and the table records only once the person is marked as
    moved — the room's procedure: a table that is not recorded."""
    assembly = _assembly(client)
    round1 = assembly["rounds"][0]["id"]
    table1 = _phone(client, assembly, 0, "10.40.0.1")
    notice = _notice(client, table1)
    assert notice["version"] == "2026-10.3"
    assert "quotations" in notice["acceptance_quotations"]
    assert "quotations" not in notice["acceptance"]
    assert any("not recorded" in p for p in notice["paragraphs"])

    _register(client, table1, "Anna", notice["hash"]).json()
    refused = _register(client, table1, "Bruno", notice["hash"],
                        recording_consent=False, transcription_consent=False,
                        analysis_consent=False, publication_consent=False).json()
    assert refused["table"] == {
        "mode": "required", "registered": 2, "consenting": 1, "refusing": 1, "can_record": False,
    }
    roster = _notice(client, table1)["participants"]
    assert [(p["name"], p["recording_consent"], p["refused"]) for p in roster] == [
        ("Anna", True, False), ("Bruno", False, True),
    ]

    started = _start(client, table1, round1)
    assert started.status_code == 409, started.text
    assert started.json()["detail"]["code"] == "PARTICIPANT_REFUSED"
    table = _monitor_table(client, round1, 1)
    assert table["readiness"]["status"] == "BLOCKED"
    assert "PARTICIPANT_REFUSED" in _reasons(table)
    assert table["consent"]["refusing"] == 1

    moved = client.post(
        f"/api/v1/public/recorder/participants/{refused['participant']['id']}/moved", headers=table1
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["table"]["refusing"] == 0 and moved.json()["table"]["can_record"] is True
    assert [p["name"] for p in _notice(client, table1)["participants"]] == ["Anna"]
    assert _start(client, table1, round1).status_code == 201
    table = _monitor_table(client, round1, 1)
    assert "PARTICIPANT_REFUSED" not in _reasons(table)

    # Bruno can be seated by name at another table, as a pre-registered person
    with session_scope() as session:
        events = [e.event for e in session.execute(select(AuditEvent)).scalars()]
    assert "participant_moved" in events


def test_a_person_who_changed_their_mind_lifts_the_block_and_the_register_keeps_both_acts(client):
    assembly = _assembly(client)
    round1 = assembly["rounds"][0]["id"]
    table1 = _phone(client, assembly, 0, "10.40.0.2")
    notice = _notice(client, table1)
    _register(client, table1, "Anna", notice["hash"])
    bruno = _register(client, table1, "Bruno", notice["hash"],
                      recording_consent=False, transcription_consent=False,
                      analysis_consent=False, publication_consent=False).json()
    assert _start(client, table1, round1).status_code == 409

    changed = client.post(
        f"/api/v1/public/recorder/participants/{bruno['participant']['id']}/consent", headers=table1,
        json={"notice_hash": notice["hash"], "notice_read": True, "recording_consent": True,
              "transcription_consent": True, "analysis_consent": True, "publication_consent": False},
    )
    assert changed.status_code == 201, changed.text
    assert changed.json()["table"]["consenting"] == 2 and changed.json()["table"]["refusing"] == 0
    assert _start(client, table1, round1).status_code == 201

    # a stale notice is refused here too
    stale = client.post(
        f"/api/v1/public/recorder/participants/{bruno['participant']['id']}/consent", headers=table1,
        json={"notice_hash": "0" * 64, "recording_consent": True},
    )
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "NOTICE_CHANGED"

    # the organizer's list shows the newest act; the register lists both
    people = client.get(f"/api/v1/assemblies/{assembly['id']}/participants").json()
    assert next(p for p in people if p["name"] == "Bruno")["consent"]["recording"] is True
    csv_body = client.get(f"/api/v1/assemblies/{assembly['id']}/consent-register.csv").text
    bruno_rows = [line for line in csv_body.splitlines() if ",Bruno," in line]
    assert len(bruno_rows) == 2
    assert ",no,no,no,no," in bruno_rows[0] and ",yes,yes,yes,no," in bruno_rows[1]
    with session_scope() as session:
        events = [e.event for e in session.execute(select(AuditEvent)).scalars()]
    assert events.count("consent_changed") == 1


def test_a_withdrawal_mid_recording_blocks_the_table_but_keeps_what_was_recorded(client):
    assembly = _assembly(client)
    round1 = assembly["rounds"][0]["id"]
    table1 = _phone(client, assembly, 0, "10.40.0.3")
    notice = _notice(client, table1)
    anna = _register(client, table1, "Anna", notice["hash"]).json()
    started = _start(client, table1, round1)
    assert started.status_code == 201

    withdrawn = client.post(
        f"/api/v1/public/recorder/participants/{anna['participant']['id']}/consent", headers=table1,
        json={"notice_hash": notice["hash"], "notice_read": True},
    )
    assert withdrawn.status_code == 201, withdrawn.text
    assert withdrawn.json()["table"] == {
        "mode": "required", "registered": 1, "consenting": 0, "refusing": 1, "can_record": False,
    }
    table = _monitor_table(client, round1, 1)
    assert table["readiness"]["status"] == "BLOCKED"
    assert "PARTICIPANT_REFUSED" in _reasons(table)
    # the recording already made is untouched: still in progress, nothing deleted
    assert table["recording"]["state"] == "RECORDING"
    status = client.get("/api/v1/public/recorder/status", headers=table1).json()
    assert status["consent"]["can_record"] is False


def test_a_phone_acts_only_on_its_own_tables_people_and_the_organizer_on_anyone(client):
    assembly = _assembly(client)
    table1 = _phone(client, assembly, 0, "10.40.0.4")
    table2 = _phone(client, assembly, 1, "10.40.0.5")
    notice = _notice(client, table1)
    bruno = _register(client, table1, "Bruno", notice["hash"], recording_consent=False).json()
    pid = bruno["participant"]["id"]
    assert client.post(f"/api/v1/public/recorder/participants/{pid}/moved", headers=table2).status_code == 404
    assert client.post(
        f"/api/v1/public/recorder/participants/{pid}/consent", headers=table2,
        json={"notice_hash": notice["hash"], "recording_consent": True},
    ).status_code == 404

    changed = client.post(
        f"/api/v1/assemblies/{assembly['id']}/participants/{pid}/consent",
        json={"recording_consent": True, "transcription_consent": True, "analysis_consent": True,
              "publication_consent": True},
    )
    assert changed.status_code == 201, changed.text
    assert changed.json()["consent"]["method"] == "ORGANIZER"
    moved = client.post(f"/api/v1/assemblies/{assembly['id']}/participants/{pid}/moved")
    assert moved.status_code == 200, moved.text
    people = client.get(f"/api/v1/assemblies/{assembly['id']}/participants").json()
    assert next(p for p in people if p["id"] == pid)["registered_table_number"] is None

    # closed: no further acts
    client.post(f"/api/v1/assemblies/{assembly['id']}/close")
    assert client.post(
        f"/api/v1/assemblies/{assembly['id']}/participants/{pid}/consent", json={"recording_consent": True}
    ).status_code == 409


def test_the_seat_of_the_session_decides_which_table_a_refusal_blocks(client):
    """New seating moves people between sessions: a refusal blocks the table
    the person sits at in THIS session, not the one they registered at."""
    assembly = _assembly(client)
    round1, round2 = (r["id"] for r in assembly["rounds"])
    table1 = _phone(client, assembly, 0, "10.40.0.6")
    table2 = _phone(client, assembly, 1, "10.40.0.7")
    notice = _notice(client, table1)
    _register(client, table1, "Anna", notice["hash"])
    bruno = _register(client, table1, "Bruno", notice["hash"], recording_consent=False).json()
    _register(client, table2, "Carla", _notice(client, table2)["hash"])
    pid = bruno["participant"]["id"]
    # the organizer seats Bruno at table 2 for session 2 (the seating plan)
    with session_scope() as session:
        from citizens.db.models import Round, TableAssignment
        r2 = session.get(Round, round2)
        t2 = next(t for t in r2.tables if t.number == 2)
        session.add(TableAssignment(round_id=round2, table_id=t2.id, participant_id=pid))
    monitor2 = client.get(f"/api/v1/rounds/{round2}/monitor").json()
    by_number = {t["number"]: t for t in monitor2["tables"]}
    assert by_number[2]["consent"]["refusing"] == 1 and by_number[1]["consent"]["refusing"] == 0
    monitor1 = client.get(f"/api/v1/rounds/{round1}/monitor").json()
    assert next(t for t in monitor1["tables"] if t["number"] == 1)["consent"]["refusing"] == 1
