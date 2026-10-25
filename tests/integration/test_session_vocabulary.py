# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Session API speaks product vocabulary over the rounds that store it.

A `session_id` IS a round id: both the new /sessions routes and the old /rounds
routes accept it, so nothing that already works has to change while new work
says Session.
"""

from citizens.domain.vocabulary import SESSION_TERMS, legacy_name


def test_the_mapping_is_stated_once():
    assert legacy_name("session") == "round"
    assert legacy_name("session_id") == "round_id"
    assert legacy_name("table") == "table"
    assert SESSION_TERMS["recorder"] == "recorder_session"


def test_a_standalone_session_and_an_assembly_round_read_the_same_way(client):
    standalone = client.post(
        "/api/v1/sessions", json={"question": "How should mobility improve?", "objective": "Three proposals"}
    ).json()
    assembly = client.post(
        "/api/v1/assemblies",
        json={"name": "Milan Mobility", "default_table_count": 2,
              "rounds": [{"title": "Introduction", "question": "Q1"}, {"title": "Main", "question": "Q2"}]},
    ).json()

    detail = client.get(f"/api/v1/sessions/{standalone['session_id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["session_id"] == standalone["session_id"]
    assert body["container_id"] == standalone["container_id"]
    assert body["standalone"] is True
    assert body["question"] == "How should mobility improve?"
    assert body["objective"] == "Three proposals"
    assert body["position"] == 1 and body["status"] == "NOT_STARTED"
    assert [(t["number"], t["color_key"]) for t in body["tables"]] == [(1, "blue")]
    assert body["recording_count"] == 0

    second = client.get(f"/api/v1/sessions/{assembly['rounds'][1]['id']}").json()
    assert second["standalone"] is False
    assert second["container_name"] == "Milan Mobility"
    assert second["title"] == "Main" and second["position"] == 2
    assert [t["number"] for t in second["tables"]] == [1, 2]

    # the same id drives the legacy route: start it as a round, read it as a session
    assert client.post(f"/api/v1/rounds/{standalone['session_id']}/start").status_code == 200
    assert client.get(f"/api/v1/sessions/{standalone['session_id']}").json()["status"] == "ACTIVE"

    listed = client.get("/api/v1/sessions").json()
    assert [s["session_id"] for s in listed] == [
        assembly["rounds"][0]["id"], assembly["rounds"][1]["id"], standalone["session_id"],
    ]


def test_sessions_are_private_to_their_owner(client):
    standalone = client.post("/api/v1/sessions", json={"question": "Q"}).json()
    other = {"X-Test-User": "someone-else"}
    assert client.get(f"/api/v1/sessions/{standalone['session_id']}", headers=other).status_code == 404
    assert client.get("/api/v1/sessions", headers=other).json() == []
