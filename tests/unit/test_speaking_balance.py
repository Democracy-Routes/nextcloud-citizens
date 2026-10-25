# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""How much each voice spoke at a table, measured honestly from one recording.

Diarization labels are consistent only within a single recording, so the
balance is taken from the table's recording that captured the most speech —
never reconciled across devices, never aggregated across tables. These tests
pin that scope, the anonymised A/B/C labelling, the tail-into-"Others" fold,
the "no speech → None" case, and the caveat when a replaced phone left parts.
"""

from sqlalchemy import select

from citizens.db.models import Recording
from citizens.db.models.assembly import Round, Table
from citizens.db.models.base import utcnow
from citizens.db.models.transcript import Transcript, TranscriptSegment
from citizens.db.session import session_scope
from citizens.services.speaking import round_speaking_comparison, table_speaking_balance


def test_the_comparison_sets_the_tables_side_by_side(client):
    """One line per table with a measured balance: voices, largest and
    smallest share, their ratio — nothing summed across tables."""
    assembly = _assembly(client, tables=3)
    with session_scope() as session:
        round_, t1 = _round_and_table(session, assembly["id"], 1)
        _, t2 = _round_and_table(session, assembly["id"], 2)
        _, tr1 = _recording(session, assembly["id"], round_, t1, 1, 0)
        _segments(session, tr1.id, [("SPEAKER_00", 0, 60), ("SPEAKER_01", 60, 70), ("SPEAKER_02", 70, 80)])
        _, tr2 = _recording(session, assembly["id"], round_, t2, 2, 1)
        _segments(session, tr2.id, [("SPEAKER_00", 0, 30), ("SPEAKER_01", 30, 60)])
        rows = round_speaking_comparison(session, round_)
    assert [row["table_number"] for row in rows] == [1, 2]  # table 3 recorded nothing
    assert rows[0]["voices"] == 3 and rows[0]["largest_percent"] == 75 and rows[0]["ratio"] == 6.0
    assert rows[1]["voices"] == 2 and rows[1]["largest_percent"] == 50 and rows[1]["ratio"] == 1.0


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
        round_, table = _round_and_table(session, assembly["id"])
        assert table_speaking_balance(session, round_, table) is None


def test_picks_the_tables_recording_with_the_most_speech_and_says_the_phone_changed(client):
    assembly = _assembly(client)
    with session_scope() as session:
        round_, table = _round_and_table(session, assembly["id"])
        # thin recording: 3s of one voice (the part before the phone died)
        _, thin = _recording(session, assembly["id"], round_, table, 1, 0)
        _segments(session, thin.id, [("SPEAKER_00", 0.0, 3.0)])
        # full recording: 30s across two voices — this one must be chosen
        full_rec, full = _recording(session, assembly["id"], round_, table, 1, 1)
        _segments(session, full.id, [
            ("SPEAKER_00", 0.0, 20.0),
            ("SPEAKER_01", 20.0, 30.0),
        ])
        session.flush()

        balance = table_speaking_balance(session, round_, table)

    assert balance is not None
    assert balance["from_recording_id"] == full_rec.id
    assert balance["total_seconds"] == 30.0
    # loudest voice first, relabelled to A/B, never the raw SPEAKER_xx
    assert [v["label"] for v in balance["voices"]] == ["A", "B"]
    assert [v["percent"] for v in balance["voices"]] == [67, 33]
    assert sum(v["percent"] for v in balance["voices"]) == 100
    # two parts held speech: the reader is told voices were not matched across them
    assert balance["parts"] == 2 and balance["recorder_changed"] is True


def test_a_single_recording_is_not_flagged_as_a_changed_phone(client):
    assembly = _assembly(client)
    with session_scope() as session:
        round_, table = _round_and_table(session, assembly["id"])
        _, t = _recording(session, assembly["id"], round_, table, 1, 0)
        _segments(session, t.id, [("A", 0.0, 10.0), ("B", 10.0, 20.0)])
        session.flush()
        balance = table_speaking_balance(session, round_, table)
    assert balance["parts"] == 1 and balance["recorder_changed"] is False


def test_each_table_gets_its_own_balance_never_the_rounds(client):
    """The old round-level metric picked one recording across the whole round
    and printed it as if it described every table."""
    assembly = _assembly(client, tables=2)
    with session_scope() as session:
        round_, table1 = _round_and_table(session, assembly["id"], 1)
        _, table2 = _round_and_table(session, assembly["id"], 2)
        _, t1 = _recording(session, assembly["id"], round_, table1, 1, 0)
        _segments(session, t1.id, [("S0", 0.0, 10.0), ("S1", 10.0, 20.0), ("S2", 20.0, 30.0)])
        _, t2 = _recording(session, assembly["id"], round_, table2, 2, 1)
        _segments(session, t2.id, [("S0", 0.0, 90.0), ("S1", 90.0, 100.0)])
        session.flush()
        one = table_speaking_balance(session, round_, table1)
        two = table_speaking_balance(session, round_, table2)

    assert [v["percent"] for v in one["voices"]] == [34, 33, 33]
    assert [v["percent"] for v in two["voices"]] == [90, 10]
    assert one["total_seconds"] == 30.0 and two["total_seconds"] == 100.0


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
        balance = table_speaking_balance(session, round_, table)

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
        balance = table_speaking_balance(session, round_, table)

    labels = [v["label"] for v in balance["voices"]]
    assert labels == ["A", "B", "C", "D", "E", "F", "Others"]
    assert sum(v["percent"] for v in balance["voices"]) == 100


def test_the_report_payload_carries_the_balance_under_its_table(client):
    """The exports read speaking_balance off each table, never off the round."""
    from citizens.db.models.assembly import Assembly as AssemblyModel
    from citizens.services.report import build_report, render_markdown

    assembly = _assembly(client, tables=2)
    with session_scope() as session:
        round_, table = _round_and_table(session, assembly["id"])
        _, t = _recording(session, assembly["id"], round_, table, 1, 0)
        _segments(session, t.id, [
            ("SPEAKER_00", 0.0, 20.0),
            ("SPEAKER_01", 20.0, 30.0),
        ])
        session.flush()

        report = build_report(session, session.get(AssemblyModel, assembly["id"]))

    round_payload = report["rounds"][0]
    assert "speaking_balance" not in round_payload
    [table1] = [t for t in round_payload["tables"] if t["table_number"] == 1]
    assert [v["label"] for v in table1["speaking_balance"]["voices"]] == ["A", "B"]
    assert not any(t["table_number"] == 2 for t in round_payload["tables"])
    md = render_markdown(report)
    assert md.index("### Table 1") < md.index("**Speaking balance**")

    # the Analysis tab reads the same shape
    findings = client.get(f"/api/v1/rounds/{round_.id}/findings").json()
    assert "speaking_balance" not in findings
    by_number = {t["table_number"]: t["speaking_balance"] for t in findings["tables"]}
    assert [v["label"] for v in by_number[1]["voices"]] == ["A", "B"]
    assert by_number[2] is None
