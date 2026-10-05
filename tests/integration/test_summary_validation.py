# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Participants validate their table's published summary (0.7): only once the
report is out, one answer per person and session (the second replaces the
first), seen by the organizer as counts and notes beside the table, counted
in the report — never shown to other participants as notes."""

import re


def _assembly(client):
    created = client.post(
        "/api/v1/assemblies",
        json={"name": "TEST Validation", "default_table_count": 2,
              "rounds": [{"title": "R1", "question": "Q"}]},
    ).json()
    client.post(f"/api/v1/rounds/{created['rounds'][0]['id']}/start")
    return created


def _own_phone(client, assembly, table_index, ip):
    token = re.search(r"#/join/(.+)$", assembly["invites"][table_index]["url"]).group(1)
    joined = client.post("/api/v1/public/join", json={"token": token},
                         headers={"X-Forwarded-For": ip}).json()
    table_headers = {"Authorization": f"Bearer {joined['session_token']}"}
    card = client.post("/api/v1/public/recorder/capabilities",
                       json={"purpose": "REGISTER_PARTICIPANT"}, headers=table_headers).json()
    rtoken = re.search(r"#/register/(.+)$", card["url"]).group(1)
    notice = client.post("/api/v1/public/register/notice", json={"token": rtoken},
                         headers={"X-Forwarded-For": ip}).json()
    registered = client.post("/api/v1/public/register", json={
        "token": rtoken, "name": f"Person {ip}", "notice_hash": notice["hash"], "notice_read": True,
        "recording_consent": True, "transcription_consent": True, "analysis_consent": True,
        "publication_consent": True,
    }, headers={"X-Forwarded-For": ip}).json()
    return {"Authorization": f"Bearer {registered['participant_token']}"}


def test_a_participant_validates_the_table_summary_once_the_report_is_out(client):
    assembly = _assembly(client)
    round_id = assembly["rounds"][0]["id"]
    anna = _own_phone(client, assembly, 1, "10.12.0.1")
    bruno = _own_phone(client, assembly, 1, "10.12.0.2")

    status = client.get("/api/v1/public/participant/status", headers=anna).json()
    assert status["rounds"] == [{"id": round_id, "position": 1, "title": "R1", "status": "ACTIVE",
                                 "table_number": 2}]
    assert status["validations"] == {}
    # not before the report is published
    early = client.post("/api/v1/public/participant/validate",
                        json={"round_id": round_id, "verdict": "LOOKS_RIGHT"}, headers=anna)
    assert early.status_code == 409

    client.post(f"/api/v1/assemblies/{assembly['id']}/report/publish")
    ok = client.post("/api/v1/public/participant/validate",
                     json={"round_id": round_id, "verdict": "LOOKS_RIGHT"}, headers=anna)
    assert ok.status_code == 200, ok.text
    flagged = client.post("/api/v1/public/participant/validate",
                          json={"round_id": round_id, "verdict": "MISSING",
                                "note": "We also talked about the bus"}, headers=bruno)
    assert flagged.status_code == 200
    # a second answer replaces the first, it does not add
    client.post("/api/v1/public/participant/validate",
                json={"round_id": round_id, "verdict": "MISSING", "note": "Changed my mind"},
                headers=anna)
    assert client.get("/api/v1/public/participant/status", headers=anna).json()["validations"] == {
        round_id: {"verdict": "MISSING", "note": "Changed my mind"},
    }

    # the organizer sees counts and notes beside table 2; participants only counts
    organizer = client.get(f"/api/v1/assemblies/{assembly['id']}/report?include_drafts=true").json()
    table2 = next(t for t in organizer["rounds"][0]["tables"] if t["table_number"] == 2)
    assert (table2["validations"]["looks_right"], table2["validations"]["missing"]) == (0, 2)
    assert sorted(table2["validations"]["notes"]) == ["Changed my mind", "We also talked about the bus"]
    assert "2 participants said whether their table's summary" in organizer["methodology_note"]
    published = client.get("/api/v1/public/participant/report", headers=anna).json()
    table2_public = next(t for t in published["rounds"][0]["tables"] if t["table_number"] == 2)
    assert table2_public["validations"] == {"looks_right": 0, "missing": 2}
    # a table nobody answered for is not listed at all (it has no content)
    assert all(t["table_number"] != 1 for t in published["rounds"][0]["tables"])

    # a session of another assembly is not ours to judge
    other = _assembly(client)
    assert client.post("/api/v1/public/participant/validate",
                       json={"round_id": other["rounds"][0]["id"], "verdict": "LOOKS_RIGHT"},
                       headers=anna).status_code == 404
