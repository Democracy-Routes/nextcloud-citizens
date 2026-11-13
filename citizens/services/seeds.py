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
from the findings of an in-person citizens' assembly. Participants will vote
agree / disagree / pass on each statement; a statement nobody could disagree
with is useless to them.

Rules:
- Respond with ONLY a JSON object: {{"seeds": [{{"finding_id": "...",
  "statements": ["...", ...]}}]}}
- Copy finding_id EXACTLY from the input. Never invent ids.
- A statement is ONE idea, one sentence, in a neutral declarative voice,
  that a stranger can agree or disagree with: "Evening buses should run
  until midnight", not "Participants wanted later buses".
- Every statement names WHO should do WHAT, concretely: an actor (the city,
  schools, the transport company, employers, citizens…), an action, and a
  concrete object (a service, a place, a rule, a number, a condition). Take
  the specifics from the finding's summary — the mechanism, the place, the
  figure, the condition — rather than the general principle.
- The dissent test: before writing a statement down, ask whether a
  reasonable person could disagree with it. "Public services should include
  everyone" fails; "The city should keep a staffed counter for every service
  that goes online" passes. A statement that fails the test is rewritten
  from the finding's specific detail, or left out.
- No empty verbs ("promote", "value", "support", "strengthen", "foster")
  without a concrete object; no abstract nouns standing alone.
- A disagreement or a trade-off becomes TWO statements, one per side. A
  question becomes the position it implies, or is left out when it implies
  none. A concern becomes the condition or the limit it asks for.
- Keep each statement under 140 characters.
- Write for the public: no "we", no "the table", no table numbers, no
  speaker labels, no names, no quotations.
- Do not repeat the same idea in two statements, across findings either.
- Respect the budget and the order given in the input: findings come in
  priority order; write one statement for each (two for a disagreement),
  then, only while the budget allows, a second statement for the findings
  whose summary holds a second distinct, concrete idea.
- Before answering, re-read your list and rewrite every statement that
  fails the dissent test or names no actor.
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


#: the order the findings are offered to the model and the budget is spent
#: in: what the room converged on first, open questions last
TYPE_RANK = {
    "proposal": 0, "agreement": 1, "disagreement": 2, "concern": 3,
    "new_idea": 4, "minority_position": 5, "question": 6,
}
TARGET_MIN, TARGET_MAX, TARGET_STEP = 10, 60, 10
RECOMMENDED_CAP = 40
#: how long one vote takes on Polis, for the organizer's estimate
SECONDS_PER_VOTE = 8


def prioritised(findings: list[Finding]) -> list[Finding]:
    """Most tables first, then proposals before concerns before questions;
    ties keep the session order."""
    return sorted(
        findings,
        key=lambda f: (-(f.mentioned_table_count or 0), TYPE_RANK.get(f.type, 9)),
    )


def recommended_target(finding_count: int) -> int:
    """About one statement per approved finding, in tens, between 10 and 40:
    attention on Polis drops after some thirty votes, and the organizer can
    still ask for more by hand."""
    if finding_count <= 0:
        return TARGET_MIN
    rounded = int(round(finding_count / TARGET_STEP)) * TARGET_STEP
    return max(TARGET_MIN, min(RECOMMENDED_CAP, rounded))


def statements_per_finding(finding_type: str) -> int:
    return 2 if finding_type == "disagreement" else 1


def within_budget(
    answers: list[tuple[Finding, list[str]]], budget: int
) -> list[tuple[str, str]]:
    """(finding_id, text) pairs chosen from the model's answers, in priority
    order, breadth first: every finding's first statement (a disagreement's
    first two), then second statements while the budget lasts."""
    chosen: list[tuple[str, str]] = []
    if budget <= 0:
        return chosen
    taken = {f.id: 0 for f, _ in answers}
    depth = 0
    while len(chosen) < budget:
        progressed = False
        for finding, statements in answers:
            allowance = statements_per_finding(finding.type) if depth == 0 else 1
            for _ in range(allowance):
                index = taken[finding.id]
                if index < len(statements) and len(chosen) < budget:
                    chosen.append((finding.id, statements[index]))
                    taken[finding.id] = index + 1
                    progressed = True
        if not progressed:
            break
        depth += 1
    return chosen


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

def generate(
    session: Session, store: provider_config.ConfigStore, assembly: Assembly, target: int | None = None
) -> int:
    """Write seeds from the approved findings; returns how many were added.

    `target` is how many statements the organizer wants in all (the
    recommendation when None); statements a person touched count towards it
    and are kept, the rest of the budget is filled from the model's answer
    in priority order (within_budget).

    Commits before the model call so the writer slot is free while the
    network round-trip runs, like analysis.analyze_assembly."""
    findings = prioritised(source_findings(session, assembly))
    if not findings:
        log.info("seeds_no_findings", assembly_id=assembly.id)
        return 0
    if target is None:
        target = assembly.seeds_target or recommended_target(len(findings))
    target = max(TARGET_MIN, min(TARGET_MAX, int(target)))
    assembly.seeds_target = target
    hidden = pseudonyms.name_map(session, assembly)
    existing = list_seeds(session, assembly.id)
    kept = [s for s in existing if s.touched]
    for seed in existing:
        if not seed.touched:
            session.delete(seed)
    session.flush()
    budget = max(0, target - len(kept))
    lines = []
    for finding in findings:
        summary = pseudonyms.redact(finding.summary, hidden)[:1200]
        tables = f"\ntables: {finding.mentioned_table_count}" if finding.scope == "round" else ""
        lines.append(
            f"finding_id: {finding.id}\ntype: {finding.type}{tables}\n"
            f"title: {pseudonyms.redact(finding.title, hidden)}\nsummary: {summary}"
        )
    user_prompt = (
        f"Assembly: {assembly.name}\n"
        f"Budget: at most {budget} statements in total, for the {len(findings)} findings below, "
        "which are in priority order.\n\n" + "\n\n".join(lines)
    )
    language = LANGUAGE_NAMES.get(assembly.language, "English")
    assembly_id, assembly_language = assembly.id, assembly.language
    session.commit()
    base_url, key, model = _analysis_config(store)
    system_prompt = build_system_prompt(SEEDS_SYSTEM, language, store, assembly.analysis_instructions)
    from citizens.domain.analysis_schemas import StatementSeeds

    log.info("seeds_started", assembly_id=assembly_id, findings=len(findings))
    result = chat_json(base_url, key, model, system_prompt, user_prompt, StatementSeeds)

    by_finding = {f.id: f for f in findings}
    seen = {_key(s.text) for s in kept}
    answers: list[tuple[Finding, list[str]]] = []
    for item in result.seeds:
        finding = by_finding.get(item.finding_id)
        if finding is None:
            log.info("seed_unknown_finding", assembly_id=assembly_id)
            continue
        answers.append((finding, clean_statements(item.statements, seen)))
    # the model's answer back in priority order, whatever order it chose
    answers.sort(key=lambda pair: findings.index(pair[0]))
    position = max((s.position for s in kept), default=0)
    added = 0
    for finding_id, text in within_budget(answers, budget):
        position += 1
        session.add(
            StatementSeed(
                assembly_id=assembly_id,
                finding_id=finding_id,
                text=text,
                source_text=text,
                language=assembly_language,
                position=position,
                origin="ai",
            )
        )
        added += 1
    session.commit()
    log.info("seeds_completed", assembly_id=assembly_id, added=added, kept=len(kept), target=target)
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
        "polis_tid": seed.polis_tid,
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
