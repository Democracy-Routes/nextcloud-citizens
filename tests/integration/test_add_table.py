# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tables are numbered, coloured, and can be added while the event runs.

A `Table` row is per round; the table the room knows is the number, the same
in every round. Adding one therefore adds a row to every round, issues one QR
code without touching the codes already on the wall, and the completeness
checks count it from then on.
"""

import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from alembic import command
from alembic.config import Config

from citizens.db.models import Assembly, Table
from citizens.db.session import session_scope, sqlite_url
from citizens.services.recording import assembly_progress


def _assembly(client, tables=2, rounds=2, mode="orchestrated"):
    created = client.post(
        "/api/v1/assemblies",
        json={
            "name": "TEST tables",
            "default_table_count": tables,
            "recording_mode": mode,
            "rounds": [{"title": f"R{i}", "question": "Q"} for i in range(1, rounds + 1)],
        },
    )
    assert created.status_code == 201, created.text
    return created.json()


def _join(client, url):
    token = re.search(r"#/join/(.+)$", url).group(1)
    joined = client.post(
        "/api/v1/public/join", json={"token": token}, headers={"X-Forwarded-For": "10.4.0.1"}
    )
    assert joined.status_code == 200, joined.text
    return joined.json()


def test_tables_carry_their_colour_from_the_number(client):
    assembly = _assembly(client, tables=7, rounds=1)
    tables = client.get(f"/api/v1/rounds/{assembly['rounds'][0]['id']}/tables").json()
    assert [t["color_key"] for t in tables] == [
        "blue", "green", "orange", "purple", "red", "teal", "blue",
    ]
    monitor = client.get(f"/api/v1/rounds/{assembly['rounds'][0]['id']}/monitor").json()
    assert [t["color_key"] for t in monitor["tables"]][:3] == ["blue", "green", "orange"]
    # the phone is told its colour too
    joined = _join(client, assembly["invites"][6]["url"])
    assert joined["table_number"] == 7 and joined["table_color"] == "blue"


def test_adding_a_table_mid_round_reaches_every_round_and_the_phone_can_join_it(client):
    assembly = _assembly(client, tables=2, rounds=2)
    round1, round2 = assembly["rounds"]
    client.post(f"/api/v1/rounds/{round1['id']}/start")

    added = client.post(f"/api/v1/assemblies/{assembly['id']}/tables")
    assert added.status_code == 201, added.text
    body = added.json()
    assert body["number"] == 3 and body["color_key"] == "orange"
    assert body["invite"]["table_number"] == 3

    for round_ in (round1, round2):
        numbers = [t["number"] for t in client.get(f"/api/v1/rounds/{round_['id']}/tables").json()]
        assert numbers == [1, 2, 3]
    monitor = client.get(f"/api/v1/rounds/{round1['id']}/monitor").json()
    assert monitor["tables_total"] == 3

    # the existing codes stay valid, and the new one works at once
    invites = client.get(f"/api/v1/assemblies/{assembly['id']}/invites").json()
    assert sorted((i["table_number"], i["active"]) for i in invites) == [(1, True), (2, True), (3, True)]
    joined = _join(client, body["invite"]["url"])
    assert joined["table_number"] == 3 and joined["table_color"] == "orange"
    started = client.post(
        "/api/v1/public/recorder/start",
        json={"round_id": round1["id"], "mime_type": "audio/webm"},
        headers={"Authorization": f"Bearer {joined['session_token']}"},
    )
    assert started.status_code == 201, started.text

    # completeness counts the table from now on — the rows, not the old count
    detail = client.get(f"/api/v1/assemblies/{assembly['id']}").json()
    assert detail["default_table_count"] == 3
    with session_scope() as session:
        progress = assembly_progress(session, session.get(Assembly, assembly["id"]))
    assert progress["tables_expected"] == 3
    assert progress["tables_missing"] == [1, 2, 3]

    # a round added afterwards is born with the table
    later = client.post(f"/api/v1/assemblies/{assembly['id']}/rounds", json={"title": "R3"}).json()
    assert [t["number"] for t in client.get(f"/api/v1/rounds/{later['id']}/tables").json()] == [1, 2, 3]


def test_a_standalone_session_can_grow_a_table_too(client):
    body = client.post("/api/v1/sessions/record-now", json={}).json()
    added = client.post(f"/api/v1/assemblies/{body['container_id']}/tables").json()
    assert added["number"] == 2 and added["color_key"] == "green"
    tables = client.get(f"/api/v1/rounds/{body['session_id']}/tables").json()
    assert [(t["number"], t["color_key"]) for t in tables] == [(1, "blue"), (2, "green")]


def test_two_organizers_adding_at_once_get_distinct_numbers(client):
    assembly = _assembly(client, tables=1, rounds=1)

    def add(_):
        return client.post(f"/api/v1/assemblies/{assembly['id']}/tables")

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(add, range(4)))
    numbers = sorted(r.json()["number"] for r in responses if r.status_code == 201)
    # every success is distinct; a loser of the race is told to retry, never given a duplicate
    assert len(numbers) == len(set(numbers))
    assert all(r.status_code in (201, 409) for r in responses)
    with session_scope() as session:
        rows = session.query(Table).filter(Table.round_id == assembly["rounds"][0]["id"]).all()
        assert sorted(t.number for t in rows) == list(range(1, len(rows) + 1))


def test_a_plenary_room_or_a_closed_assembly_cannot_grow(client):
    plenary = _assembly(client, tables=3, rounds=1, mode="plenary")
    assert client.post(f"/api/v1/assemblies/{plenary['id']}/tables").status_code == 409

    assembly = _assembly(client, tables=1, rounds=1)
    closed = client.post(f"/api/v1/assemblies/{assembly['id']}/close")
    assert closed.status_code in (200, 204), closed.text
    assert client.post(f"/api/v1/assemblies/{assembly['id']}/tables").status_code == 409


def test_only_the_owner_can_add_a_table(client):
    assembly = _assembly(client, tables=1, rounds=1)
    other = client.post(
        f"/api/v1/assemblies/{assembly['id']}/tables", headers={"X-Test-User": "someone-else"}
    )
    assert other.status_code == 404


def test_migration_colours_the_tables_that_existed_before(client, settings_env):
    assembly = _assembly(client, tables=7, rounds=1)
    cfg = Config()
    cfg.set_main_option("script_location", str(Path("citizens/db/migrations").resolve()))
    cfg.set_main_option(
        "sqlalchemy.url", sqlite_url(settings_env.app_persistent_storage / "citizens.db")
    )
    command.downgrade(cfg, "0024")
    command.upgrade(cfg, "head")
    tables = client.get(f"/api/v1/rounds/{assembly['rounds'][0]['id']}/tables").json()
    assert [t["color_key"] for t in tables] == [
        "blue", "green", "orange", "purple", "red", "teal", "blue",
    ]
