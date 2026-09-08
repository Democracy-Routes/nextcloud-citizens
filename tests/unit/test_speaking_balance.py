# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""How much each voice spoke, measured honestly from one recording.

Diarization labels are consistent only within a single recording, so the
balance is taken from the recording that captured the most speech — never
reconciled across devices. These tests pin that choice, the anonymised A/B/C
labelling, the tail-into-"Others" fold, and the "no speech → None" case.
"""

from sqlalchemy import select

from citizens.db.models import Recording
from citizens.db.models.assembly import Round, Table
from citizens.db.models.base import utcnow
from citizens.db.models.transcript import Transcript, TranscriptSegment
from citizens.db.session import session_scope
from citizens.services.speaking import round_speaking_balance


def _assembly(client, tables=1):
    return client.post(
        "/api/v1/assemblies",
        json={
            "name": "TEST Speaking Balance",
            "default_table_count": tables,
            "rounds": [{"title": "R1", "question": "What should change?", "duration_minutes": 30}],
        },
    ).json()


def _recording(session, assembly_id, round_, table, table_number, index):
    rec = Recording(
        assembly_id=assembly_id,
        round_id=round_.id,
        table_id=table.id,
        table_number=table_number,
        state="TRANSCRIBED",
        mime_type="audio/webm",
        canonical_audio_path=f"assembled/{assembly_id}/rec{index}.webm",
        started_at=utcnow(),
    )
    session.add(rec)
    session.flush()
    transcript = Transcript(recording_id=rec.id, language="en", provider="test")
    session.add(transcript)
    session.flush()
    return rec, transcript


def _segments(session, transcript_id, spans):
    """spans: list of (speaker_label, start, end)."""
    for seq, (speaker, start, end) in enumerate(spans):
        session.add(
            TranscriptSegment(
                transcript_id=transcript_id, sequence=seq,
                start_seconds=start, end_seconds=end, text=f"line {seq}",
                speaker_label=speaker,
            )
        )


def _round_and_table(session, assembly_id, number=1):
    round_ = session.execute(
        select(Round).where(Round.assembly_id == assembly_id)
    ).scalar_one()
    table = session.execute(
        select(Table).where(Table.round_id == round_.id, Table.number == number)
    ).scalar_one()
    return round_, table


def test_no_transcribed_speech_returns_none(client):
    assembly = _assembly(client)
    with session_scope() as session:
        round_, _ = _round_and_table(session, assembly["id"])
        assert round_speaking_balance(session, round_) is None


def test_picks_the_recording_with_the_most_speech(client):
    assembly = _assembly(client)
    with session_scope() as session:
        round_, table = _round_and_table(session, assembly["id"])
        # thin recording: 3s of one voice
        _, thin = _recording(session, assembly["id"], round_, table, 1, 0)
        _segments(session, thin.id, [("SPEAKER_00", 0.0, 3.0)])
        # full recording: 30s across two voices — this one must be chosen
        full_rec, full = _recording(session, assembly["id"], round_, table, 1, 1)
        _segments(session, full.id, [
            ("SPEAKER_00", 0.0, 20.0),
            ("SPEAKER_01", 20.0, 30.0),
        ])
        session.flush()

        balance = round_speaking_balance(session, round_)

    assert balance is not None
    assert balance["from_recording_id"] == full_rec.id
    assert balance["total_seconds"] == 30.0
    # loudest voice first, relabelled to A/B, never the raw SPEAKER_xx
    assert [v["label"] for v in balance["voices"]] == ["A", "B"]
    assert [v["percent"] for v in balance["voices"]] == [67, 33]
    assert sum(v["percent"] for v in balance["voices"]) == 100


def test_percentages_always_sum_to_100(client):
    # three thirds: 33 + 33 + 33 = 99 without largest-remainder correction
    assembly = _assembly(client)
    with session_scope() as session:
        round_, table = _round_and_table(session, assembly["id"])
        _, t = _recording(session, assembly["id"], round_, table, 1, 0)
        _segments(session, t.id, [
            ("A", 0.0, 10.0), ("B", 10.0, 20.0), ("C", 20.0, 30.0),
        ])
        session.flush()
        balance = round_speaking_balance(session, round_)

    assert sum(v["percent"] for v in balance["voices"]) == 100


def test_the_quietest_voices_fold_into_others(client):
    # eight distinct voices; only six get their own slice, the rest are "Others"
    assembly = _assembly(client)
    with session_scope() as session:
        round_, table = _round_and_table(session, assembly["id"])
        _, t = _recording(session, assembly["id"], round_, table, 1, 0)
        spans = []
        # give voice i a duration of (10 - i)s so ranking is deterministic
        for i in range(8):
            start = float(i * 20)
            spans.append((f"SPEAKER_{i:02d}", start, start + (10 - i)))
        _segments(session, t.id, spans)
        session.flush()
        balance = round_speaking_balance(session, round_)

    labels = [v["label"] for v in balance["voices"]]
    assert labels == ["A", "B", "C", "D", "E", "F", "Others"]
    assert sum(v["percent"] for v in balance["voices"]) == 100


def test_the_report_payload_carries_the_round_balance(client):
    """The exports read speaking_balance straight off the round dict."""
    from citizens.db.models.assembly import Assembly as AssemblyModel
    from citizens.services.report import build_report

    assembly = _assembly(client)
    with session_scope() as session:
        round_, table = _round_and_table(session, assembly["id"])
        _, t = _recording(session, assembly["id"], round_, table, 1, 0)
        _segments(session, t.id, [
            ("SPEAKER_00", 0.0, 20.0),
            ("SPEAKER_01", 20.0, 30.0),
        ])
        session.flush()

        report = build_report(session, session.get(AssemblyModel, assembly["id"]))

    balance = report["rounds"][0]["speaking_balance"]
    assert balance is not None
    assert [v["label"] for v in balance["voices"]] == ["A", "B"]
