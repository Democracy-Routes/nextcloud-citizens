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
from citizens.services.report_text import (
    TYPE_ORDER,
    finding_type_label,
    text,
    type_labels,
    type_labels_singular,
)
from citizens.services.speaking import round_speaking_balance

# The wording lives in report_text.py, per language. These module names are
# the English values, kept for callers that want a language-neutral constant
# (tests, the findings API); the renderers look up the report's own language.
METHODOLOGY_NOTE = text("en", "methodology_note")

# deliberation-report vocabulary; the fixed order groups cross-table findings
# in reports (institutional reading order, divergence highlighted)
TYPE_LABELS = type_labels("en")

TYPE_LABELS_SINGULAR = type_labels_singular("en")


def group_findings_by_type(
    findings: list[dict], language: str | None = "en"
) -> list[tuple[str, str, list[dict]]]:
    """(type, plural label, findings) groups in the institutional order."""
    labels = type_labels(language)
    groups = []
    for type_ in TYPE_ORDER:
        matching = [f for f in findings if f["type"] == type_]
        if matching:
            groups.append((type_, labels[type_], matching))
    leftover = [f for f in findings if f["type"] not in TYPE_ORDER]
    if leftover:
        groups.append(("other", text(language, "type_plural.other"), leftover))
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


# English, with the leading space the methodology note joins them by; the
# per-language wording is in report_text.py
LIVE_TRANSCRIPT_NOTE = " " + text("en", "live_transcript_note")

DEVICE_REPLACED_NOTE = " " + text("en", "device_replaced_note")


