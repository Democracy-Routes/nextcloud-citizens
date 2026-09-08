# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Assembly report: approved findings with evidence references (brief §42)."""

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from citizens.db.models import (
    Assembly,
    Finding,
    Participant,
    Recording,
    Transcript,
    TranscriptSegment,
)
from citizens.services.recording import assembly_progress as progress
from citizens.services.speaking import round_speaking_balance

METHODOLOGY_NOTE = (
    "AI was used to assist transcription and analysis. "
    "Findings were reviewed by a human organizer; discussion summaries are "
    "AI-generated neutral descriptions. "
    "“Mentioned at N tables” describes how many discussion tables raised a topic; "
    "it is not a measure of participant support."
)

# deliberation-report vocabulary; the fixed order groups cross-table findings
# in reports (institutional reading order, divergence highlighted)
TYPE_ORDER = (
    "proposal", "agreement", "disagreement", "concern",
    "question", "minority_position", "new_idea",
)

TYPE_LABELS = {
    "proposal": "Proposals",
    "agreement": "Points of consensus",
    "disagreement": "Points of divergence",
    "concern": "Concerns raised",
    "question": "Open questions",
    "minority_position": "Minority positions",
    "new_idea": "Emerging ideas",
}

TYPE_LABELS_SINGULAR = {
    "proposal": "Proposal",
    "agreement": "Point of consensus",
    "disagreement": "Point of divergence",
    "concern": "Concern",
    "question": "Open question",
    "minority_position": "Minority position",
    "new_idea": "Emerging idea",
}


def group_findings_by_type(findings: list[dict]) -> list[tuple[str, str, list[dict]]]:
    """(type, plural label, findings) groups in the institutional order."""
    groups = []
    for type_ in TYPE_ORDER:
        matching = [f for f in findings if f["type"] == type_]
        if matching:
            groups.append((type_, TYPE_LABELS[type_], matching))
    leftover = [f for f in findings if f["type"] not in TYPE_ORDER]
    if leftover:
        groups.append(("other", "Other findings", leftover))
    return groups

APPROVED = ("APPROVED", "EDITED_AND_APPROVED")


def _timestamp(seconds: float) -> str:
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


def _has_speaker_labels(session: Session, assembly: Assembly) -> bool:
    """True when at least one transcript segment names a speaker."""
    return (
        session.execute(
            select(TranscriptSegment.id)
            .join(Transcript, Transcript.id == TranscriptSegment.transcript_id)
            .join(Recording, Recording.id == Transcript.recording_id)
            .where(Recording.assembly_id == assembly.id, TranscriptSegment.speaker_label != "")
            .limit(1)
        ).first()
        is not None
    )


LIVE_TRANSCRIPT_NOTE = (
    " This assembly's transcripts come from the live captions produced while "
    "the tables were speaking, not from a separate transcription of the "
    "complete recordings. Captions are made under time pressure and can miss "
    "speech the engine could not keep up with, so passages may be absent or "
    "less accurate than the audio itself."
)


DEVICE_REPLACED_NOTE = (
    " At least one table's phone stopped working during a round and the "
    "discussion continued on another device. Both parts were transcribed and "
    "analysed together as one conversation; a short stretch between them was "
    "not recorded."
)


#: Quotes printed under a finding. Five is what fits without the citation
#: swamping the finding it supports.
def round_heading(position: int, title: str) -> str:
    """How a round is named wherever it is shown.

    The app manufactures its own redundancy here: both round-creation paths
    pre-fill the title with "Round N", so an organizer who edits it to
    "Round 1 - design" gets "Round 1 — Round 1 - design" on every screen and in
    every export. When the title already opens with this round's number, it is
    the whole heading.
    """
    name = (title or "").strip()
    if not name:
        return f"Round {position}"
    first = name.split()[0].rstrip(".:-–—") if name.split() else ""
    if name.lower().startswith(f"round {position}") or first == str(position):
        return name
    return f"Round {position} — {name}"


