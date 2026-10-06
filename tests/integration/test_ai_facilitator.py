# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The AI facilitator (0.7): opt-in by level (instance default, assembly,
table override), one minute at a time from the sweep. It speaks only when
a trigger fires and the model has something to say; the advice goes to a
connected facilitator's phone (Dismiss / Send to table) and to the table's
phones only when none is; levels bound how often; thumbs down silence it;
the Live tab reads the log; nothing is called without a key."""

import re
from datetime import timedelta

from citizens.db.models.base import utcnow
from citizens.domain.analysis_schemas import FacilitatorAdvice
from citizens.services import facilitator as ai_svc
from citizens.services import provider_config

REAL_HISTORY = ai_svc._history

SETTINGS = {
    "level": "off", "configured": True, "own_key": False,
    "interval_minutes": 4, "dominance_percent": 60, "silence_seconds": 90,
}


def _assembly(client, **extra):
    created = client.post(
        "/api/v1/assemblies",
        json={
            "name": "TEST AI facilitator", "default_table_count": 2,
            "rounds": [{"title": "Problems", "question": "What is broken?",
                        "objective": "Three problems", "duration_minutes": 20}],
            **extra,
        },
    ).json()
    client.post(f"/api/v1/rounds/{created['rounds'][0]['id']}/start")
    return created


def _phone(client, assembly, index, ip="10.30.0.1"):
    token = re.search(r"#/join/(.+)$", assembly["invites"][index]["url"]).group(1)
    joined = client.post(
        "/api/v1/public/join", json={"token": token}, headers={"X-Forwarded-For": ip}
    ).json()
    headers = {"Authorization": f"Bearer {joined['session_token']}"}
    started = client.post(
        "/api/v1/public/recorder/start",
        json={"round_id": assembly["rounds"][0]["id"], "mime_type": "audio/webm"}, headers=headers,
    )
    assert started.status_code == 201, started.text
    return headers


def _facilitator(client, table_headers):
    card = client.post(
        "/api/v1/public/recorder/capabilities", json={"purpose": "FACILITATE_TABLE"},
        headers=table_headers,
    ).json()
    token = re.search(r"#/facilitate/(.+)$", card["url"]).group(1)
    joined = client.post("/api/v1/public/facilitate", json={"token": token}).json()
    return {"Authorization": f"Bearer {joined['facilitator_token']}"}


def _captions(monkeypatch, count=12, speaker=None):
    lines = [
        {"t": 10.0 * i, "end": 10.0 * i + 6, "text": f"Someone said thing {i}.", "speaker": speaker}
        for i in range(count)
    ]
    monkeypatch.setattr(ai_svc, "_lines_for", lambda recording_id: lines)
    return lines


def _wire(monkeypatch, level="normal", advice=None, calls=None):
    settings = {**SETTINGS, "level": level}
    monkeypatch.setattr(provider_config, "facilitator_settings_cached", lambda: settings)
    monkeypatch.setattr(
        provider_config, "facilitator_model_config",
        lambda store: ("https://llm.example/v1", "fk-test", "small-model"),
    )
    calls = calls if calls is not None else []

    def fake_chat_json(base_url, key, model, system_prompt, user_prompt, schema):
        calls.append(user_prompt)
        assert schema is FacilitatorAdvice and key == "fk-test" and model == "small-model"
        return advice or FacilitatorAdvice(kind="objective", text="What would make your list of three?")

    monkeypatch.setattr(ai_svc, "chat_json", fake_chat_json)
    return calls


def test_off_by_default_and_a_level_turns_it_on(client, monkeypatch):
    assembly = _assembly(client)
    table1 = _phone(client, assembly, 0)
    _captions(monkeypatch)
    calls = _wire(monkeypatch, level="off")
    assert ai_svc.tick() == 0 and calls == []

    # the assembly opts in: the table's phones get a banner labelled "AI facilitator"
    updated = client.put(f"/api/v1/assemblies/{assembly['id']}", json={"ai_facilitator": "normal"})
    assert updated.status_code == 200 and updated.json()["ai_facilitator"] == "normal"
    assert updated.json()["ai_facilitator_default"] == "off"
    assert ai_svc.tick() == 1
    assert "Question: What is broken?" in calls[-1] and "Objective: Three problems" in calls[-1]
    assert "Someone said thing 11." in calls[-1] and "content" in calls[-1]
    status = client.get("/api/v1/public/recorder/status", headers=table1).json()
    assert [m["author"] for m in status["messages"]] == ["ai"]
    assert status["messages"][0]["text"] == "What would make your list of three?"
    assert status["ai_facilitator"]["level"] == "normal"

    # the interval holds it back; the Live tab's log has the one intervention
    assert ai_svc.tick() == 0
    log = client.get(f"/api/v1/rounds/{assembly['rounds'][0]['id']}/interventions").json()
    assert len(log) == 1 and log[0]["delivered_to"] == "table" and log[0]["kind"] == "objective"
    assert log[0]["feedback"] == {"helpful": 0, "not_helpful": 0}

    # 👍 from the table's phone
    thumbs = client.post(
        f"/api/v1/public/recorder/messages/{status['messages'][0]['id']}/feedback",
        json={"helpful": True}, headers=table1,
    )
    assert thumbs.status_code == 200
    log = client.get(f"/api/v1/rounds/{assembly['rounds'][0]['id']}/interventions").json()
    assert log[0]["feedback"] == {"helpful": 1, "not_helpful": 0}
    # a plain organizer message takes no thumbs
    message = client.post(
        f"/api/v1/rounds/{assembly['rounds'][0]['id']}/messages", json={"kind": "WRAP_UP"}
    ).json()
    assert client.post(
        f"/api/v1/public/recorder/messages/{message['id']}/feedback", json={"helpful": True},
        headers=table1,
    ).status_code == 404


def test_the_facilitators_phone_gets_the_advice_first_and_decides(client, monkeypatch):
    assembly = _assembly(client, ai_facilitator="active")
    table1 = _phone(client, assembly, 0)
    facilitator = _facilitator(client, table1)
    _captions(monkeypatch)
    _wire(monkeypatch, level="off")  # the assembly's own level wins over the instance's
    assert ai_svc.tick() == 1

    # nothing reached the table; the card is on the facilitator's phone
    assert client.get("/api/v1/public/recorder/status", headers=table1).json()["messages"] == []
    status = client.get("/api/v1/public/facilitator/status", headers=facilitator).json()
    assert status["capabilities"]["ai_facilitator"] is True
    assert len(status["advice"]) == 1 and status["advice"][0]["kind"] == "objective"
    advice_id = status["advice"][0]["id"]

    # 👎 then dismiss: gone from the phone, counted in the log
    assert client.post(
        f"/api/v1/public/facilitator/advice/{advice_id}/feedback", json={"helpful": False},
        headers=facilitator,
    ).status_code == 200
    assert client.post(
        f"/api/v1/public/facilitator/advice/{advice_id}/dismiss", headers=facilitator
    ).status_code == 200
    status = client.get("/api/v1/public/facilitator/status", headers=facilitator).json()
    assert status["advice"] == []
    log = client.get(f"/api/v1/rounds/{assembly['rounds'][0]['id']}/interventions").json()
    assert log[0]["dismissed_at"] and log[0]["feedback"]["not_helpful"] == 1

    # a second piece of advice, sent on to the table as the facilitator's own prompt
    monkeypatch.setattr(ai_svc, "_history", lambda *a, **k: [])
    assert ai_svc.tick() == 1
    status = client.get("/api/v1/public/facilitator/status", headers=facilitator).json()
    advice_id = status["advice"][0]["id"]
    sent = client.post(f"/api/v1/public/facilitator/advice/{advice_id}/send", headers=facilitator)
    assert sent.status_code == 201 and sent.json()["sent_to_table_at"]
    messages = client.get("/api/v1/public/recorder/status", headers=table1).json()["messages"]
    assert [m["author"] for m in messages] == ["facilitator"]
    assert messages[0]["text"] == "What would make your list of three?"


def test_quiet_when_the_model_says_none_or_fails_and_the_balance_needs_figures(client, monkeypatch):
    assembly = _assembly(client, ai_facilitator="normal")
    table1 = _phone(client, assembly, 0)
    _captions(monkeypatch)
    _wire(monkeypatch, advice=FacilitatorAdvice(kind="none", text=""))
    assert ai_svc.tick() == 0
    # no figures were given, so a balance nudge is refused
    _wire(monkeypatch, advice=FacilitatorAdvice(kind="balance", text="Let us hear other voices."))
    assert ai_svc.tick() == 0

    def boom(*args, **kwargs):
        raise RuntimeError("model down")

    monkeypatch.setattr(ai_svc, "chat_json", boom)
    assert ai_svc.tick() == 0
    assert client.get("/api/v1/public/recorder/status", headers=table1).json()["messages"] == []


def test_balance_nudge_only_with_labelled_speakers_and_dominance(client, monkeypatch):
    assembly = _assembly(client, ai_facilitator="normal")
    _phone(client, assembly, 0)
    # one voice speaks nine lines of ten, labelled by the engine
    lines = [
        {"t": 10.0 * i, "end": 10.0 * i + 8, "text": f"Line {i}", "speaker": 0 if i != 5 else 1}
        for i in range(10)
    ]
    monkeypatch.setattr(ai_svc, "_lines_for", lambda recording_id: lines)
    calls = _wire(monkeypatch, advice=FacilitatorAdvice(kind="balance", text="Has everyone had a turn?"))
    assert ai_svc.tick() == 1
    assert "Voice A 90%" in calls[-1] and "balance" in calls[-1]


def test_levels_bound_how_often_and_thumbs_down_silence_it(client, monkeypatch):
    assembly = _assembly(client, ai_facilitator="light")
    table1 = _phone(client, assembly, 0)
    _captions(monkeypatch, count=30)
    _wire(monkeypatch)
    monkeypatch.setattr(ai_svc, "_history", lambda session, round_id, table_number: [])
    assert ai_svc.tick() == 1
    assert ai_svc.tick() == 1
    # the real history now holds two: Light allows no more
    monkeypatch.setattr(ai_svc, "_history", REAL_HISTORY)
    now = utcnow() + timedelta(minutes=10)
    assert ai_svc.tick(now) == 0

    # the table switches it off from its own phone
    switched = client.post(
        "/api/v1/public/recorder/facilitator", json={"level": "off"}, headers=table1
    )
    assert switched.status_code == 200 and switched.json()["override"] == "off"
    status = client.get("/api/v1/public/recorder/status", headers=table1).json()
    assert status["ai_facilitator"]["level"] == "off"
    # ...and back to the assembly's level; the organizer pauses it from the Live tab
    assert client.post(
        "/api/v1/public/recorder/facilitator", json={"level": "default"}, headers=table1
    ).json()["level"] == "light"
    paused = client.post(
        f"/api/v1/assemblies/{assembly['id']}/tables/1/facilitation", json={"level": "off"}
    )
    assert paused.status_code == 200 and paused.json()["level"] == "off"


def test_three_not_helpful_thumbs_silence_a_table(client, monkeypatch):
    assembly = _assembly(client, ai_facilitator="active")
    table1 = _phone(client, assembly, 0)
    _captions(monkeypatch, count=30)
    _wire(monkeypatch)
    ids = []
    for _ in range(3):
        monkeypatch.setattr(ai_svc, "_history", lambda session, round_id, table_number: [])
        assert ai_svc.tick() == 1
        status = client.get("/api/v1/public/recorder/status", headers=table1).json()
        message_id = status["messages"][-1]["id"]
        ids.append(message_id)
        client.post("/api/v1/public/recorder/messages/seen", json={"message_id": message_id}, headers=table1)
        client.post(
            f"/api/v1/public/recorder/messages/{message_id}/feedback", json={"helpful": False},
            headers=table1,
        )
    assert len(set(ids)) == 3
    monkeypatch.setattr(ai_svc, "_history", lambda session, round_id, table_number: [])
    assert ai_svc.tick() == 0


def test_no_key_no_call(client, monkeypatch):
    assembly = _assembly(client, ai_facilitator="normal")
    _phone(client, assembly, 0)
    _captions(monkeypatch)
    calls = _wire(monkeypatch)
    monkeypatch.setattr(
        provider_config, "facilitator_model_config", lambda store: ("https://llm", "", "m")
    )
    assert ai_svc.tick() == 0 and calls == []
