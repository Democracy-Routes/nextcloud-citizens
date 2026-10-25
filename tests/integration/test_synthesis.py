# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""How the discussion developed across sessions (0.7): produced by the
analysis model from the sessions' summaries once at least two have one,
stored on the assembly, printed after the executive summary in JSON,
Markdown and PDF, remade at closing."""

import time

from citizens.db.models import Assembly
from citizens.db.session import session_scope
from citizens.domain.analysis_schemas import AssemblySynthesis, SynthesisStage


class MemoryStore:
    def __init__(self, values=None):
        self.values = values or {}

    def get_value(self, key):
        return self.values.get(key)

    def set_value(self, key, value, sensitive=False):
        self.values[key] = value

    def delete_value(self, key):
        self.values.pop(key, None)


def _assembly(client, rounds=2):
    return client.post(
        "/api/v1/assemblies",
        json={"name": "TEST Synthesis", "default_table_count": 1,
              "rounds": [{"title": f"S{i}", "question": f"Q{i}"} for i in range(1, rounds + 1)]},
    ).json()


def _summarise(assembly_id, texts):
    with session_scope() as session:
        assembly = session.get(Assembly, assembly_id)
        for round_, text_ in zip(sorted(assembly.rounds, key=lambda r: r.position), texts, strict=False):
            round_.analysis_summary = text_


def _wait_for_synthesis(client, assembly_id, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        report = client.get(f"/api/v1/assemblies/{assembly_id}/report").json()
        if report.get("synthesis"):
            return report
        time.sleep(0.4)
    return client.get(f"/api/v1/assemblies/{assembly_id}/report").json()


def test_the_synthesis_is_written_from_the_sessions_and_printed_in_the_report(client, monkeypatch):
    store = MemoryStore({"analysis_api_key": "ak-test", "analysis_enabled": "1"})
    monkeypatch.setattr("citizens.services.provider_config.default_store", lambda: store)
    prompts: list[str] = []

    def fake_chat_json(base_url, key, model, system_prompt, user_prompt, schema):
        prompts.append(user_prompt)
        assert schema is AssemblySynthesis and key == "ak-test"
        return AssemblySynthesis(
            narrative="The first session listed problems; the second turned two of them into proposals.",
            stages=[SynthesisStage(title="Session 1", summary="Problems with buses and bike lanes."),
                    SynthesisStage(title="Session 2", summary="Two proposals on evening buses.")],
            carried_forward=["Evening bus service"],
        )

    monkeypatch.setattr("citizens.services.analysis.chat_json", fake_chat_json)
    assembly = _assembly(client)
    # too early: one summary only
    _summarise(assembly["id"], ["Problems with buses."])
    assert client.post(f"/api/v1/assemblies/{assembly['id']}/synthesis").status_code == 409
    assert client.get(f"/api/v1/assemblies/{assembly['id']}/report").json()["synthesis"] is None

    _summarise(assembly["id"], ["Problems with buses.", "Proposals on evening buses."])
    queued = client.post(f"/api/v1/assemblies/{assembly['id']}/synthesis")
    assert queued.status_code == 202, queued.text
    report = _wait_for_synthesis(client, assembly["id"])
    synthesis = report["synthesis"]
    assert synthesis and synthesis["narrative"].startswith("The first session listed problems")
    assert [s["title"] for s in synthesis["stages"]] == ["Session 1", "Session 2"]
    assert synthesis["carried_forward"] == ["Evening bus service"]
    assert "Session 1: S1" in prompts[-1] and "Proposals on evening buses." in prompts[-1]

    # closing remakes it and freezes it into what participants read
    prompts.clear()
    assert client.post(f"/api/v1/assemblies/{assembly['id']}/close").status_code == 200
    deadline = time.time() + 30
    while time.time() < deadline and not prompts:
        time.sleep(0.4)
    assert prompts, "closing queued the synthesis again"

    # the exports (final report, so after closing) carry the chapter
    markdown = client.get(f"/api/v1/assemblies/{assembly['id']}/report.md").text
    assert "## How the discussion developed" in markdown
    assert "Carried from one session to the next" in markdown and "- Evening bus service" in markdown
    pdf = client.get(f"/api/v1/assemblies/{assembly['id']}/report.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
