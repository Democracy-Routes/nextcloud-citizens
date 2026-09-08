# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""AI analysis: per-table structured extraction and cross-table clustering
(brief §36–§39). Every table finding must cite real transcript segments;
anything without valid evidence is dropped, never stored.
"""

import difflib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from citizens.db.models import (
    Assembly,
    Finding,
    FindingEvidence,
    Recording,
    Round,
    Transcript,
    TranscriptSegment,
)
from citizens.domain.analysis_schemas import RoundAnalysis, TableAnalysis
from citizens.logging_setup import get_logger
from citizens.providers.analysis.openai_compat import AnalysisError, chat_json
from citizens.services import provider_config, pseudonyms

log = get_logger(__name__)

COALESCE_GAP_SECONDS = 1.5

LANGUAGE_NAMES = {"en": "English", "it": "Italian", "de": "German", "fr": "French", "es": "Spanish"}


def analysis_ready(store: provider_config.ConfigStore) -> bool:
    return (
        provider_config.get_setting(store, "analysis_enabled") == "1"
        and bool(store.get_value("analysis_api_key"))
    )


def coalesce_segments(segments: list[TranscriptSegment]) -> list[dict]:
    """Merge consecutive same-speaker fragments into readable blocks. Each
    block keeps every member segment id so evidence citations stay valid."""
    blocks: list[dict] = []
    for segment in segments:
        last = blocks[-1] if blocks else None
        if (
            last is not None
            and last["speaker"] == segment.speaker_label
            and segment.start_seconds - last["end"] <= COALESCE_GAP_SECONDS
        ):
            last["ids"].append(segment.id)
            last["end"] = segment.end_seconds
            last["text"] = f"{last['text']} {segment.text}".strip()
        else:
            blocks.append(
                {
                    "ids": [segment.id],
                    "speaker": segment.speaker_label,
                    "start": segment.start_seconds,
                    "end": segment.end_seconds,
                    "text": segment.text,
                }
            )
    return blocks


def _timestamp(seconds: float) -> str:
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


def _analysis_config(store: provider_config.ConfigStore) -> tuple[str, str, str]:
    key = store.get_value("analysis_api_key")
    if not key:
        raise AnalysisError("No analysis API key configured", permanent=True)
    return (
        provider_config.get_setting(store, "analysis_base_url"),
        key,
        provider_config.get_setting(store, "analysis_model"),
    )


TABLE_SYSTEM = """You are an analyst supporting an in-person citizens' assembly.
You analyze ONE table's discussion transcript.

Rules:
- Respond with ONLY a JSON object: {{"summary": "...", "findings": [{{"type": ...,
  "title": ..., "summary": ..., "support": ..., "evidence_segment_ids": [...]}}]}}
- "summary" (top level) is ALWAYS required: a neutral 2-4 sentence description
  of what the table actually discussed — even if it was small talk or off the
  round question. Never leave it out.
- "type" is one of: proposal, agreement, disagreement, concern, question,
  minority_position, new_idea.
- "support" (optional) is one of: strong, mixed, weak, unclear.
- EVERY finding MUST cite at least one evidence_segment_ids value copied
  EXACTLY from the segment ids in the transcript. Never invent ids.
- Only report what participants actually said. Do not invent content.
- Actively look for points of conflict: positions where participants disagree
  with each other. Report each as a "disagreement" finding whose summary names
  BOTH sides of the disagreement, and mention the most significant conflicts
  in the top-level summary.
- If the discussion contains nothing substantive for the round question,
  return {{"summary": "...", "findings": []}}.
- Write everything in {language}."""

ROUND_SYSTEM = """You are an analyst supporting an in-person citizens' assembly.
You aggregate findings from multiple discussion tables of the SAME round into
cross-table clusters (recurring proposals, shared concerns, disagreements,
minority positions, questions, unique new ideas).

Rules:
- Respond with ONLY a JSON object: {{"summary": "...", "clusters": [{{"type": ...,
  "title": ..., "summary": ..., "source_finding_ids": [...]}}]}}
