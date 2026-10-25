# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Remix between sessions (0.7): "meet new people" seats everyone — the people
who registered at the tables included — so that as few pairs as possible sit
together again, with balanced tables; the participant's own page then says
where to go next."""

import re


def _assembly(client):
    return client.post(
        "/api/v1/assemblies",
        json={"name": "TEST Remix", "default_table_count": 2, "participant_consent": "optional",
              "rounds": [{"title": "R1", "question": "Q"}, {"title": "R2", "question": "Q"}]},
    ).json()


def _pairs(tables):
    pairs = set()
    for table in tables:
        names = sorted(p["name"] for p in table["participants"])
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                pairs.add((a, b))
    return pairs


def test_meet_new_people_avoids_repeated_pairs_and_balances_tables(client):
    assembly = _assembly(client)
    round1, round2 = (r["id"] for r in assembly["rounds"])
    client.post(f"/api/v1/assemblies/{assembly['id']}/participants", json={"participants": [
        {"label": f"P00{i}", "name": name} for i, name in enumerate(["Ada", "Ben", "Cleo", "Dan"], start=1)
    ]})
    # one person registered at table 2 on the phone: seated like the others
    token = re.search(r"#/join/(.+)$", assembly["invites"][1]["url"]).group(1)
    joined = client.post("/api/v1/public/join", json={"token": token},
                         headers={"X-Forwarded-For": "10.14.0.1"}).json()
    headers = {"Authorization": f"Bearer {joined['session_token']}"}
    notice = client.get("/api/v1/public/recorder/consent-notice", headers=headers).json()
    client.post("/api/v1/public/recorder/participants", json={
        "name": "Eve", "notice_hash": notice["hash"], "notice_read": True, "recording_consent": True,
        "transcription_consent": True, "analysis_consent": True, "publication_consent": True,
    }, headers=headers)

    first = client.post(f"/api/v1/rounds/{round1}/assignments/remix", json={"goal": "random"})
    assert first.status_code == 200, first.text
    assert first.json()["seated"] == 5
    assert sorted(len(t["participants"]) for t in first.json()["tables"]) == [2, 3]
    pairs_before = _pairs(first.json()["tables"])

    second = client.post(f"/api/v1/rounds/{round2}/assignments/remix", json={"goal": "new_people"}).json()
    assert second["seated"] == 5 and sorted(len(t["participants"]) for t in second["tables"]) == [2, 3]
    pairs_after = _pairs(second["tables"])
    # five people over two tables: at least one pair must repeat (3 at a
    # table), but the greedy seating keeps it to the minimum
    assert len(pairs_before & pairs_after) == second["repeated_pairs"] <= 1

    # continuity keeps the previous seating
    kept = client.post(f"/api/v1/rounds/{round2}/assignments/remix", json={"goal": "continuity"}).json()
    assert _pairs(kept["tables"]) == pairs_before
    sideways = client.post(f"/api/v1/rounds/{round2}/assignments/remix", json={"goal": "sideways"})
    assert sideways.status_code == 422


def test_the_participants_page_says_where_to_go_next(client):
    assembly = _assembly(client)
    round1, round2 = (r["id"] for r in assembly["rounds"])
    token = re.search(r"#/join/(.+)$", assembly["invites"][0]["url"]).group(1)
    joined = client.post("/api/v1/public/join", json={"token": token},
                         headers={"X-Forwarded-For": "10.14.1.1"}).json()
    table1 = {"Authorization": f"Bearer {joined['session_token']}"}
    card = client.post("/api/v1/public/recorder/capabilities", json={"purpose": "REGISTER_PARTICIPANT"},
                       headers=table1).json()
    rtoken = re.search(r"#/register/(.+)$", card["url"]).group(1)
    notice = client.post("/api/v1/public/register/notice", json={"token": rtoken},
                         headers={"X-Forwarded-For": "10.14.1.2"}).json()
    person = client.post("/api/v1/public/register", json={
        "token": rtoken, "name": "Fatima", "notice_hash": notice["hash"], "notice_read": True,
        "recording_consent": True, "transcription_consent": True, "analysis_consent": True,
        "publication_consent": True,
    }, headers={"X-Forwarded-For": "10.14.1.2"}).json()
    page_headers = {"Authorization": f"Bearer {person['participant_token']}"}

    # registered at table 1 for session 1 (seated there) — nothing to announce
    status = client.get("/api/v1/public/participant/status", headers=page_headers).json()
    assert status["table_number"] == 1 and status["next_table"] is None

    # the event is under way and session 2 is seated: her page points at
    # the table she will sit at next
    assert client.post(f"/api/v1/rounds/{round1}/start").status_code == 200
    client.post(f"/api/v1/rounds/{round2}/assignments/remix", json={"goal": "random"})
    status = client.get("/api/v1/public/participant/status", headers=page_headers).json()
    nxt = status["next_table"]
    assert nxt and nxt["round_position"] == 2 and nxt["table_number"] in (1, 2)
    assert nxt["color_key"] == ("blue" if nxt["table_number"] == 1 else "green")


def test_new_seating_leaves_a_refuser_at_the_table_that_is_not_recorded(client):
    """A person who refused (and was marked as moved) must not be dealt to a
    recorded table by New seating: the 2026-10-12 rehearsal seated the two
    moved refusers at tables 3 and 4, which were then blocked by
    PARTICIPANT_REFUSED for the whole second session."""
    import re

    created = client.post(
        "/api/v1/assemblies",
        json={
            "name": "TEST remix consent", "default_table_count": 2,
            "participant_consent": "required",
            "rounds": [{"title": "S1", "question": "Q"}, {"title": "S2", "question": "Q"}],
        },
    ).json()
    round1, round2 = (r["id"] for r in created["rounds"])
    client.post(f"/api/v1/rounds/{round1}/start")
    token = re.search(r"#/join/(.+)$", created["invites"][0]["url"]).group(1)
    joined = client.post("/api/v1/public/join", json={"token": token},
                         headers={"X-Forwarded-For": "10.70.0.1"}).json()
    phone = {"Authorization": f"Bearer {joined['session_token']}"}
    notice = client.get("/api/v1/public/recorder/consent-notice", headers=phone).json()
    act = {"notice_hash": notice["hash"], "notice_read": True, "recording_consent": True,
           "transcription_consent": True, "analysis_consent": True, "publication_consent": True}
    for name in ("Anna", "Bruno", "Carla"):
        client.post("/api/v1/public/recorder/participants", json={**act, "name": name}, headers=phone)
    refuser = client.post(
        "/api/v1/public/recorder/participants",
        json={**act, "name": "Dario", "recording_consent": False, "transcription_consent": False,
              "analysis_consent": False, "publication_consent": False},
        headers=phone,
    ).json()["participant"]["id"]
    client.post(f"/api/v1/public/recorder/participants/{refuser}/moved", headers=phone)

    for goal in ("new_people", "random", "continuity"):
        mixed = client.post(f"/api/v1/rounds/{round2}/assignments/remix", json={"goal": goal}).json()
        assert mixed["seated"] == 3, mixed
        tables = client.get(f"/api/v1/rounds/{round2}/tables").json()
        seated = {p["name"] for t in tables for p in t["participants"]}
        assert "Dario" not in seated and seated == {"Anna", "Bruno", "Carla"}
    monitor = client.get(f"/api/v1/rounds/{round2}/monitor").json()
    assert not any(
        r["code"] == "PARTICIPANT_REFUSED" for t in monitor["tables"] for r in t["readiness"]["reasons"]
    )
