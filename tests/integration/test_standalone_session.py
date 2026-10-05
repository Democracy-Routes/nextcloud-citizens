# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A Session stands on its own: Record now and Start a Session need no assembly.

The rows behind a standalone Session are a Round inside a container assembly
of kind "session" (services/sessions.py). These tests pin the product contract
— nothing asks for an assembly, the phone can record at once, the container is
listed as a Session, legacy assemblies are untouched — not the storage detail.
"""

import re
from pathlib import Path

from alembic import command
from alembic.config import Config

from citizens.db.models import Assembly, Round
from citizens.db.session import session_scope, sqlite_url


def _join(client, url):
    token = re.search(r"#/join/(.+)$", url).group(1)
    joined = client.post(
        "/api/v1/public/join", json={"token": token}, headers={"X-Forwarded-For": "10.7.0.1"}
    )
    assert joined.status_code == 200, joined.text
    return joined.json()


def test_record_now_makes_a_session_a_table_and_a_recorder_that_can_start(client):
    created = client.post("/api/v1/sessions/record-now", json={})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["table_number"] == 1
    assert "#/join/" in body["recorder_url"]

    # the phone that opens the link is Table 1's recorder, and records at once:
    # no assembly was configured, no facilitator pressed Start
    joined = _join(client, body["recorder_url"])
    assert joined["table_number"] == 1
    assert joined["assembly"]["kind"] == "session"
    assert joined["assembly"]["recording_mode"] == "independent"
    assert [r["id"] for r in joined["rounds"]] == [body["session_id"]]
    started = client.post(
        "/api/v1/public/recorder/start",
        json={"round_id": body["session_id"], "mime_type": "audio/webm"},
        headers={"Authorization": f"Bearer {joined['session_token']}"},
    )
    assert started.status_code == 201, started.text


def test_record_now_is_listed_as_a_session_in_the_callers_language(client):
    body = client.post("/api/v1/sessions/record-now", json={"language": "it"}).json()

    [row] = [a for a in client.get("/api/v1/assemblies").json() if a["id"] == body["container_id"]]
    assert row["kind"] == "session"
    assert row["language"] == "it"
    assert row["name"].startswith("Recording ")

    detail = client.get(f"/api/v1/assemblies/{body['container_id']}").json()
    assert detail["kind"] == "session"
    assert [r["id"] for r in detail["rounds"]] == [body["session_id"]]
    assert detail["default_table_count"] == 1
    assert detail["rounds"][0]["question"] == ""
    assert detail["rounds"][0]["objective"] is None


def test_start_a_session_keeps_question_and_objective_apart(client):
    created = client.post(
        "/api/v1/sessions",
        json={
            "question": "How should local mobility improve?",
            "objective": "Produce three concrete proposals.",
            "duration_minutes": 20,
            "table_count": 3,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["question"] == "How should local mobility improve?"
    assert body["objective"] == "Produce three concrete proposals."
    assert body["recording_mode"] == "orchestrated"
    assert body["table_count"] == 3
    assert [card["table_number"] for card in body["invites"]] == [1, 2, 3]

    detail = client.get(f"/api/v1/assemblies/{body['container_id']}").json()
    assert detail["name"] == "How should local mobility improve?"
    round_ = detail["rounds"][0]
    assert round_["id"] == body["session_id"]
    assert round_["objective"] == "Produce three concrete proposals."
    assert round_["duration_minutes"] == 20

    # the phone reads both halves of the brief
    joined = _join(client, body["invites"][0]["url"])
    assert joined["rounds"][0]["question"] == "How should local mobility improve?"
    assert joined["rounds"][0]["objective"] == "Produce three concrete proposals."


def test_objective_is_optional_and_can_be_set_kept_and_cleared(client):
    body = client.post("/api/v1/sessions", json={"question": "Q"}).json()
    round_url = f"/api/v1/rounds/{body['session_id']}"
    assert client.get(f"/api/v1/assemblies/{body['container_id']}").json()["rounds"][0]["objective"] is None

    assert client.put(round_url, json={"objective": "Agree on one priority"}).json()["objective"] == (
        "Agree on one priority"
    )
    # an update that does not mention it leaves it alone
    assert client.put(round_url, json={"title": "Renamed"}).json()["objective"] == "Agree on one priority"
    # an empty string clears it back to "none stated"
    assert client.put(round_url, json={"objective": ""}).json()["objective"] is None


def test_the_assembly_wizard_is_unchanged_and_its_rounds_may_state_an_objective(client):
    assembly = client.post(
        "/api/v1/assemblies",
        json={
            "name": "TEST Assembly",
            "default_table_count": 2,
            "rounds": [{"title": "R1", "question": "Q1"}],
        },
    ).json()
    assert assembly["kind"] == "assembly"
    assert assembly["rounds"][0]["objective"] is None

    added = client.post(
        f"/api/v1/assemblies/{assembly['id']}/rounds",
        json={"title": "R2", "question": "Q2", "objective": "O2"},
    ).json()
    assert added["objective"] == "O2"


def test_a_session_is_private_to_whoever_started_it(client):
    body = client.post("/api/v1/sessions/record-now", json={}).json()
    other = {"X-Test-User": "someone-else"}
    assert client.get(f"/api/v1/assemblies/{body['container_id']}", headers=other).status_code == 404
    assert client.get(f"/api/v1/rounds/{body['session_id']}/monitor", headers=other).status_code == 404
    listed = client.get("/api/v1/assemblies", headers=other).json()
    assert body["container_id"] not in {a["id"] for a in listed}


def test_migration_treats_every_earlier_row_as_an_assembly_without_an_objective(client, settings_env):
    """Downgrading to 0023 and back is what a pre-0.7 database looks like to 0024:
    rows with no `kind` column become assemblies, rounds have no objective."""
    body = client.post(
        "/api/v1/sessions", json={"question": "Q", "objective": "will not survive 0023"}
    ).json()
    cfg = Config()
    cfg.set_main_option("script_location", str(Path("citizens/db/migrations").resolve()))
    cfg.set_main_option(
        "sqlalchemy.url", sqlite_url(settings_env.app_persistent_storage / "citizens.db")
    )
    command.downgrade(cfg, "0023")
    command.upgrade(cfg, "head")
    with session_scope() as session:
        container = session.get(Assembly, body["container_id"])
        assert container is not None and container.kind == "assembly"
        round_ = session.get(Round, body["session_id"])
        assert round_ is not None and round_.objective is None
    # and the API keeps working on such rows
    assert client.get(f"/api/v1/assemblies/{body['container_id']}").json()["kind"] == "assembly"
