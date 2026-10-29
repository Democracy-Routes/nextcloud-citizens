# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Polis statement seeds: from approved findings to a file Polis can take.

The assembly's findings are long and carry evidence; a Polis conversation
needs short statements a stranger can agree or disagree with, and nothing
else. The analysis model writes one to three per approved finding; the
organizer reviews every one; approved seeds go out as CSV or JSON. Nothing
here reads a transcript, and no name or table number reaches the file.

Regeneration keeps what a person touched (approved, rejected, edited or
added by hand) and replaces only untouched drafts, so a second run never
undoes a review.
"""

import csv
import io
import json
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from citizens.db.models import Assembly, Finding, StatementSeed
from citizens.db.models.base import utcnow
from citizens.db.models.seeds import EXPORTABLE_STATUSES, SEED_MAX_CHARS
from citizens.logging_setup import get_logger
from citizens.providers.analysis.openai_compat import chat_json
from citizens.services import provider_config, pseudonyms
from citizens.services.analysis import (
    APPROVED_STATUSES,
    LANGUAGE_NAMES,
    _analysis_config,
    build_system_prompt,
)

log = get_logger(__name__)

EXPORT_SCHEMA = "citizens.statement-seeds/1"

SEEDS_SYSTEM = """You are preparing seed statements for a Polis conversation
from the findings of an in-person citizens' assembly.

Rules:
- Respond with ONLY a JSON object: {{"seeds": [{{"finding_id": "...",
  "statements": ["...", ...]}}]}}
- For EVERY finding given, write one to three statements. Copy finding_id
  EXACTLY from the input. Never invent ids and never skip a finding.
- A statement is ONE idea, one sentence, in a neutral declarative voice,
  that a stranger can agree or disagree with: "Evening buses should run
  until midnight", not "Participants wanted later buses".
- Keep each statement under 140 characters.
- Write for the public: no "we", no "the table", no table numbers, no
  speaker labels, no names, no quotations.
- A disagreement becomes two statements, one per side. A question becomes
  the position it implies, or is left out when it implies none.
