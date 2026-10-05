# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pre-registration (0.7): the organizer issues one reusable link, people
register and consent at home with no table, and at the door the table's phone
finds them by name and seats them — the consent act travels with them, the
roster and the start gate see them, and nothing crosses tables or events."""

import re


def _assembly(client, consent="required", name="TEST Pre-registration"):
    created = client.post(
        "/api/v1/assemblies",
        json={"name": name, "default_table_count": 2, "participant_consent": consent,
              "rounds": [{"title": "R1", "question": "Q"}]},
    ).json()
    client.post(f"/api/v1/rounds/{created['rounds'][0]['id']}/start")
    return created


def _phone(client, assembly, index, ip):
    token = re.search(r"#/join/(.+)$", assembly["invites"][index]["url"]).group(1)
    joined = client.post("/api/v1/public/join", json={"token": token},
                         headers={"X-Forwarded-For": ip}).json()
    return {"Authorization": f"Bearer {joined['session_token']}"}


def _register_at_home(client, token, name, ip, consent=True):
    notice = client.post("/api/v1/public/register/notice", json={"token": token},
                         headers={"X-Forwarded-For": ip}).json()
    assert notice["table_number"] is None and notice["color_key"] is None
    body = {"token": token, "name": name, "notice_hash": notice["hash"], "notice_read": True,
            "recording_consent": consent, "transcription_consent": consent,
            "analysis_consent": consent, "publication_consent": consent}
    response = client.post("/api/v1/public/register", json=body, headers={"X-Forwarded-For": ip})
    assert response.status_code == 201, response.text
    return response.json()


def test_people_register_at_home_and_are_seated_at_the_door_by_name(client):
    assembly = _assembly(client)
    round_id = assembly["rounds"][0]["id"]
    link = client.post(f"/api/v1/assemblies/{assembly['id']}/registration-link")
    assert link.status_code == 200, link.text
    url = link.json()["url"]
    assert "#/register/" in url and link.json()["registered"] == {"total": 0, "seated": 0}
    # asking again gives the same link
    assert client.post(f"/api/v1/assemblies/{assembly['id']}/registration-link").json()["url"] == url
    token = re.search(r"#/register/(.+)$", url).group(1)

    ines = _register_at_home(client, token, "Ines Rossi", "10.13.0.1")
    assert ines["table_number"] is None and ines["consent"]["method"] == "PRE_REGISTRATION"
    _register_at_home(client, token, "Ivo Bianchi", "10.13.0.2", consent=False)
    page = client.get("/api/v1/public/participant/status",
                      headers={"Authorization": f"Bearer {ines['participant_token']}"}).json()
    assert page["table_number"] is None and page["consent"]["recording"] is True
    assert client.get(f"/api/v1/assemblies/{assembly['id']}/registration-link").json()["registered"] == {
        "total": 2, "seated": 0,
    }

    # at the door: table 2's phone finds her by name and seats her
    table2 = _phone(client, assembly, 1, "10.13.1.1")
    assert client.get("/api/v1/public/recorder/participants/search?q=i", headers=table2).json() == []
    found = client.get("/api/v1/public/recorder/participants/search?q=ros", headers=table2).json()
    assert [p["name"] for p in found] == ["Ines Rossi"] and found[0]["recording_consent"] is True
    assert "email" not in found[0]
    blocked = client.post("/api/v1/public/recorder/start",
                          json={"round_id": round_id, "mime_type": "audio/webm"}, headers=table2)
    assert blocked.status_code == 409
    seated = client.post(f"/api/v1/public/recorder/participants/{found[0]['id']}/seat", headers=table2)
    assert seated.status_code == 200, seated.text
    assert seated.json()["table"] == {
        "mode": "required", "registered": 1, "consenting": 1, "can_record": True,
    }
    roster = client.get("/api/v1/public/recorder/consent-notice", headers=table2).json()["participants"]
    assert roster == [
        {"label": ines["participant"]["label"], "name": "Ines Rossi", "recording_consent": True},
    ]
    started = client.post("/api/v1/public/recorder/start",
                          json={"round_id": round_id, "mime_type": "audio/webm"}, headers=table2)
    assert started.status_code == 201
    # seated for the session too, and her own page knows the table
    tables = client.get(f"/api/v1/rounds/{round_id}/tables").json()
    assert [p["name"] for p in next(t for t in tables if t["number"] == 2)["participants"]] == ["Ines Rossi"]
    page = client.get("/api/v1/public/participant/status",
                      headers={"Authorization": f"Bearer {ines['participant_token']}"}).json()
    assert page["table_number"] == 2 and page["color_key"] == "green"
    # once seated she is no longer offered at the door; seating twice is refused
    assert client.get("/api/v1/public/recorder/participants/search?q=ros", headers=table2).json() == []
    assert client.post(f"/api/v1/public/recorder/participants/{found[0]['id']}/seat",
                       headers=table2).status_code == 409
    assert client.get(f"/api/v1/assemblies/{assembly['id']}/registration-link").json()["registered"] == {
        "total": 2, "seated": 1,
    }
    listed = client.get(f"/api/v1/assemblies/{assembly['id']}/participants").json()
    assert next(p for p in listed if p["name"] == "Ines Rossi")["source"] == "PRE_REGISTRATION"

    # another event's phone cannot see or seat her
    other = _assembly(client, name="TEST Elsewhere")
    stranger = _phone(client, other, 0, "10.13.2.1")
    assert client.get("/api/v1/public/recorder/participants/search?q=bianchi", headers=stranger).json() == []
    ivo = client.get("/api/v1/public/recorder/participants/search?q=bianchi", headers=table2).json()[0]
    assert client.post(f"/api/v1/public/recorder/participants/{ivo['id']}/seat",
                       headers=stranger).status_code == 404
