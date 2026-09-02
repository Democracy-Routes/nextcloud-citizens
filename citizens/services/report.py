# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Assembly report: approved findings with evidence references (brief §42)."""

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
            "evidence": [
                {
                    "speaker": segments[e.transcript_segment_id].speaker_label,
                    "start": segments[e.transcript_segment_id].start_seconds,
                    "timestamp": _timestamp(segments[e.transcript_segment_id].start_seconds),
                    "text": segments[e.transcript_segment_id].text,
                }
                for e in finding.evidence
                if e.transcript_segment_id in segments
            ],
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
        f"- Participants: {assembly['participants']} (expected {assembly['expected_participants']})",
        f"- Tables: {assembly['tables']}",
        f"- Language: {assembly['language'].upper()}",
        "",
        "## Method",
        "",
        report["method"],
        "",
    ]
    for round_ in report["rounds"]:
        lines += [f"## Round {round_['position']} — {round_['title'] or 'Untitled'}", ""]
        if round_["question"]:
            lines += [f"> {round_['question']}", ""]
        if round_["summary"]:
            lines += [f"*AI summary:* {round_['summary']}", ""]
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
    for evidence in finding["evidence"][:5]:
        speaker = evidence["speaker"] or "Speaker"
        lines += [f"> [{evidence['timestamp']}] {speaker}: “{evidence['text']}”", ""]
    if not finding["evidence"] and finding.get("evidence_removed"):
        lines += ["_Evidence removed with the transcript._", ""]
    return lines
