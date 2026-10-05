# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Registration on the participant's own phone (0.7): the table's phone makes
a REGISTER_PARTICIPANT code, a person scans it, reads the notice, registers —
the table is known from the code — and keeps a page that shows where they
are, their consent, and the report once it is published. The code never
makes a recorder; nothing crosses events."""

import re


def _assembly(client, consent="required"):
    created = client.post(
        "/api/v1/assemblies",
        json={
            "name": "TEST Self registration",
            "default_table_count": 2,
            "participant_consent": consent,
            "rounds": [{"title": "R1", "question": "Q"}],
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


def _code(client, headers):
    response = client.post(
        "/api/v1/public/recorder/capabilities", json={"purpose": "REGISTER_PARTICIPANT"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _register(client, token, name, notice_hash, ip, **ticks):
    body = {
        "token": token, "name": name, "notice_hash": notice_hash, "notice_read": True,
        "recording_consent": True, "transcription_consent": True, "analysis_consent": True,
        "publication_consent": True, **ticks,
    }
    return client.post("/api/v1/public/register", json=body, headers={"X-Forwarded-For": ip})


def test_a_table_code_registers_people_on_their_own_phones(client):
    assembly = _assembly(client)
    table2 = _phone(client, assembly, 1, "10.10.0.1")
    card = _code(client, table2)
    assert card["purpose"] == "REGISTER_PARTICIPANT" and card["table_number"] == 2
    assert "#/register/" in card["url"]
    token = re.search(r"#/register/(.+)$", card["url"]).group(1)

    # what the code is for, before a name is typed
    notice = client.post("/api/v1/public/register/notice", json={"token": token},
                         headers={"X-Forwarded-For": "10.10.0.2"})
    assert notice.status_code == 200, notice.text
    body = notice.json()
    assert (body["table_number"], body["color_key"], body["mode"]) == (2, "green", "required")
    assert body["assembly"]["name"] == "TEST Self registration" and len(body["hash"]) == 64

    # two people, two phones, one code
    first = _register(client, token, "Giulia", body["hash"], "10.10.0.3")
    assert first.status_code == 201, first.text
    second = _register(client, token, "Hamid", body["hash"], "10.10.0.4", publication_consent=False)
    assert second.status_code == 201, second.text
    assert first.json()["participant"]["label"] != second.json()["participant"]["label"]
    assert first.json()["table_number"] == 2 and first.json()["consent"]["method"] == "SELF_PHONE"

    # the table's own phone sees them on its roster; table 1 does not
    roster = client.get("/api/v1/public/recorder/consent-notice", headers=table2).json()["participants"]
    assert [p["name"] for p in roster] == ["Giulia", "Hamid"]
    table1 = _phone(client, assembly, 0, "10.10.0.5")
    assert client.get("/api/v1/public/recorder/consent-notice", headers=table1).json()["participants"] == []
    # ...and may record now, under the required rule
    assert client.post(
        "/api/v1/public/recorder/start",
        json={"round_id": assembly["rounds"][0]["id"], "mime_type": "audio/webm"}, headers=table2,
    ).status_code == 201

    # the organizer's list says how they registered
    listed = client.get(f"/api/v1/assemblies/{assembly['id']}/participants").json()
    giulia = next(p for p in listed if p["name"] == "Giulia")
    assert (giulia["source"], giulia["registered_table_number"], giulia["consent"]["method"]) == (
        "SELF_PHONE", 2, "SELF_PHONE",
    )

    # the code never makes a recorder
    refused = client.post("/api/v1/public/join", json={"token": token},
                          headers={"X-Forwarded-For": "10.10.0.6"})
    assert refused.status_code == 409, refused.text
    # a stale notice is refused here too
    assert _register(client, token, "Ines", "0" * 64, "10.10.0.7").status_code == 409


def test_the_person_keeps_a_page_that_shows_the_report_when_published(client):
    assembly = _assembly(client, consent="optional")
    table1 = _phone(client, assembly, 0, "10.10.1.1")
    token = re.search(r"#/register/(.+)$", _code(client, table1)["url"]).group(1)
    body = client.post("/api/v1/public/register/notice", json={"token": token},
                       headers={"X-Forwarded-For": "10.10.1.2"}).json()
    registered = _register(client, token, "Jana", body["hash"], "10.10.1.3").json()
    headers = {"Authorization": f"Bearer {registered['participant_token']}"}

    status = client.get("/api/v1/public/participant/status", headers=headers)
    assert status.status_code == 200, status.text
    page = status.json()
    assert (page["table_number"], page["color_key"], page["participant"]["name"]) == (1, "blue", "Jana")
    assert page["consent"]["recording"] is True and page["report_available"] is False
    assert client.get("/api/v1/public/participant/report", headers=headers).status_code == 404

    client.post(f"/api/v1/assemblies/{assembly['id']}/report/publish")
    assert client.get("/api/v1/public/participant/status", headers=headers).json()["report_available"]
    report = client.get("/api/v1/public/participant/report", headers=headers)
    assert report.status_code == 200, report.text
    assert report.json()["assembly"]["name"] == "TEST Self registration"
    pdf = client.get("/api/v1/public/participant/report.pdf", headers=headers)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    # a wrong or missing bearer sees nothing
    assert client.get("/api/v1/public/participant/status").status_code == 401
    assert client.get(
        "/api/v1/public/participant/status", headers={"Authorization": "Bearer nope"}
    ).status_code == 401
