# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Polis statement seeds: from approved findings to a file Polis can take.

The assembly's findings are long and carry evidence; a Polis conversation
needs short statements a stranger can agree or disagree with, and nothing
else. The statements are written in three passes (seed_pipeline.py: ground
in the cited excerpts, draft, critique), the organizer reviews every one;
approved seeds go out as CSV, JSON or straight to Polis. The model reads
the excerpts a finding cites and the organizer sees the one a statement
rests on; no excerpt, name or table number reaches the file or Polis.

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
from citizens.services import provider_config, seed_pipeline
from citizens.services.analysis import APPROVED_STATUSES, LANGUAGE_NAMES, _analysis_config

log = get_logger(__name__)

EXPORT_SCHEMA = "citizens.statement-seeds/1"

SEEDS_SYSTEM = """You are writing seed statements for a Polis conversation
from claims people made at an in-person citizens' assembly. Participants
will vote agree / disagree / pass on each statement without any context; a
statement nobody could disagree with is useless to them.

You receive claims, each with a ref ("F3.2") and, when there is one, the
excerpt it rests on. Write ONE statement per claim and keep its ref.

Rules:
- Respond with ONLY a JSON object: {{"statements": [{{"ref": "F1.1",
  "text": "..."}}]}}
- Copy each ref EXACTLY from the input. Never invent refs.
- A statement is ONE idea, one sentence, in a neutral declarative voice,
  that a stranger can agree or disagree with: "Evening buses should run
  until midnight", not "Participants wanted later buses".
- Say WHO should do WHAT, concretely, when the claim says so: an actor, an
  action and a concrete object (a service, a place, a rule, a number, a
  condition). Take the specifics from the claim and its excerpt — never add
  an actor or a measure the people did not mention.
- The dissent test: before writing a statement down, ask whether a
  reasonable person could disagree with it. "Public services should include
  everyone" fails; "The city should keep a staffed counter for every service
  that goes online" passes. A claim that fails the test is written as the
  specific position behind it, or marked by leaving its text empty.
- No empty verbs ("promote", "value", "support", "strengthen", "foster")
  without a concrete object; no abstract nouns standing alone.
- A disagreement comes as TWO statements, one per claim; keep each side
  plain and fair.
- Everyday words a stranger understands at first reading; no jargon, no
  abbreviations, no quotation marks; keep each statement under 140
  characters.
- Write for the public: no "we", no "the table", no table numbers, no
  speaker labels, no names.
- Do not repeat the same idea in two statements; when two claims say the
  same thing, write it once and leave the other text empty.
- The budget of the consultation is small: say the one thing the claim says,
  and nothing more.
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


def within_budget(answers: list[tuple[Finding, list]], budget: int) -> list[tuple[str, object]]:
    """(finding_id, item) pairs chosen from the per-finding lists, in
    priority order, breadth first: every finding's first statement (a
    disagreement's first two), then second statements while the budget
    lasts. Items are strings or pipeline Candidates; this only orders them."""
    chosen: list[tuple[str, object]] = []
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
    existing = list_seeds(session, assembly.id)
    kept = [s for s in existing if s.touched]
    for seed in existing:
        if not seed.touched:
            session.delete(seed)
    session.flush()
    budget = max(0, target - len(kept))
    language = LANGUAGE_NAMES.get(assembly.language, "English")
    assembly_id, assembly_language = assembly.id, assembly.language
    config = _analysis_config(store)
    log.info("seeds_started", assembly_id=assembly_id, findings=len(findings), budget=budget)
    # run() reads the excerpts, commits, then talks to the model with the
    # session idle, as analysis.analyze_assembly does
    grouped, _trace = seed_pipeline.run(
        session, store, assembly, findings, budget, [s.text for s in kept],
        language, SEEDS_SYSTEM, config,
    )
    position = max((s.position for s in kept), default=0)
    added = 0
    for finding_id, candidate in within_budget(grouped, budget):
        position += 1
        session.add(
            StatementSeed(
                assembly_id=assembly_id,
                finding_id=finding_id,
                text=candidate.text,
                source_text=candidate.text,
                language=assembly_language,
                position=position,
                origin="ai",
                evidence_text=candidate.quote.text if candidate.quote else None,
                evidence_segment_id=candidate.quote.segment_id if candidate.quote else None,
                quality_json=candidate.quality_json(),
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


def finding_titles(session: Session, seeds: list[StatementSeed]) -> dict[str, str]:
    """The title of each finding the seeds point at, for the organizer's
    "why" line; one query, nothing for seeds whose finding was replaced."""
    ids = {s.finding_id for s in seeds if s.finding_id}
    if not ids:
        return {}
    rows = session.execute(select(Finding.id, Finding.title).where(Finding.id.in_(ids))).all()
    return {finding_id: title for finding_id, title in rows}


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


def quality(seed: StatementSeed) -> dict | None:
    if not seed.quality_json:
        return None
    try:
        return json.loads(seed.quality_json)
    except ValueError:
        return None


def payload(seed: StatementSeed, finding_title: str | None = None) -> dict:
    return {
        "id": seed.id,
        "text": seed.text,
        "finding_title": finding_title,
        "evidence_text": seed.evidence_text,
        "quality": quality(seed),
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
