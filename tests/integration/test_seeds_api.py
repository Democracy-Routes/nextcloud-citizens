# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Polis seeds (0.9): approved findings become short statements the
organizer reviews and exports. The model is faked; the job runner, the
routes, the review rules and the files are real."""

import csv
import io
import json
import time
from pathlib import Path

from alembic import command
from alembic.config import Config

from citizens.db.models import Assembly, Finding, Participant, StatementSeed
from citizens.db.session import session_scope, sqlite_url
from citizens.domain.analysis_schemas import StatementSeedItem, StatementSeeds
from citizens.services import analysis as analysis_svc


class MemoryStore:
    def __init__(self, values=None):
        self.values = values or {}

    def get_value(self, key):
        return self.values.get(key)

    def set_value(self, key, value, sensitive=False):
        self.values[key] = value

    def delete_value(self, key):
        self.values.pop(key, None)


def _assembly(client, name="TEST Seeds", language="en"):
    created = client.post(
        "/api/v1/assemblies",
        json={"name": name, "language": language, "default_table_count": 2,
              "rounds": [{"title": "S1", "question": "Q1", "duration_minutes": 30},
                         {"title": "S2", "question": "Q2", "duration_minutes": 30}]},
    )
    assert created.status_code == 201, created.text
    return created.json()


def _findings(assembly_id, specs):
    """specs: (scope, type, title, status, session position)."""
    ids = []
    with session_scope() as session:
        assembly = session.get(Assembly, assembly_id)
        rounds = {r.position: r for r in assembly.rounds}
        # a registered participant: her name must never reach the model
        session.add(Participant(assembly_id=assembly_id, label="P001", name="Anna", source="TABLE_DEVICE"))
        for scope, type_, title, status, position in specs:
            finding = Finding(
                assembly_id=assembly_id, round_id=rounds[position].id, scope=scope, type=type_,
                title=title, summary=f"Summary of {title}. Anna said so.", status=status,
                table_id=None,
            )
            session.add(finding)
            session.flush()
            ids.append(finding.id)
    return ids


def _configure(monkeypatch, answer):
    """A configured analysis provider whose model answers `answer(finding_ids)`."""
    store = MemoryStore({"analysis_api_key": "ak-test", "analysis_enabled": "1"})
    monkeypatch.setattr("citizens.services.provider_config.default_store", lambda: store)
    monkeypatch.setattr("citizens.services.provider_config.analysis_ready_cached", lambda: True)
    prompts: list[tuple[str, str]] = []

    def fake_chat_json(base_url, key, model, system_prompt, user_prompt, schema):
        assert schema is StatementSeeds and key == "ak-test"
        prompts.append((system_prompt, user_prompt))
        ids = [line.split(": ", 1)[1] for line in user_prompt.splitlines() if line.startswith("finding_id: ")]
        return answer(ids)

    monkeypatch.setattr("citizens.services.seeds.chat_json", fake_chat_json)
    return prompts


def _wait(client, assembly_id, until, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        listing = client.get(f"/api/v1/assemblies/{assembly_id}/seeds").json()
        if until(listing):
            return listing
        time.sleep(0.3)
    raise AssertionError(f"timed out: {listing}")


def _settled(listing):
    return listing["job"] is not None and listing["job"]["state"] in ("SUCCEEDED", "FAILED")


def test_generation_needs_a_provider_and_approved_findings(client, monkeypatch):
    assembly = _assembly(client)
    url = f"/api/v1/assemblies/{assembly['id']}/seeds"
    listing = client.get(url).json()
    assert listing["seeds"] == [] and listing["ready_to_export"] is False
    assert listing["max_chars"] == 400 and listing["soft_chars"] == 140
    monkeypatch.setattr("citizens.services.provider_config.analysis_ready_cached", lambda: False)
    refused = client.post(f"{url}/generate")
    assert refused.status_code == 409 and "not configured" in refused.json()["detail"]
    monkeypatch.setattr("citizens.services.provider_config.analysis_ready_cached", lambda: True)
    _findings(assembly["id"], [("round", "proposal", "Draft only", "DRAFT", 1)])
    refused = client.post(f"{url}/generate")
    assert refused.status_code == 409 and "Approve" in refused.json()["detail"]


def test_seeds_are_written_from_approved_findings_in_the_assembly_language(client, monkeypatch):
    def answer(ids):
        return StatementSeeds(seeds=[
            # ids come in prompt order: session 1's finding first
            StatementSeedItem(finding_id=ids[0], statements=["Le piste ciclabili vanno illuminate."]),
            StatementSeedItem(finding_id=ids[1], statements=[
                "Gli autobus serali dovrebbero circolare fino a mezzanotte.",
                "Gli autobus serali dovrebbero circolare fino a mezzanotte",  # repeat
            ]),
            StatementSeedItem(finding_id="not-a-finding", statements=["Ignored."]),
        ])

    prompts = _configure(monkeypatch, answer)
    assembly = _assembly(client, language="it")
    approved, approved_2, _rejected, _table = (
        _findings(assembly["id"], [
            ("round", "proposal", "Autobus serali", "APPROVED", 2),
            ("round", "concern", "Piste ciclabili", "EDITED_AND_APPROVED", 1),
            ("round", "proposal", "Rejected one", "REJECTED", 1),
            ("table", "proposal", "Table level", "APPROVED", 1),
        ])
    )
    url = f"/api/v1/assemblies/{assembly['id']}/seeds"
    assert client.post(f"{url}/generate").json() == {"queued": True}
    assert client.post(f"{url}/generate").json() == {"queued": False}  # one live job at a time
    listing = _wait(client, assembly["id"], _settled)
    assert listing["job"]["state"] == "SUCCEEDED", listing["job"]
    texts = [s["text"] for s in listing["seeds"]]
    assert texts == [
        "Le piste ciclabili vanno illuminate.",
        "Gli autobus serali dovrebbero circolare fino a mezzanotte.",
    ]
    assert [s["finding_id"] for s in listing["seeds"]] == [approved_2, approved]
    assert all(s["status"] == "DRAFT" and s["origin"] == "ai" for s in listing["seeds"])
    assert listing["findings_approved"] == 3 and listing["ready_to_export"] is False
    system_prompt, user_prompt = prompts[-1]
    assert "Write everything in Italian." in system_prompt
    # session order, cross-table findings only, names masked
    assert user_prompt.index("Piste ciclabili") < user_prompt.index("Autobus serali")
    assert "Table level" not in user_prompt and "Rejected one" not in user_prompt
    assert "Anna" not in user_prompt


def test_table_findings_feed_the_seeds_when_no_session_was_clustered(client, monkeypatch):
    _configure(monkeypatch, lambda ids: StatementSeeds(seeds=[
        StatementSeedItem(finding_id=ids[0], statements=["From the table."]),
    ]))
    assembly = _assembly(client)
    _findings(assembly["id"], [("table", "proposal", "Table level", "APPROVED", 1)])
    url = f"/api/v1/assemblies/{assembly['id']}/seeds"
    assert client.post(f"{url}/generate").status_code == 202
    listing = _wait(client, assembly["id"], _settled)
    assert [s["text"] for s in listing["seeds"]] == ["From the table."]


def test_review_edit_order_and_regeneration_keep_what_a_person_touched(client, monkeypatch):
    runs = {"n": 0}

    def answer(ids):
        runs["n"] += 1
        return StatementSeeds(seeds=[StatementSeedItem(
            finding_id=ids[0],
            statements=[f"Run {runs['n']} statement A", f"Run {runs['n']} statement B", "Shared statement"],
        )])

    _configure(monkeypatch, answer)
    assembly = _assembly(client)
    _findings(assembly["id"], [("round", "proposal", "Buses", "APPROVED", 1)])
    url = f"/api/v1/assemblies/{assembly['id']}/seeds"
    client.post(f"{url}/generate")
    first = _wait(client, assembly["id"], _settled)["seeds"]
    a, b, shared = first
    # approve one, edit one, add one by hand, leave "shared" as an untouched draft
    approved = client.put(f"{url}/{a['id']}", json={"status": "APPROVED"})
    assert approved.status_code == 200 and approved.json()["reviewed_by"] == "tester"
    edited = client.put(f"{url}/{b['id']}", json={"text": "  Rewritten   by hand "})
    assert edited.json()["text"] == "Rewritten by hand" and edited.json()["edited"] is True
    manual = client.post(url, json={"text": "Manual statement"})
    assert manual.status_code == 201 and manual.json()["origin"] == "manual"
    assert manual.json()["position"] == 4
    too_long = client.post(url, json={"text": "x" * 401})
    assert too_long.status_code == 422

    assert client.post(f"{url}/generate").status_code == 202
    second = _wait(client, assembly["id"], lambda listing: _settled(listing) and runs["n"] == 2)["seeds"]
    texts = [s["text"] for s in second]
    assert "Run 1 statement A" in texts and "Rewritten by hand" in texts and "Manual statement" in texts
    assert "Shared statement" in texts and texts.count("Shared statement") == 1
    assert "Run 2 statement A" in texts and "Run 2 statement B" in texts
    assert "Run 1 statement B" not in texts
    # the kept ones come first, the new ones after
    assert texts.index("Manual statement") < texts.index("Run 2 statement A")

    # reorder: the named ids first, the rest keep their order after them
    ordered = client.put(f"{url}/order", json={"ids": [second[-1]["id"], second[0]["id"]]})
    assert ordered.status_code == 200
    positions = [(s["id"], s["position"]) for s in ordered.json()["seeds"]]
    assert positions[0] == (second[-1]["id"], 1) and positions[1] == (second[0]["id"], 2)
    assert client.put(f"{url}/order", json={"ids": ["nope"]}).status_code == 404

    # delete
    assert client.delete(f"{url}/{second[-1]['id']}").status_code == 204
    assert client.delete(f"{url}/{second[-1]['id']}").status_code == 404
    assert client.get(url).json()["seeds"][0]["position"] == 2


def test_export_waits_for_the_review_then_writes_csv_and_json(client, monkeypatch):
    assembly = _assembly(client, name="Comune di Prova, 2026")
    url = f"/api/v1/assemblies/{assembly['id']}/seeds"
    first = client.post(url, json={"text": 'Buses should run "late", every night'}).json()
    second = client.post(url, json={"text": "Bike lanes need lighting"}).json()
    third = client.post(url, json={"text": "A rejected idea"}).json()
    # manual seeds start as DRAFT: the organizer still decides
    assert client.get(f"{url}/export.csv").status_code == 409
    for seed, status in ((first, "APPROVED"), (second, "APPROVED")):
        client.put(f"{url}/{seed['id']}", json={"status": status})
    assert client.get(f"{url}/export.json").status_code == 409  # third still a draft
    client.put(f"{url}/{third['id']}", json={"status": "REJECTED"})
    assert client.get(url).json()["ready_to_export"] is True

    exported = client.get(f"{url}/export.csv")
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"].startswith("text/csv")
    assert exported.headers["cache-control"].startswith("no-store")
    assert 'filename="Comune-di-Prova,-2026-statements.csv"' in exported.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(exported.text)))
    assert rows == [["position", "statement"],
                    ["1", 'Buses should run "late", every night'],
                    ["2", "Bike lanes need lighting"]]

    exported = client.get(f"{url}/export.json")
    assert exported.status_code == 200
    body = json.loads(exported.content)
    assert body["schema"] == "citizens.statement-seeds/1"
    assert body["assembly"] == {"name": "Comune di Prova, 2026", "language": "en"}
    assert [s["statement"] for s in body["statements"]] == [
        'Buses should run "late", every night', "Bike lanes need lighting"]
    assert "A rejected idea" not in exported.text
    assert "-statements.json" in exported.headers["content-disposition"]

    listing = client.get(url).json()
    assert [s["status"] for s in listing["seeds"]] == ["EXPORTED", "EXPORTED", "REJECTED"]
    assert all(s["exported_at"] for s in listing["seeds"][:2])
    assert listing["ready_to_export"] is True  # a second download carries the same statements


def test_seeds_are_private_to_the_assembly_owner(client):
    assembly = _assembly(client)
    url = f"/api/v1/assemblies/{assembly['id']}/seeds"
    seed = client.post(url, json={"text": "Mine"}).json()
    other = {"X-Test-User": "someone-else"}
    assert client.get(url, headers=other).status_code == 404
    assert client.post(url, json={"text": "Theirs"}, headers=other).status_code == 404
    assert client.put(f"{url}/{seed['id']}", json={"status": "APPROVED"}, headers=other).status_code == 404
    assert client.delete(f"{url}/{seed['id']}", headers=other).status_code == 404
    assert client.get(f"{url}/export.csv", headers=other).status_code == 404
    # a seed id under another assembly's URL is not found either
    second = _assembly(client, name="TEST Other")
    assert client.put(
        f"/api/v1/assemblies/{second['id']}/seeds/{seed['id']}", json={"status": "APPROVED"}
    ).status_code == 404


def test_a_rerun_of_the_analysis_unlinks_the_seed_and_marks_it_stale(client):
    assembly = _assembly(client)
    (finding_id,) = _findings(assembly["id"], [("round", "proposal", "Buses", "APPROVED", 1)])
    with session_scope() as session:
        session.add(StatementSeed(
            assembly_id=assembly["id"], finding_id=finding_id, text="Buses should run later",
            source_text="Buses should run later", language="en", position=1, status="APPROVED",
        ))
    with session_scope() as session:
        round_id = session.get(Finding, finding_id).round_id
        analysis_svc._delete_existing(session, round_id=round_id, scope="round")
    listing = client.get(f"/api/v1/assemblies/{assembly['id']}/seeds").json()
    (seed,) = listing["seeds"]
    assert seed["finding_id"] is None and seed["stale"] is True
    assert seed["text"] == "Buses should run later" and seed["status"] == "APPROVED"
    # editing the text clears the flag
    fixed = client.put(
        f"/api/v1/assemblies/{assembly['id']}/seeds/{seed['id']}", json={"text": "Buses later"}
    )
    assert fixed.json()["stale"] is False


def test_a_permanent_model_failure_shows_on_the_listing(client, monkeypatch):
    from citizens.providers.analysis.openai_compat import AnalysisError

    def refuse(ids):
        raise AnalysisError("The model refused", permanent=True)

    _configure(monkeypatch, refuse)
    assembly = _assembly(client)
    _findings(assembly["id"], [("round", "proposal", "Buses", "APPROVED", 1)])
    url = f"/api/v1/assemblies/{assembly['id']}/seeds"
    assert client.post(f"{url}/generate").status_code == 202
    listing = _wait(client, assembly["id"], _settled)
    assert listing["job"]["state"] == "FAILED" and listing["seeds"] == []
    assert "refused" in listing["job"]["failure_detail"]


def test_migration_0040_downgrades_and_upgrades_cleanly(database):
    cfg = Config()
    cfg.set_main_option("script_location", str(Path("citizens/db/migrations").resolve()))
    cfg.set_main_option("sqlalchemy.url", sqlite_url(database.app_persistent_storage / "citizens.db"))
    command.downgrade(cfg, "0039")
    command.upgrade(cfg, "head")
    with session_scope() as session:
        assembly = Assembly(name="After", language="en", created_by="anna")
        session.add(assembly)
        session.flush()
        session.add(StatementSeed(assembly_id=assembly.id, text="Still here", source_text="Still here"))
    with session_scope() as session:
        assert session.query(StatementSeed).filter_by(text="Still here").count() == 1
