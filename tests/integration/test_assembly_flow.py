# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Milestone 1 acceptance as an API flow: 50 participants, 10 tables, 2 rounds."""


def _create_assembly(client):
    response = client.post(
        "/api/v1/assemblies",
        json={
            "name": "TEST Assembly",
            "description": "Integration test",
            "language": "it",
            "expected_participants": 50,
            "default_table_count": 10,
            "rounds": [
                {"title": "Round 1", "question": "What problems exist?", "duration_minutes": 30},
                {"title": "Round 2", "question": "What should we do?", "duration_minutes": 30},
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _import_50_participants(client, assembly_id):
    csv_text = "label,name,email\n" + "".join(f"P{i:03d},,\n" for i in range(1, 51))
    response = client.post(
        f"/api/v1/assemblies/{assembly_id}/participants/import-csv", json={"csv": csv_text}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_full_assembly_flow(client):
    assembly = _create_assembly(client)
    assert len(assembly["rounds"]) == 2
    assert assembly["status"] == "DRAFT"

    participants = _import_50_participants(client, assembly["id"])
    assert len(participants) == 50

    round1, round2 = assembly["rounds"]

    # random assignment: 10 tables x 5 participants
    tables = client.post(f"/api/v1/rounds/{round1['id']}/assignments/randomize").json()
    assert len(tables) == 10
    assert sorted(len(t["participants"]) for t in tables) == [5] * 10
    all_labels = sorted(p["label"] for t in tables for p in t["participants"])
    assert all_labels == sorted(p["label"] for p in participants)

    # copy to round 2 preserves the distribution by table number
    tables2 = client.post(f"/api/v1/rounds/{round2['id']}/assignments/copy-previous").json()
    by_number_1 = {t["number"]: {p["label"] for p in t["participants"]} for t in tables}
    by_number_2 = {t["number"]: {p["label"] for p in t["participants"]} for t in tables2}
    assert by_number_1 == by_number_2

    # manual move
    source = tables2[0]
    target = tables2[1]
    moved_participant = source["participants"][0]
    tables2_after = client.post(
        f"/api/v1/rounds/{round2['id']}/assignments/move",
        json={"participant_id": moved_participant["id"], "to_table_id": target["id"]},
    ).json()
    sizes = {t["number"]: len(t["participants"]) for t in tables2_after}
    assert sizes[source["number"]] == 4
    assert sizes[target["number"]] == 6


def test_invites_lifecycle(client):
    assembly = _create_assembly(client)

    generated = client.post(f"/api/v1/assemblies/{assembly['id']}/invites/generate")
    assert generated.status_code == 201
    invites = generated.json()
    assert len(invites) == 10
    assert all("<svg" in invite["qr_svg"] for invite in invites)
    assert all("/recorder.html#/join/" in invite["url"] for invite in invites)
    # raw tokens are never repeated by the listing endpoint
    listing = client.get(f"/api/v1/assemblies/{assembly['id']}/invites").json()
    assert len(listing) == 10
    assert all(invite["active"] for invite in listing)
    assert all("url" not in invite for invite in listing)

    # regeneration revokes the previous set (still one active invite per table)
    client.post(f"/api/v1/assemblies/{assembly['id']}/invites/generate")
    listing = client.get(f"/api/v1/assemblies/{assembly['id']}/invites").json()
    assert len(listing) == 10
    assert all(invite["active"] for invite in listing)

    # explicit revoke deactivates everything
    assert client.post(f"/api/v1/assemblies/{assembly['id']}/invites/revoke").status_code == 204
    listing = client.get(f"/api/v1/assemblies/{assembly['id']}/invites").json()
    assert all(not invite["active"] for invite in listing)


def test_ownership_isolation(client):
    assembly = _create_assembly(client)

    other = {"X-Test-User": "someone-else"}
    assert client.get(f"/api/v1/assemblies/{assembly['id']}", headers=other).status_code == 404
    assert client.get("/api/v1/assemblies", headers=other).json() == []
    assert (
        client.post(
            f"/api/v1/assemblies/{assembly['id']}/invites/generate", headers=other
        ).status_code
        == 404
    )
    # owner still sees it
    assert client.get(f"/api/v1/assemblies/{assembly['id']}").status_code == 200


def test_round_management(client):
    assembly = _create_assembly(client)
    round1 = assembly["rounds"][0]

    # add a third round
    added = client.post(
        f"/api/v1/assemblies/{assembly['id']}/rounds",
        json={"title": "Round 3", "question": "Priorities?", "duration_minutes": 20},
    )
    assert added.status_code == 201
    assert added.json()["position"] == 3

    # move it to the front
    moved = client.put(f"/api/v1/rounds/{added.json()['id']}", json={"position": 1})
    assert moved.json()["position"] == 1
    detail = client.get(f"/api/v1/assemblies/{assembly['id']}").json()
    assert [r["title"] for r in detail["rounds"]] == ["Round 3", "Round 1", "Round 2"]

    # delete one; positions compact
    assert client.delete(f"/api/v1/rounds/{round1['id']}").status_code == 204
    detail = client.get(f"/api/v1/assemblies/{assembly['id']}").json()
    assert [(r["title"], r["position"]) for r in detail["rounds"]] == [("Round 3", 1), ("Round 2", 2)]


def test_an_assembly_needs_at_least_one_table(client):
    """Zero tables builds no Table rows, so generate_invites has nothing to make
    codes for and no phone can ever join. Nothing in the UI repairs it either -
    raising the count creates tables only for FUTURE rounds - so the assembly
    would have to be deleted and made again. Refused at the door instead."""
    response = client.post(
        "/api/v1/assemblies",
        json={
            "name": "TEST No tables",
            "default_table_count": 0,
            "rounds": [{"title": "R1", "question": "Q?", "duration_minutes": 30}],
        },
    )

    assert response.status_code == 422


def test_an_assembly_created_without_a_table_count_still_gets_one(client):
    response = client.post("/api/v1/assemblies", json={"name": "TEST Default tables"})

    assert response.status_code == 201
    assert response.json()["default_table_count"] == 1


def test_the_table_count_cannot_be_dropped_to_zero_later(client):
    assembly = client.post(
        "/api/v1/assemblies", json={"name": "TEST Shrink", "default_table_count": 4}
    ).json()

    response = client.put(
        f"/api/v1/assemblies/{assembly['id']}", json={"default_table_count": 0}
    )

    assert response.status_code == 422


def test_an_unsupported_language_is_refused(client):
    """Anything outside the offered list reaches the analysis prompt as English
    and selects no transcription model for the room's real language. Better to
    refuse it than to accept it and quietly ignore it."""
    response = client.post(
        "/api/v1/assemblies", json={"name": "TEST Klingon", "language": "tlh"}
    )

    assert response.status_code == 422


def test_the_name_description_and_language_can_be_edited(client):
    """The endpoint always accepted these; nothing in the UI ever sent them."""
    assembly = client.post(
        "/api/v1/assemblies", json={"name": "TEST Typo", "language": "en"}
    ).json()

    updated = client.put(
        f"/api/v1/assemblies/{assembly['id']}",
        json={"name": "TEST Corrected", "description": "Mobility", "language": "it"},
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "TEST Corrected"
    assert updated.json()["description"] == "Mobility"
    assert updated.json()["language"] == "it"