#: Quotes printed under a finding. Five is what fits without the citation
#: swamping the finding it supports.
MAX_QUOTES = 5

#: An utterance shorter than this says nothing on its own. "Yes.", "Also…" and
#: "And so this is cool." were all printed as evidence for real findings in a
#: real report — a citation a reader can check and find empty damages the claim
#: more than no citation would.
MIN_QUOTE_CHARS = 25


def _cross_table_evidence(
    session: Session, finding: Finding, table_numbers: dict[str, int]
) -> list[dict]:
    """Quotes for a cross-table finding, borrowed from the table findings it
    clustered and labelled with the table each came from.

    A round-scope finding stores no evidence of its own — only
    `source_finding_ids`, the table findings it aggregated. Those findings and
    their evidence survive (analyze_round deletes only round drafts), so the
    honest evidence for "this recurred across tables" is a sample of the
    supporting quotes from each contributing table. One best quote per table,
    round-robin, so no single table dominates the citation.

    Fetched by id rather than from build_report's preloaded set: a source table
    finding may still be a draft while this cross-table finding is approved, so
    it is not necessarily in the loaded findings.
    """
    try:
        source_ids = json.loads(finding.source_finding_ids or "[]")
    except ValueError:
        return []
    if not source_ids:
        return []
    sources = session.execute(
        select(Finding).where(Finding.id.in_(source_ids)).options(selectinload(Finding.evidence))
    ).scalars().all()
    segment_ids = {e.transcript_segment_id for f in sources for e in f.evidence}
    segments = {
        s.id: s
        for s in session.execute(
            select(TranscriptSegment).where(TranscriptSegment.id.in_(segment_ids))
        ).scalars()
    } if segment_ids else {}

    # best-first segments per contributing table (substance, then chronology)
    per_table: dict[int, list[TranscriptSegment]] = {}
    for source in sources:
        number = table_numbers.get(source.table_id or "")
        if number is None:
            continue
        cited = [segments[e.transcript_segment_id] for e in source.evidence
                 if e.transcript_segment_id in segments]
        if not cited:
            continue
        substantial = [c for c in cited if len(c.text.strip()) >= MIN_QUOTE_CHARS] or cited
        ranked = sorted(substantial, key=lambda c: len(c.text.strip()), reverse=True)
        per_table[number] = sorted(ranked, key=lambda c: c.start_seconds)

    # round-robin across tables, in table order, until MAX_QUOTES
    chosen: list[tuple[int, TranscriptSegment]] = []
    cursors = {number: 0 for number in per_table}
    while len(chosen) < MAX_QUOTES and any(
        cursors[number] < len(per_table[number]) for number in per_table
    ):
        for number in sorted(per_table):
            if cursors[number] < len(per_table[number]) and len(chosen) < MAX_QUOTES:
                chosen.append((number, per_table[number][cursors[number]]))
                cursors[number] += 1
    return [
        {
            "table_number": number,
            "segment_id": segment.id,
            "speaker": segment.speaker_label,
            "start": segment.start_seconds,
            "end": segment.end_seconds,
            "timestamp": _timestamp(segment.start_seconds),
            "text": segment.text,
        }
        for number, segment in chosen
    ]


