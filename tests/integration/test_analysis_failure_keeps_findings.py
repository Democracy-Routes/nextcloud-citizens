# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A failed re-analysis must leave the existing findings alone.

Re-analysis used to delete the drafts and commit BEFORE calling the model. A
permanent failure — a rotated API key answering 401, or output that fails
schema validation three times — raises PermanentJobError, and the job runner
deliberately does not roll back on that. So the delete stood: the organizer
pressed "Re-run analysis", the provider refused, and a round that had twelve
findings had none, with nothing regenerated and no way back.

The delete now happens after the model answers, in the same transaction as the
inserts, so re-analysis either replaces the findings or leaves them untouched.
"""

import pytest
from sqlalchemy import select

from citizens.db.models import Finding
from citizens.db.models.assembly import Assembly, Round, Table
from citizens.db.models.recording import Recording
from citizens.db.session import session_scope
from citizens.services import analysis as analysis_svc
from citizens.services.analysis import AnalysisError


@pytest.fixture
def seeded(client, settings_env):
    """An assembly with a transcript and one existing DRAFT finding."""
    from citizens.db.models.transcript import Transcript, TranscriptSegment

    assembly = client.post(
        "/api/v1/assemblies",
        json={
            "name": "TEST Analysis Failure",
            "default_table_count": 1,
            "rounds": [{"title": "R1", "question": "Q?", "duration_minutes": 30}],
        },
    ).json()
    with session_scope() as session:
        db_assembly = session.get(Assembly, assembly["id"])
        round_ = session.execute(
            select(Round).where(Round.assembly_id == db_assembly.id)
        ).scalar_one()
        table = session.execute(
            select(Table).where(Table.round_id == round_.id, Table.number == 1)
        ).scalar_one()
        recording = Recording(
            assembly_id=db_assembly.id,
            round_id=round_.id,
            table_id=table.id,
            table_number=1,
            state="TRANSCRIBED",
            mime_type="audio/webm",
        )
        session.add(recording)
        session.flush()
        transcript = Transcript(recording_id=recording.id, language="en", provider="test")
        session.add(transcript)
        session.flush()
        session.add(
            TranscriptSegment(
                transcript_id=transcript.id,
                sequence=0,
                start_seconds=0.0,
                end_seconds=4.0,
                text="We should widen the cycle lanes on Via Zamboni.",
                speaker_label="SPEAKER",
            )
        )
        session.add(
            Finding(
                assembly_id=db_assembly.id,
                round_id=round_.id,
                recording_id=recording.id,
                scope="table",
                type="proposal",
                title="An existing draft the organizer has not reviewed yet",
                summary="Widen the cycle lanes.",
                status="DRAFT",
            )
        )
        session.flush()
        return {"assembly_id": db_assembly.id, "round_id": round_.id, "recording_id": recording.id}


def _findings(recording_id):
    with session_scope() as session:
        return list(
            session.execute(
                select(Finding).where(Finding.recording_id == recording_id)
            ).scalars()
        )


def test_a_permanent_model_failure_keeps_the_existing_table_findings(seeded, monkeypatch):
    assert len(_findings(seeded["recording_id"])) == 1

    def refuse(*_args, **_kwargs):
        raise AnalysisError("401 Unauthorized", permanent=True)

    monkeypatch.setattr(analysis_svc, "chat_json", refuse)
    monkeypatch.setattr(
        analysis_svc, "_analysis_config", lambda _store: ("http://x", "k", "m")
    )
    monkeypatch.setattr(
        analysis_svc, "build_system_prompt", lambda *_a, **_k: "system prompt"
    )

    with session_scope() as session:
        recording = session.get(Recording, seeded["recording_id"])
        with pytest.raises(AnalysisError):
            analysis_svc.analyze_table(session, object(), recording)

    survivors = _findings(seeded["recording_id"])
    assert len(survivors) == 1, (
        "the model refused and the existing draft was destroyed anyway — "
        "re-analysis must replace findings only when it has something to "
        "replace them with"
    )
    assert survivors[0].title.startswith("An existing draft")


def test_a_permanent_round_failure_keeps_the_existing_clusters(seeded, monkeypatch):
    """Same ordering bug in the cross-table pass."""
    with session_scope() as session:
        session.add(
            Finding(
                assembly_id=seeded["assembly_id"],
                round_id=seeded["round_id"],
                scope="round",
                type="agreement",
                title="An existing cross-table cluster",
                summary="Tables agreed about cycle lanes.",
                status="DRAFT",
            )
        )

    def refuse(*_args, **_kwargs):
        raise AnalysisError("401 Unauthorized", permanent=True)

    monkeypatch.setattr(analysis_svc, "chat_json", refuse)
    monkeypatch.setattr(
        analysis_svc, "_analysis_config", lambda _store: ("http://x", "k", "m")
    )
    monkeypatch.setattr(
        analysis_svc, "build_system_prompt", lambda *_a, **_k: "system prompt"
    )

    with session_scope() as session:
        round_ = session.get(Round, seeded["round_id"])
        with pytest.raises(AnalysisError):
            analysis_svc.analyze_round(session, object(), round_)

    with session_scope() as session:
        clusters = list(
            session.execute(
                select(Finding).where(
                    Finding.round_id == seeded["round_id"], Finding.scope == "round"
                )
            ).scalars()
        )
    assert len(clusters) == 1, "the round's existing clusters were destroyed by a failure"


def test_findings_are_deleted_only_after_the_model_answers():
    """The ordering itself, so a refactor cannot quietly reintroduce this."""
    import inspect

    for function in (analysis_svc.analyze_table, analysis_svc.analyze_round):
        source = inspect.getsource(function)
        model_call = source.index("chat_json(")
        # the replacing delete is the last one in the body; an earlier delete
        # inside the "nothing to analyse" branch is deliberate and safe
        assert source.rindex("_delete_existing(") > model_call, (
            f"{function.__name__} deletes findings before calling the model — a "
            "permanent provider failure would destroy them with no replacement"
        )