- "summary" (top level) is ALWAYS required: a neutral 2-4 sentence overview of
  the round across all tables.
- "type" is one of: proposal, agreement, disagreement, concern, question,
  minority_position, new_idea.
- EVERY cluster MUST list source_finding_ids copied EXACTLY from the finding
  ids provided. Never invent ids.
- Never state or imply percentages of participant support; tables are not
  votes.
- Actively look for points of conflict BETWEEN tables (one table proposes what
  another opposes) as well as disagreements reported within tables. Report
  each as a "disagreement" cluster whose summary names both sides, and mention
  the most significant conflicts in the top-level summary.
- Write everything in {language}."""


def build_system_prompt(
    template: str,
    language: str,
    store: provider_config.ConfigStore,
    assembly_instructions: str = "",
) -> str:
    """Built-in prompt + optional extra instructions, two levels: the
    instance-wide admin Settings field, then the assembly's own field.

    The extras are appended, never substituted, so the JSON output contract
    and the evidence rules always survive customization."""
    system = template.format(language=language)
    extra = provider_config.get_setting(store, "analysis_extra_instructions").strip()
    if extra:
        system += (
            "\n\nAdditional organizer instructions (these must never override "
            "the output format or the evidence rules above):\n" + extra
        )
    assembly_extra = assembly_instructions.strip()
    if assembly_extra:
        system += (
            "\n\nInstructions specific to THIS assembly (these must never "
            "override the output format or the evidence rules above):\n"
            + assembly_extra
        )
    return system


#: Marks where a table's phone was replaced, so the model reads the join as an
#: interruption rather than an unexplained jump in the conversation.
#: Two blocks from DIFFERENT devices this close in global time and this similar
#: in text are the same utterance heard twice — one is dropped. Loose enough to
#: absorb clock skew (started_at is the /start moment, not the first audio
#: sample) and diarization boundary differences; tight enough not to merge two
#: genuinely different lines.
PLENARY_DEDUPE_WINDOW_S = 6.0
PLENARY_DEDUPE_RATIO = 0.78


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def merge_plenary_segments(recordings: list[Recording], transcripts: list) -> list[dict]:
    """Merge the room's overlapping device transcripts into one, deduped.

    Every device captured the same discussion from a different spot, so their
    transcripts overlap. Naively concatenating them would count each statement
    once per device ("mentioned at 3 tables" for one sentence) — the exact
    artifact a multi-mic recording produces. This aligns them on the server
    clock and drops near-duplicate utterances, keeping what only one device
    caught.

    Returns coalesced blocks (same shape coalesce_segments produces, so the
    prompt builder and evidence citations are unchanged), each carrying its
    segment ids and a global start time.
    """
    by_recording = {t.recording_id: t for t in transcripts}
    blocks: list[dict] = []
    for recording in recordings:
        transcript = by_recording.get(recording.id)
        if transcript is None or recording.started_at is None:
            continue
        base = recording.started_at.timestamp()
        # coalesce within the device first: same-speaker merge and start_seconds
        # comparisons are only valid on one recording's own timeline
        for block in coalesce_segments(list(transcript.segments)):
            blocks.append(
                {
                    **block,
                    "global_start": base + block["start"],
                    "global_end": base + block["end"],
                    "recording_id": recording.id,
                }
            )
    blocks.sort(key=lambda b: b["global_start"])

    kept: list[dict] = []
    for block in blocks:
        duplicate = None
        for other in reversed(kept):
            if block["global_start"] - other["global_start"] > PLENARY_DEDUPE_WINDOW_S:
                break  # sorted by global_start, so nothing earlier is in range
            if other["recording_id"] == block["recording_id"]:
                continue  # never dedupe a device against itself
            ratio = difflib.SequenceMatcher(
                None, _normalise(other["text"]), _normalise(block["text"])
            ).ratio()
            if ratio >= PLENARY_DEDUPE_RATIO:
                duplicate = other
                break
        if duplicate is None:
            kept.append(block)
        elif len(block["text"]) > len(duplicate["text"]):
            # the same utterance, better captured on this device — keep its text
            # and its ids (evidence points at the clearer copy)
            duplicate["text"] = block["text"]
            duplicate["ids"] = block["ids"]
    kept.sort(key=lambda b: b["global_start"])
    return kept


DEVICE_CHANGE_MARKER = (
    "[--- the table's phone was replaced here; the discussion continued on "
    "another device, and a short part of it was not recorded ---]"
)


def table_recordings(session: Session, recording: Recording) -> list[Recording]:
    """Every recording of this table's discussion in this round, oldest first.

    Normally one. Two when the phone was replaced mid-round — one group of
    people having one conversation with a technical interruption in the middle,
    which is how the analysis and the report should treat it.
    """
    return list(
        session.execute(
            select(Recording)
            .where(
                Recording.round_id == recording.round_id,
                Recording.table_id == recording.table_id,
            )
            .order_by(Recording.created_at)
        ).scalars()
    )


def analyze_table(session: Session, store: provider_config.ConfigStore, recording: Recording) -> int:
    """Extract findings for one table's discussion; returns stored finding count.

    Analyses the TABLE, not the recording. A table whose phone was replaced has
    two recordings, and analysing each separately would produce two competing
    summaries above a single merged set of findings — telling a reader the same
    discussion is both one thing and two. It is also more expensive: one model
    call per recording rather than one per table.
    """
    siblings = table_recordings(session, recording)
    # the newest recording owns the table's summary and findings, so exactly
    # one row per (round, table) carries them and nothing can overwrite anything
    primary = siblings[-1]

    transcripts = []
    for sibling in siblings:
        transcript = session.execute(
            select(Transcript).where(Transcript.recording_id == sibling.id)
        ).scalar_one_or_none()
        if transcript is not None:
            transcripts.append(transcript)
    if not transcripts:
        raise AnalysisError("No transcript for this table", permanent=True)

    segments = [segment for transcript in transcripts for segment in transcript.segments]
    if not segments:
        # nothing can fail after this point, so replacing here is safe
        _delete_table_findings(session, siblings)
        _set_table_summary(siblings, primary, "No speech was detected in this recording.")
        log.info("analysis_empty_transcript", recording_id=primary.id)
        return 0

    assembly = session.get(Assembly, recording.assembly_id)
    round_ = session.get(Round, recording.round_id)
    language = LANGUAGE_NAMES.get(assembly.language if assembly else "en", "English")
    valid_ids = {segment.id for segment in segments}
    # Names people say out loud are in the transcript, and the transcript is
    # what leaves the server. The stored text is untouched — this masks only
    # the copy composed into the prompt, so the report's quotes still show what
    # the table actually said.
    hidden = pseudonyms.name_map(session, assembly) if assembly else {}

    lines: list[str] = []
    if assembly is not None and assembly.recording_mode == "plenary" and len(siblings) > 1:
        # The whole room on many phones: one discussion, overlapping captures.
        # Merge and dedupe into a single timeline rather than concatenating the
        # devices back to back (which would count each statement once per phone).
        for block in merge_plenary_segments(siblings, transcripts):
            lines.append(
                f"[{'|'.join(block['ids'])}] {block['speaker'] or 'SPEAKER'} "
                f"({_timestamp(block['start'])}-{_timestamp(block['end'])}): "
                f"{pseudonyms.redact(block['text'], hidden)}"
            )
    else:
        for index, transcript in enumerate(transcripts):
            if index:
                lines.append(DEVICE_CHANGE_MARKER)
            lines.extend(
                f"[{'|'.join(block['ids'])}] {block['speaker'] or 'SPEAKER'} "
                f"({_timestamp(block['start'])}-{_timestamp(block['end'])}): "
                f"{pseudonyms.redact(block['text'], hidden)}"
                for block in coalesce_segments(list(transcript.segments))
            )
    user_prompt = (
        f"Assembly: {assembly.name if assembly else ''}\n"
        f"Round question: {round_.question or round_.title if round_ else ''}\n"
        f"Table number: {recording.table_number}\n\n"
        "Transcript segments (format: [segment ids] SPEAKER (start-end): text):\n"
        + "\n".join(lines)
    )

    # release the DB write lock BEFORE reading provider config — _analysis_config
    # and build_system_prompt are OCS calls to Nextcloud, and a held job
    # transaction 500s every API request after busy_timeout
    session.commit()
    base_url, key, model = _analysis_config(store)
    log.info(
        "analysis_started", recording_id=primary.id, scope="table",
        segments=len(lines), recordings=len(siblings),
    )
    system_prompt = build_system_prompt(
        TABLE_SYSTEM, language, store, assembly.analysis_instructions if assembly else ""
    )
    result = chat_json(base_url, key, model, system_prompt, user_prompt, TableAnalysis)

    # Only now that the model has answered. Deleting before the call meant a
    # permanent failure — a rotated key answering 401, or output that fails
    # validation three times — destroyed the existing findings and regenerated
    # nothing: PermanentJobError does not roll back (see jobs/runner.py). The
    # delete and the inserts below are one transaction, so re-analysis either
    # replaces the findings or leaves them untouched.
    _delete_table_findings(session, siblings)
    _set_table_summary(siblings, primary, result.summary)

    stored = 0
    dropped = 0
    for item in result.findings:
        evidence_ids = {
            eid for raw in item.evidence_segment_ids for eid in raw.split("|") if eid in valid_ids
        }
        if not evidence_ids:
            dropped += 1
            continue  # a finding without real evidence is INVALID (brief §38)
        finding = Finding(
            assembly_id=recording.assembly_id,
            round_id=recording.round_id,
            table_id=recording.table_id,
            # attributed to the table's current recording, so re-analysis
            # replaces them wherever the job happened to be enqueued from
            recording_id=primary.id,
            scope="table",
            type=item.type,
            title=item.title,
            summary=item.summary,
            support=item.support or "",
            ai_model=model,
            original_json=item.model_dump_json(),
        )
        for segment_id in sorted(evidence_ids):
            finding.evidence.append(FindingEvidence(transcript_segment_id=segment_id))
        session.add(finding)
        stored += 1
    session.flush()
    log.info(
        "analysis_completed", recording_id=primary.id, scope="table",
        recordings=len(siblings), findings=stored, dropped_without_evidence=dropped,
    )
    return stored


def analyze_round(session: Session, store: provider_config.ConfigStore, round_: Round) -> int:
    """Cluster all table findings of a round into cross-table findings."""
    assembly = session.get(Assembly, round_.assembly_id)
    if assembly is not None and assembly.recording_mode == "plenary":
        # Plenary is one group (one table), so there is nothing to cluster
        # ACROSS tables — the table findings ARE the round's findings. Producing
        # round-scope clusters here just echoed every finding a second time in
        # the report. Skip the model call; set the round summary from the group.
        _delete_existing(session, round_id=round_.id, scope="round", only_drafts=True)
        summary = session.execute(
            select(Recording.analysis_summary).where(
                Recording.round_id == round_.id, Recording.analysis_summary != ""
            )
        ).scalars().first()
        round_.analysis_summary = summary or (
            "No substantive findings emerged from this round's discussion."
        )
        session.flush()
        log.info("analysis_round_plenary_no_clustering", round_id=round_.id)
        return 0

    table_findings = list(
        session.execute(
            select(Finding).where(
                Finding.round_id == round_.id,
                Finding.scope == "table",
                Finding.status != "REJECTED",
            )
        ).scalars()
    )
    if not table_findings:
        # nothing can fail after this point, so replacing here is safe
        _delete_existing(session, round_id=round_.id, scope="round", only_drafts=True)
        summaries = [
            f"Table {rec.table_number}: {rec.analysis_summary}"
            for rec in session.execute(
                select(Recording).where(
                    Recording.round_id == round_.id, Recording.analysis_summary != ""
                )
            ).scalars()
        ]
        round_.analysis_summary = (
            " ".join(summaries)[:1500]
            if summaries
            else "No substantive findings emerged from this round's discussions."
        )
        log.info("analysis_round_no_findings", round_id=round_.id)
        return 0

    language = LANGUAGE_NAMES.get(assembly.language if assembly else "en", "English")
    tables_by_finding: dict[str, str | None] = {f.id: f.table_id for f in table_findings}
    total_tables = len({f.table_id for f in table_findings if f.table_id})
    table_numbers = _table_numbers(session, round_)

    # the table findings were drafted from already-masked text, but a name may
    # have been added to the list since, or typed into a human edit
    hidden = pseudonyms.name_map(session, assembly) if assembly else {}
    lines = [
        f"[{f.id}] table {table_numbers.get(f.table_id or '', '?')} · {f.type} · "
        f"{pseudonyms.redact(f.title, hidden)}: "
        f"{pseudonyms.redact(f.summary, hidden)[:400]}"
        for f in table_findings
    ]
    user_prompt = (
        f"Assembly: {assembly.name if assembly else ''}\n"
        f"Round question: {round_.question or round_.title}\n"
        f"Tables that produced findings: {total_tables}\n\n"
        "Table findings (format: [finding id] table N · type · title: summary):\n"
        + "\n".join(lines)
    )

    # release the lock before the config reads as well as the model call
    # (see analyze_table)
    session.commit()
    base_url, key, model = _analysis_config(store)
    log.info("analysis_started", round_id=round_.id, scope="round", source_findings=len(lines))
    system_prompt = build_system_prompt(
        ROUND_SYSTEM, language, store, assembly.analysis_instructions if assembly else ""
    )
    result = chat_json(base_url, key, model, system_prompt, user_prompt, RoundAnalysis)

    # after the model answers, for the reason given in analyze_table
    _delete_existing(session, round_id=round_.id, scope="round", only_drafts=True)
    round_.analysis_summary = result.summary

    stored = 0
    for cluster in result.clusters:
        source_ids = [fid for fid in cluster.source_finding_ids if fid in tables_by_finding]
        if not source_ids:
            continue
        # table count computed from real links, never trusted from the model
        mentioned = len({tables_by_finding[fid] for fid in source_ids if tables_by_finding[fid]})
        session.add(
            Finding(
                assembly_id=round_.assembly_id,
                round_id=round_.id,
                scope="round",
                type=cluster.type,
                title=cluster.title,
                summary=cluster.summary,
                ai_model=model,
                original_json=cluster.model_dump_json(),
                source_finding_ids=json.dumps(source_ids),
                mentioned_table_count=mentioned,
            )
        )
        stored += 1
    session.flush()
    log.info("analysis_completed", round_id=round_.id, scope="round", findings=stored)
    return stored


def _table_numbers(session: Session, round_: Round) -> dict[str, int]:
    return {table.id: table.number for table in round_.tables}


def _delete_table_findings(session: Session, siblings: list[Recording]) -> None:
    """Clear this table's draft findings across every recording it has.

    A replaced phone leaves findings attributed to the earlier recording; a
    re-analysis that only cleared the current one would leave those behind as
    duplicates nobody could account for.
    """
    for sibling in siblings:
        _delete_existing(session, recording_id=sibling.id, scope="table", only_drafts=True)


def _set_table_summary(siblings: list[Recording], primary: Recording, summary: str) -> None:
    """One summary per table, on one row.

    The report keys each table's summary by (round, table number), so two
    recordings both carrying one meant the second silently overwrote the first
    and database row order decided which a reader saw. Clearing the others
    makes that impossible rather than merely unlikely.
    """
    for sibling in siblings:
        sibling.analysis_summary = summary if sibling.id == primary.id else ""


def _delete_existing(
    session: Session,
    scope: str,
    recording_id: str | None = None,
    round_id: str | None = None,
    only_drafts: bool = True,
) -> None:
    query = select(Finding).where(Finding.scope == scope)
    if recording_id:
        query = query.where(Finding.recording_id == recording_id)
    if round_id:
        query = query.where(Finding.round_id == round_id)
    if only_drafts:
        query = query.where(Finding.status == "DRAFT")
    for finding in session.execute(query).scalars():
        session.delete(finding)
    session.flush()