- Do not repeat the same idea in two statements.
- Write everything in {language}."""


# --- which findings feed the seeds --------------------------------------

def source_findings(session: Session, assembly: Assembly) -> list[Finding]:
    """Approved cross-table findings in session order; the tables' own
    approved findings when no session was clustered."""
    round_order = {r.id: r.position for r in assembly.rounds}
    rows = list(
        session.execute(
            select(Finding).where(
                Finding.assembly_id == assembly.id,
                Finding.status.in_(APPROVED_STATUSES),
            )
        ).scalars()
    )
    rows.sort(key=lambda f: (round_order.get(f.round_id, 0), f.created_at))
    clustered = [f for f in rows if f.scope == "round"]
    return clustered or [f for f in rows if f.scope == "table"]


def _normalise(text: str) -> str:
    return " ".join(text.split())


def _key(text: str) -> str:
    return _normalise(text).casefold().rstrip(".!")


def clean_statements(raw: list[str], seen: set[str]) -> list[str]:
    """Trim, drop empties, over-long ones and repeats; `seen` collects keys
    across calls so the same idea from two findings appears once."""
    kept = []
    for item in raw:
        text = _normalise(item)
        if not text:
            continue
        if len(text) > SEED_MAX_CHARS:
            log.info("seed_statement_too_long", chars=len(text))
            continue
        key = _key(text)
        if key in seen:
            continue
        seen.add(key)
        kept.append(text)
    return kept


# --- generation -----------------------------------------------------------

def generate(session: Session, store: provider_config.ConfigStore, assembly: Assembly) -> int:
    """Write seeds from the approved findings; returns how many were added.

    Commits before the model call so the writer slot is free while the
    network round-trip runs, like analysis.analyze_assembly."""
    findings = source_findings(session, assembly)
    if not findings:
        log.info("seeds_no_findings", assembly_id=assembly.id)
        return 0
    hidden = pseudonyms.name_map(session, assembly)
    existing = list_seeds(session, assembly.id)
    kept = [s for s in existing if s.touched]
    for seed in existing:
        if not seed.touched:
            session.delete(seed)
    session.flush()
    lines = []
    for finding in findings:
        summary = pseudonyms.redact(finding.summary, hidden)[:1200]
        lines.append(
            f"finding_id: {finding.id}\ntype: {finding.type}\n"
            f"title: {pseudonyms.redact(finding.title, hidden)}\nsummary: {summary}"
        )
    user_prompt = f"Assembly: {assembly.name}\n\n" + "\n\n".join(lines)
    language = LANGUAGE_NAMES.get(assembly.language, "English")
    assembly_id, assembly_language = assembly.id, assembly.language
    session.commit()
    base_url, key, model = _analysis_config(store)
    system_prompt = build_system_prompt(SEEDS_SYSTEM, language, store, assembly.analysis_instructions)
    from citizens.domain.analysis_schemas import StatementSeeds

    log.info("seeds_started", assembly_id=assembly_id, findings=len(findings))
    result = chat_json(base_url, key, model, system_prompt, user_prompt, StatementSeeds)

    wanted = {f.id for f in findings}
    seen = {_key(s.text) for s in kept}
    position = max((s.position for s in kept), default=0)
    added = 0
    for item in result.seeds:
        if item.finding_id not in wanted:
            log.info("seed_unknown_finding", assembly_id=assembly_id)
            continue
        for text in clean_statements(item.statements, seen):
            position += 1
            session.add(
                StatementSeed(
                    assembly_id=assembly_id,
                    finding_id=item.finding_id,
                    text=text,
                    source_text=text,
                    language=assembly_language,
                    position=position,
                    origin="ai",
                )
            )
            added += 1
    session.commit()
    log.info("seeds_completed", assembly_id=assembly_id, added=added, kept=len(kept))
    return added


def mark_findings_replaced(session: Session, finding_ids: list[str]) -> None:
    """A re-run of the analysis is about to delete these findings: their
    seeds lose the link and are flagged so the organizer re-reads them."""
    if not finding_ids:
        return
    for seed in session.execute(
        select(StatementSeed).where(StatementSeed.finding_id.in_(finding_ids))
    ).scalars():
        seed.finding_id = None
        seed.stale = True


# --- reading ----------------------------------------------------------------

def list_seeds(session: Session, assembly_id: str) -> list[StatementSeed]:
    return list(
        session.execute(
            select(StatementSeed)
            .where(StatementSeed.assembly_id == assembly_id)
            .order_by(StatementSeed.position, StatementSeed.created_at)
        ).scalars()
    )


def next_position(session: Session, assembly_id: str) -> int:
    top = session.scalar(
        select(func.max(StatementSeed.position)).where(StatementSeed.assembly_id == assembly_id)
    )
    return (top or 0) + 1


def approved_count(session: Session, assembly_id: str) -> int:
    return session.scalar(
        select(func.count(Finding.id)).where(
            Finding.assembly_id == assembly_id, Finding.status.in_(APPROVED_STATUSES)
        )
    ) or 0


def ready_to_export(seeds: list[StatementSeed]) -> bool:
    """Every seed reviewed, and at least one approved."""
    return bool(seeds) and all(s.status != "DRAFT" for s in seeds) and any(
        s.status in EXPORTABLE_STATUSES for s in seeds
    )


def payload(seed: StatementSeed) -> dict:
    return {
        "id": seed.id,
        "text": seed.text,
        "status": seed.status,
        "position": seed.position,
        "origin": seed.origin,
        "finding_id": seed.finding_id,
        "edited": seed.edited,
        "stale": seed.stale,
        "reviewed_by": seed.reviewed_by,
        "exported_at": seed.exported_at.isoformat() if seed.exported_at else None,
    }


# --- export ---------------------------------------------------------------

def exportable(seeds: list[StatementSeed]) -> list[StatementSeed]:
    return [s for s in seeds if s.status in EXPORTABLE_STATUSES]


def render_csv(seeds: list[StatementSeed]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(["position", "statement"])
    for number, seed in enumerate(seeds, start=1):
        writer.writerow([number, seed.text])
    return out.getvalue()


def render_json(assembly: Assembly, seeds: list[StatementSeed], exported_at: datetime) -> str:
    body = {
        "schema": EXPORT_SCHEMA,
        "assembly": {"name": assembly.name, "language": assembly.language},
        "exported_at": exported_at.isoformat(),
        "statements": [
            {"position": number, "statement": seed.text}
            for number, seed in enumerate(seeds, start=1)
        ],
    }
    return json.dumps(body, ensure_ascii=False, indent=2) + "\n"


def mark_exported(seeds: list[StatementSeed], when: datetime | None = None) -> datetime:
    when = when or utcnow()
    for seed in seeds:
        seed.status = "EXPORTED"
        seed.exported_at = when
    return when


def export_filename(assembly: Assembly, ext: str) -> str:
    return f"{assembly.name[:40].replace(' ', '-')}-statements.{ext}"