def _quotes(cited: list[TranscriptSegment]) -> list[dict]:
    """The excerpts printed under a finding, best first-to-last.

    Two bugs met here. FindingEvidence has no ordering column and the
    relationship declares no order_by, so rows came back in insertion order —
    and they are inserted over `sorted(evidence_ids)`, which sorts random
    UUIDs. Truncating that with [:5] printed five ARBITRARY quotes in an
    arbitrary order, which is why the timestamps ran 04:35, 09:59, 04:25.

    So: prefer excerpts that carry something, then read them back in the order
    they were said. Substance is chosen first and chronology restored after,
    because choosing chronologically would just print the first five.

    Sorted within a transcript, not across: start_seconds is relative to its own
    recording, and a table that changed device mid-round has two timelines that
    would interleave wrongly.
    """
    def spoken_order(segment: TranscriptSegment) -> tuple:
        return (segment.transcript_id, segment.start_seconds)

    substantial = [s for s in cited if len(s.text.strip()) >= MIN_QUOTE_CHARS]
    # never leave a finding uncited: if every excerpt is short, the longest
    # available still says more about it than nothing does
    pool = substantial or cited
    chosen = sorted(pool, key=lambda s: len(s.text.strip()), reverse=True)[:MAX_QUOTES]
    return [
        {
            "speaker": segment.speaker_label,
            "start": segment.start_seconds,
            "timestamp": _timestamp(segment.start_seconds),
            "text": segment.text,
        }
        for segment in sorted(chosen, key=spoken_order)
    ]


def _methodology_note(session: Session, assembly: Assembly) -> str:
    """The standing note, plus whatever was unusual about THIS assembly."""
    note = METHODOLOGY_NOTE
    if _has_live_transcript(session, assembly):
        note += LIVE_TRANSCRIPT_NOTE
    if _has_replaced_device(session, assembly):
        note += DEVICE_REPLACED_NOTE
    return note


def _has_replaced_device(session: Session, assembly: Assembly) -> bool:
    """Did any table change phone mid-round?

    The methodology says one phone per table recorded each conversation. When
    a device was replaced that is no longer true, and a reader deserves to know
    why a table's recording has a gap in it.
    """
    return (
        session.execute(
            select(Recording.id)
            .where(
                Recording.assembly_id == assembly.id,
                Recording.superseded_at.is_not(None),
            )
            .limit(1)
        ).first()
        is not None
    )


def _has_live_transcript(session: Session, assembly: Assembly) -> bool:
    """True when any of this assembly's transcripts came from live captions.

    That is a weaker record than a transcription of the finished audio, and a
    reader of the report is entitled to know which one they are reading.
    """
    return (
        session.execute(
            select(Transcript.id)
            .join(Recording, Recording.id == Transcript.recording_id)
            .where(Recording.assembly_id == assembly.id, Transcript.source == "live")
            .limit(1)
        ).first()
        is not None
    )