def round_heading(position: int, title: str, language: str | None = "en") -> str:
    """How a round is named wherever it is shown.

    The app manufactures its own redundancy here: both round-creation paths
    pre-fill the title with "Round N", so an organizer who edits it to
    "Round 1 - design" gets "Round 1 — Round 1 - design" on every screen and in
    every export. When the title already opens with this round's number, it is
    the whole heading.

    The pre-filled default is English whatever the assembly's language, so an
    untouched "Round 2" in an Italian assembly is rendered as "Turno 2"; a
    title the organizer wrote is theirs and is printed as written.
    """
    name = (title or "").strip()
    default = text(language, "round", position=position)
    if not name or name == f"Round {position}":
        return default
    first = name.split()[0].rstrip(".:-–—") if name.split() else ""
    lowered = name.lower()
    if (
        lowered.startswith(f"round {position}")
        or lowered.startswith(default.lower())
        or first == str(position)
    ):
        return name
    return text(language, "round_titled", position=position, title=name)


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
    language = assembly.language
    parts = [text(language, "methodology_note")]
    if _has_live_transcript(session, assembly):
        parts.append(text(language, "live_transcript_note"))
    if _has_replaced_device(session, assembly):
        parts.append(text(language, "device_replaced_note"))
    return " ".join(parts)


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

    language = assembly.language

    def finding_payload(finding: Finding, table_numbers: dict[str, int]) -> dict:
        return {
            "id": finding.id,
            "type": finding.type,
            # the type as the report names it, in the assembly's language, so
            # a client can show it without a dictionary of its own
            "type_label": finding_type_label(language, finding.type),
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
                # the phone's report screen shows this as-is, so it follows the
                # assembly's language without a dictionary of its own
                "heading": round_heading(round_.position, round_.title, assembly.language),
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
        "method": text(
            language,
            "method_diarized" if _has_speaker_labels(session, assembly) else "method",
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


def report_language(report: dict) -> str | None:
    """The language a report's fixed wording is printed in: the assembly's.

    Read with .get(): a frozen final report predates nothing here, but the
    renderers also take hand-built dicts in tests.
    """
    return (report.get("assembly") or {}).get("language")


def mentioned_at_tables(language: str | None, count: int) -> str:
    """"Mentioned at N table(s)" — languages that cannot hedge the plural the
    way English does carry a separate wording for one table."""
    key = "mentioned_at_one_table" if count == 1 else "mentioned_at_tables"
    return text(language, key, count=count)


def render_markdown(report: dict) -> str:
    assembly = report["assembly"]
    language = report_language(report)
    coverage = report.get("progress") or {}
    state_line = (
        f"**{text(language, 'final_report')}** — "
        + text(language, "closed_on", date=(report.get("closed_at") or "")[:10])
        if report.get("is_final")
        else f"**{text(language, 'interim_report')}** — "
        + text(
            language, "tables_completed_all_rounds",
            complete=coverage.get("tables_complete", 0),
            expected=coverage.get("tables_expected", 0),
        )
    )
    lines = [
        f"# {assembly['name']} — {text(language, 'assembly_report')}",
        "",
        state_line,
        "",
        assembly["description"] or "",
        "",
        "- " + text(
            language, "tables_contributing",
            contributed=coverage.get("tables_contributed", 0),
            expected=coverage.get("tables_expected", 0),
        ),
        # only when a roster was imported: "0 participants (expected 50)" on a
        # report of a real discussion reads as a failure, and it is not one —
        # recording a table creates no Participant row
        *(
            ["- " + text(
                language, "participants",
                count=assembly["participants"], expected=assembly["expected_participants"],
            )]
            if assembly["participants"]
            else []
        ),
        "- " + text(language, "tables", count=assembly["tables"]),
        "- " + text(language, "language", code=assembly["language"].upper()),
        "",
        f"## {text(language, 'method_heading')}",
        "",
        report["method"],
        "",
    ]
    ai_summary = text(language, "ai_summary")
    no_findings = f"_{text(language, 'no_findings_yet')}_"
    plenary = assembly.get("recording_mode") == "plenary"
    for round_ in report["rounds"]:
        lines += [f"## {round_heading(round_['position'], round_['title'], language)}", ""]
        if round_["question"]:
            lines += [f"> {round_['question']}", ""]
        if round_["summary"]:
            lines += [f"*{ai_summary}:* {round_['summary']}", ""]
        balance = round_.get("speaking_balance")
        if balance and len(balance["voices"]) >= 2:
            lines += [f"**{text(language, 'speaking_balance')}**", ""]
            lines += [
                f"- {voice_name(language, v['label'])} — {v['percent']}% "
                f"({_timestamp(v['seconds'])})"
                for v in balance["voices"]
            ]
            lines += ["", f"*{text(language, 'voices_caveat')}*", ""]
        if plenary:
            # One group = one table: render its findings once, grouped by type,
            # with no "Across all tables" section and no "Table N" heading.
            table = round_["tables"][0] if round_["tables"] else None
            findings = table["findings"] if table else []
            for _type, label, group in group_findings_by_type(findings, language):
                lines += [f"### {label}", ""]
                for finding in group:
                    lines += _markdown_finding(finding, cross=False, language=language)
            if not findings:
                lines += [no_findings, ""]
            continue
        if round_["cross_table"]:
            lines += [f"### {text(language, 'across_all_tables')}", ""]
            for _type, label, group in group_findings_by_type(round_["cross_table"], language):
                lines += [f"#### {label}", ""]
                for finding in group:
                    lines += _markdown_finding(finding, cross=True, language=language)
        for table in round_["tables"]:
            if not table["findings"] and not table["summary"]:
                continue
            lines += [f"### {text(language, 'table', number=table['table_number'])}", ""]
            if table["summary"]:
                lines += [f"*{ai_summary}:* {table['summary']}", ""]
            for finding in table["findings"]:
                lines += _markdown_finding(finding, cross=False, language=language)
        if (
            not round_["summary"]
            and not round_["cross_table"]
            and not any(t["findings"] or t["summary"] for t in round_["tables"])
        ):
            lines += [no_findings, ""]
    lines += ["---", "", f"_{report['methodology_note']}_", ""]
    return "\n".join(lines)


def voice_name(language: str | None, label: str) -> str:
    """"Voice A" / "Others" — the balance's labels are data; the words are not."""
    if label == "Others":
        return text(language, "others")
    return text(language, "voice", label=label)


def _markdown_finding(finding: dict, cross: bool, language: str | None = "en") -> list[str]:
    draft = f" *({text(language, 'draft_not_reviewed')})*" if finding["is_draft"] else ""
    label = finding_type_label(language, finding["type"])
    header = f"**{label}: {finding['title']}**{draft}"
    lines = [header, "", finding["summary"], ""]
    if cross and finding["mentioned_table_count"]:
        lines.insert(2, mentioned_at_tables(language, finding["mentioned_table_count"]) + ".")
        lines.insert(3, "")
    for evidence in finding["evidence"]:
        speaker = evidence["speaker"] or text(language, "speaker")
        # cross-table quotes are labelled with the table they came from
        where = (
            f"{text(language, 'table', number=evidence['table_number'])} · "
            if evidence.get("table_number")
            else ""
        )
        lines += [f"> {where}[{evidence['timestamp']}] {speaker}: “{evidence['text']}”", ""]
    if not finding["evidence"] and finding.get("evidence_removed"):
        lines += [f"_{text(language, 'evidence_removed')}_", ""]
    return lines