def build_report(session: Session, assembly: Assembly, include_drafts: bool = False) -> dict:
    participant_count = session.execute(
        select(func.count()).select_from(Participant).where(Participant.assembly_id == assembly.id)
    ).scalar_one()

    statuses = APPROVED + (("DRAFT",) if include_drafts else ())
    findings = list(
        session.execute(
            select(Finding)
            .where(Finding.assembly_id == assembly.id, Finding.status.in_(statuses))
            .options(selectinload(Finding.evidence))
            .order_by(Finding.created_at)
        ).scalars()
    )
    segment_ids = {
        e.transcript_segment_id for f in findings for e in f.evidence
    }
    segments = {
        s.id: s
        for s in session.execute(
            select(TranscriptSegment).where(TranscriptSegment.id.in_(segment_ids))
        ).scalars()
    } if segment_ids else {}

    recordings_by_round: dict[str, int] = {}
    table_summaries: dict[tuple[str, int], str] = {}
    for recording in session.execute(
        select(Recording).where(Recording.assembly_id == assembly.id)
    ).scalars():
        recordings_by_round[recording.round_id] = recordings_by_round.get(recording.round_id, 0) + 1
        if recording.analysis_summary:
            table_summaries[(recording.round_id, recording.table_number)] = recording.analysis_summary

    def finding_payload(finding: Finding, table_numbers: dict[str, int]) -> dict:
        return {
            "id": finding.id,
            "type": finding.type,
            "title": finding.title,
            "summary": finding.summary,
            "support": finding.support,
            "status": finding.status,
            "is_draft": finding.status == "DRAFT",
            "table_number": table_numbers.get(finding.table_id or ""),
            "mentioned_table_count": finding.mentioned_table_count,
            # the quotes went away with a deleted/replaced transcript — say so
            # rather than rendering a finding that looks unsupported
            "evidence_removed": finding.evidence_removed_at is not None,
            "evidence": (
                # a cross-table finding has no evidence of its own; borrow it
                # from the table findings it clustered, labelled per table
                _cross_table_evidence(session, finding, table_numbers)
                if finding.scope == "round"
                else _quotes(
                    [
                        segments[e.transcript_segment_id]
                        for e in finding.evidence
                        if e.transcript_segment_id in segments
                    ]
                )
            ),
        }

    rounds_payload = []
    for round_ in assembly.rounds:
        table_numbers = {table.id: table.number for table in round_.tables}
        round_findings = [f for f in findings if f.round_id == round_.id]
        cross = [finding_payload(f, table_numbers) for f in round_findings if f.scope == "round"]
        per_table: dict[int, list[dict]] = {}
        for finding in round_findings:
            if finding.scope != "table":
                continue
            number = table_numbers.get(finding.table_id or "")
            if number is not None:
                per_table.setdefault(number, []).append(finding_payload(finding, table_numbers))
        # tables with an AI summary appear even without findings
        round_table_numbers = sorted(
            set(per_table)
            | {num for (rid, num) in table_summaries if rid == round_.id}
        )
        rounds_payload.append(
            {
                "position": round_.position,
                "title": round_.title,
                "question": round_.question,
                "status": round_.status,
                "summary": round_.analysis_summary,
                "recordings": recordings_by_round.get(round_.id, 0),
                # talk-time per detected voice (services/speaking.py); the
                # renderers show it only when diarization produced >= 2 voices
                "speaking_balance": round_speaking_balance(session, round_),
                "cross_table": cross,
                "tables": [
                    {
                        "table_number": number,
                        "summary": table_summaries.get((round_.id, number), ""),
                        "findings": per_table.get(number, []),
                    }
                    for number in round_table_numbers
                ],
            }
        )

    return {
        "assembly": {
            "name": assembly.name,
            "description": assembly.description,
            "language": assembly.language,
            "status": assembly.status,
            "recording_mode": assembly.recording_mode,
            "participants": participant_count,
            "expected_participants": assembly.expected_participants,
            "tables": assembly.default_table_count,
        },
        # only claim diarization when the transcripts actually carry speakers:
        # Whisper and Vosk return text without speaker separation
        "method": (
            "In-person citizens' assembly: participants discussed in small tables; "
            "a phone at each table recorded the conversation, which was transcribed "
            + ("with speaker diarization " if _has_speaker_labels(session, assembly) else "")
            + "and analyzed per table, then aggregated across tables."
        ),
        # built by accumulation rather than a ternary: there are three notes
        # now, and "(A + B) if cond else A" does not extend to a third
        "methodology_note": _methodology_note(session, assembly),
        "include_drafts": include_drafts,
        # when set, table phones can view/download this report
        "published_at": (
            assembly.report_published_at.isoformat()
            if assembly.report_published_at
            else None
        ),
        # a report is FINAL once the organizer closed the session; until then
        # it is an interim view of an assembly still in progress
        "closed_at": assembly.closed_at.isoformat() if assembly.closed_at else None,
        "is_final": assembly.closed_at is not None,
        "progress": progress(session, assembly),
        "rounds": rounds_payload,
    }


def render_markdown(report: dict) -> str:
    assembly = report["assembly"]
    coverage = report.get("progress") or {}
    state_line = (
        f"**FINAL REPORT** — closed {(report.get('closed_at') or '')[:10]}"
        if report.get("is_final")
        else f"**INTERIM REPORT** — {coverage.get('tables_complete', 0)} of "
        f"{coverage.get('tables_expected', 0)} tables have completed all rounds"
    )
    lines = [
        f"# {assembly['name']} — Assembly Report",
        "",
        state_line,
        "",
        assembly["description"] or "",
        "",
        f"- Tables contributing: {coverage.get('tables_contributed', 0)} of "
        f"{coverage.get('tables_expected', 0)}",
        # only when a roster was imported: "0 participants (expected 50)" on a
        # report of a real discussion reads as a failure, and it is not one —
        # recording a table creates no Participant row
        *(
            [f"- Participants: {assembly['participants']} "
             f"(expected {assembly['expected_participants']})"]
            if assembly["participants"]
            else []
        ),
        f"- Tables: {assembly['tables']}",
        f"- Language: {assembly['language'].upper()}",
        "",
        "## Method",
        "",
        report["method"],
        "",
    ]
    plenary = assembly.get("recording_mode") == "plenary"
    for round_ in report["rounds"]:
        lines += [f"## {round_heading(round_['position'], round_['title'])}", ""]
        if round_["question"]:
            lines += [f"> {round_['question']}", ""]
        if round_["summary"]:
            lines += [f"*AI summary:* {round_['summary']}", ""]
        balance = round_.get("speaking_balance")
        if balance and len(balance["voices"]) >= 2:
            lines += ["**Speaking balance**", ""]
            lines += [
                f"- Voice {v['label']} — {v['percent']}% ({_timestamp(v['seconds'])})"
                if v["label"] != "Others"
                else f"- Others — {v['percent']}% ({_timestamp(v['seconds'])})"
                for v in balance["voices"]
            ]
            lines += [
                "",
                "*Detected voices, not identified by name — from the clearest "
                "single recording. Talk-time, not influence.*",
                "",
            ]
        if plenary:
            # One group = one table: render its findings once, grouped by type,
            # with no "Across all tables" section and no "Table N" heading.
            table = round_["tables"][0] if round_["tables"] else None
            findings = table["findings"] if table else []
            for _type, label, group in group_findings_by_type(findings):
                lines += [f"### {label}", ""]
                for finding in group:
                    lines += _markdown_finding(finding, cross=False)
            if not findings:
                lines += ["_No findings for this round yet._", ""]
            continue
        if round_["cross_table"]:
            lines += ["### Across all tables", ""]
            for _type, label, group in group_findings_by_type(round_["cross_table"]):
                lines += [f"#### {label}", ""]
                for finding in group:
                    lines += _markdown_finding(finding, cross=True)
        for table in round_["tables"]:
            if not table["findings"] and not table["summary"]:
                continue
            lines += [f"### Table {table['table_number']}", ""]
            if table["summary"]:
                lines += [f"*AI summary:* {table['summary']}", ""]
            for finding in table["findings"]:
                lines += _markdown_finding(finding, cross=False)
        if (
            not round_["summary"]
            and not round_["cross_table"]
            and not any(t["findings"] or t["summary"] for t in round_["tables"])
        ):
            lines += ["_No findings for this round yet._", ""]
    lines += ["---", "", f"_{report['methodology_note']}_", ""]
    return "\n".join(lines)


def _markdown_finding(finding: dict, cross: bool) -> list[str]:
    draft = " *(DRAFT — not yet reviewed)*" if finding["is_draft"] else ""
    label = TYPE_LABELS_SINGULAR.get(finding["type"], finding["type"])
    header = f"**{label}: {finding['title']}**{draft}"
    lines = [header, "", finding["summary"], ""]
    if cross and finding["mentioned_table_count"]:
        lines.insert(2, f"Mentioned at {finding['mentioned_table_count']} table(s).")
        lines.insert(3, "")
    for evidence in finding["evidence"]:
        speaker = evidence["speaker"] or "Speaker"
        # cross-table quotes are labelled with the table they came from
        where = f"Table {evidence['table_number']} · " if evidence.get("table_number") else ""
        lines += [f"> {where}[{evidence['timestamp']}] {speaker}: “{evidence['text']}”", ""]
    if not finding["evidence"] and finding.get("evidence_removed"):
        lines += ["_Evidence removed with the transcript._", ""]
    return lines
