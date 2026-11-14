# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""From approved findings to Polis statements in three passes, with a trail.

One call that writes and judges at once produced statements that were
grammatical and useless: abstract positions nobody at the tables defended,
single remarks promoted to policy, nothing to tell the organizer where a
statement came from. So the work is split the way an editor would split it:

1. **Ground.** For each finding the model gets the finding and the excerpts
   its evidence cites, and extracts the concrete positions people actually
   took, each tied to the excerpt that supports it.
2. **Draft.** Each claim becomes one statement, written to a style card for
   Polis: one idea, plain words, short, contestable, standing on its own.
3. **Critique.** A second call scores every draft (grounded, contestable, one
   idea, clear), rewrites what can be fixed and drops what cannot.

Selection after that is deterministic (seeds.within_budget): breadth first
across findings in priority order, best-scored statement of a finding first,
near-duplicates removed. Every statement keeps the excerpt and the scores it
was judged on, so the organizer can check one in a look. Transcript text is
read by the model and shown to the organizer; it never reaches Polis.
"""

import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from citizens.db.models import Finding, FindingEvidence, TranscriptSegment
from citizens.db.models.seeds import SEED_MAX_CHARS
from citizens.domain.analysis_schemas import SeedClaims, SeedDrafts, SeedReviews
from citizens.logging_setup import get_logger
from citizens.providers.analysis.openai_compat import chat_json
from citizens.services import pseudonyms
from citizens.services.analysis import build_system_prompt

log = get_logger(__name__)

#: findings per model call: enough context to avoid repeats across findings,
#: small enough that the critic reads every draft with care
BATCH = 6
#: excerpts offered per finding, longest first (the ones that say something)
QUOTES_PER_FINDING = 6
QUOTE_MAX_CHARS = 400
#: word overlap above which two statements are the same idea
DUPLICATE_JACCARD = 0.8

GROUND_SYSTEM = """You are preparing a Polis consultation from the findings of an
in-person citizens' assembly. Your job in this step is NOT to write the
statements yet: it is to find what people at the tables actually claimed.

For each finding you get its title, its summary and numbered excerpts from
the transcripts that the finding cites. Extract the concrete positions people
took — one to four per finding — each as one sentence in plain words.

Rules:
- Respond with ONLY a JSON object: {{"findings": [{{"finding_id": "...",
  "claims": [{{"text": "...", "quote": 1}}]}}]}}
- Copy finding_id EXACTLY from the input. Never invent ids.
- A claim is a position someone could hold or reject, not a topic ("the
  city should keep a staffed counter for every service that goes online",
  not "digital services").
- Take the specifics from the excerpts: the mechanism, the place, the
  number, the condition. Where the excerpts and the summary differ, the
  excerpts win.
- "quote" is the number of the excerpt that best supports the claim, or null
  when the claim rests only on the summary.
- A disagreement yields the two opposite positions. A question yields the
  position it implies, or nothing.
- Skip what is said once in passing and goes nowhere; keep what the table
  argued about or agreed on.
- No names, no table numbers, no speaker labels, no "we".
- Write everything in {language}."""

CRITIC_SYSTEM = """You are the editor of a Polis consultation. You receive draft
statements, each with the claim it was written from and the excerpt that
supports the claim. Participants will vote agree / disagree / pass on each
statement without any context. Judge every draft and fix what you can.

Score each draft from 0 (fails) to 2 (clearly passes) on:
- grounded: the statement says what the claim and the excerpt say — no
  added policy, no generalisation, no detail the excerpt does not carry;
- contestable: a reasonable person could disagree with it; a truism or a
  wish nobody opposes scores 0;
- single_idea: one proposition, no "and", no list, no condition stacked on
  a condition;
- clear: a stranger understands it at first reading, everyday words, no
  jargon, no abbreviation, under about 140 characters.

Then give a verdict: "keep" when every score is 2; "rewrite" when a rewrite
would reach 2 everywhere (and put the rewrite in "text"); "drop" when the
claim itself is a truism, is not supported by its excerpt, or cannot be made
one clear idea. In "text" put the final statement: the rewrite, or the
draft itself when you keep it; leave it empty when you drop it.

Rules:
- Respond with ONLY a JSON object: {{"reviews": [{{"ref": "F1.1",
  "grounded": 2, "contestable": 2, "single_idea": 2, "clear": 2,
  "verdict": "keep", "text": "..."}}]}}
- Copy each ref EXACTLY from the input and review every draft once.
- A rewrite keeps the claim's meaning and the excerpt's specifics; it never
  adds an actor or a measure the people did not mention.
- No names, no table numbers, no speaker labels, no "we".
- Write everything in {language}."""


@dataclass
class Quote:
    segment_id: str
    text: str


@dataclass
class Claim:
    ref: str
    finding: Finding
    text: str
    quote: Quote | None


@dataclass
class Candidate:
    """A statement that survived the critic, with its trail."""

    finding: Finding
    text: str
    claim: str
    quote: Quote | None
    scores: dict | None = None

    @property
    def total(self) -> int:
        return sum(self.scores.values()) if self.scores else 0

    def quality_json(self) -> str:
        return json.dumps({"claim": self.claim, "scores": self.scores}, ensure_ascii=False)


@dataclass
class Trace:
    """What the run asked and how many answers each pass gave, for the log."""

    prompts: list[tuple[str, str]] = field(default_factory=list)
    claims: int = 0
    drafts: int = 0
    kept: int = 0
    rewritten: int = 0
    dropped: int = 0


# --- evidence ----------------------------------------------------------------

def evidence_quotes(
    session: Session, finding: Finding, hidden: dict[str, str], limit: int = QUOTES_PER_FINDING
) -> list[Quote]:
    """The excerpts a finding cites, names masked, speaker labels dropped,
    the ones that say most first, then in the order they were said."""
    rows = list(
        session.execute(
            select(TranscriptSegment)
            .join(FindingEvidence, FindingEvidence.transcript_segment_id == TranscriptSegment.id)
            .where(FindingEvidence.finding_id == finding.id)
        ).scalars()
    )
    substantial = [s for s in rows if len(s.text.strip()) >= 40] or rows
    chosen = sorted(substantial, key=lambda s: len(s.text.strip()), reverse=True)[:limit]
    chosen.sort(key=lambda s: (s.transcript_id, s.start_seconds))
    return [
        Quote(segment_id=s.id, text=pseudonyms.redact(" ".join(s.text.split()), hidden)[:QUOTE_MAX_CHARS])
        for s in chosen
    ]


# --- the three passes --------------------------------------------------------

def _finding_block(label: str, finding: Finding, hidden: dict[str, str], quotes: list[Quote]) -> str:
    summary = pseudonyms.redact(finding.summary, hidden)[:1200]
    tables = f"\ntables: {finding.mentioned_table_count}" if finding.scope == "round" else ""
    lines = [
        f"{label} finding_id: {finding.id}",
        f"type: {finding.type}{tables}",
        f"title: {pseudonyms.redact(finding.title, hidden)}",
        f"summary: {summary}",
    ]
    for number, quote in enumerate(quotes, start=1):
        lines.append(f"excerpt [{number}]: “{quote.text}”")
    return "\n".join(lines)


def ground(
    call, assembly_name: str, language: str, budget: int, findings: list[Finding],
    quotes: dict[str, list[Quote]], hidden: dict[str, str], trace: Trace,
) -> list[Claim]:
    """Pass 1 over batches of findings: the claims, labelled F<n>.<k>."""
    claims: list[Claim] = []
    for start in range(0, len(findings), BATCH):
        batch = findings[start:start + BATCH]
        blocks = [
            _finding_block(f"F{start + i + 1}", f, hidden, quotes.get(f.id, []))
            for i, f in enumerate(batch)
        ]
        user_prompt = (
            f"Assembly: {assembly_name}\n"
            f"Budget: at most {budget} statements in total, for the {len(findings)} findings "
            f"of this assembly, which are in priority order; these are findings "
            f"{start + 1} to {start + len(batch)}.\n\n" + "\n\n".join(blocks)
        )
        trace.prompts.append(("ground", user_prompt))
        result = call(GROUND_SYSTEM, user_prompt, SeedClaims)
        by_id = {f.id: (start + i + 1, f) for i, f in enumerate(batch)}
        answered = set()
        for item in result.findings:
            found = by_id.get(item.finding_id)
            if found is None:
                log.info("seed_unknown_finding")
                continue
            number, finding = found
            answered.add(finding.id)
            batch_quotes = quotes.get(finding.id, [])
            for k, claim in enumerate(item.claims, start=1):
                quote = None
                if claim.quote and 1 <= claim.quote <= len(batch_quotes):
                    quote = batch_quotes[claim.quote - 1]
                text = pseudonyms.redact(" ".join(claim.text.split()), hidden)
                if text:
                    claims.append(Claim(ref=f"F{number}.{k}", finding=finding, text=text, quote=quote))
        # a finding the model skipped still gets one statement written from
        # its title, so a thin answer never silences a finding
        for number, finding in by_id.values():
            if finding.id not in answered:
                claims.append(Claim(
                    ref=f"F{number}.1", finding=finding,
                    text=pseudonyms.redact(finding.title, hidden), quote=None,
                ))
    trace.claims = len(claims)
    return claims


def draft(call, draft_system: str, claims: list[Claim], trace: Trace) -> dict[str, str]:
    """Pass 2: one statement per claim, keyed by the claim's ref."""
    drafts: dict[str, str] = {}
    for start in range(0, len(claims), BATCH * 3):
        batch = claims[start:start + BATCH * 3]
        lines = []
        for claim in batch:
            lines.append(f"{claim.ref}: {claim.text}")
            if claim.quote is not None:
                lines.append(f"  excerpt: “{claim.quote.text}”")
        user_prompt = (
            "Write ONE statement for each claim below, keeping its ref. "
            "Respond with ONLY a JSON object: {\"statements\": [{\"ref\": \"F1.1\", \"text\": \"...\"}]}\n\n"
            + "\n".join(lines)
        )
        trace.prompts.append(("draft", user_prompt))
        result = call(draft_system, user_prompt, SeedDrafts)
        wanted = {c.ref for c in batch}
        for item in result.statements:
            text = " ".join(item.text.split())
            if item.ref in wanted and text:
                drafts.setdefault(item.ref, text)
    trace.drafts = len(drafts)
    return drafts


def critique(call, claims: list[Claim], drafts: dict[str, str], trace: Trace) -> list[Candidate]:
    """Pass 3: scores, rewrites and drops; a draft the critic forgot is kept
    unscored rather than lost."""
    drafted = [c for c in claims if c.ref in drafts]
    candidates: list[Candidate] = []
    for start in range(0, len(drafted), BATCH * 3):
        batch = drafted[start:start + BATCH * 3]
        lines = []
        for claim in batch:
            lines.append(f"{claim.ref}")
            lines.append(f"  statement: {drafts[claim.ref]}")
            lines.append(f"  claim: {claim.text}")
            if claim.quote is not None:
                lines.append(f"  excerpt: “{claim.quote.text}”")
        user_prompt = "Review every draft below.\n\n" + "\n".join(lines)
        trace.prompts.append(("critique", user_prompt))
        result = call(CRITIC_SYSTEM, user_prompt, SeedReviews)
        reviews = {}
        for review in result.reviews:
            reviews.setdefault(review.ref, review)
        for claim in batch:
            review = reviews.get(claim.ref)
            if review is None:
                candidates.append(Candidate(claim.finding, drafts[claim.ref], claim.text, claim.quote))
                continue
            scores = {
                "grounded": review.grounded, "contestable": review.contestable,
                "single_idea": review.single_idea, "clear": review.clear,
            }
            if review.verdict == "drop" or review.grounded == 0:
                trace.dropped += 1
                continue
            text = " ".join((review.text or drafts[claim.ref]).split())
            if review.verdict == "rewrite" and review.text.strip():
                trace.rewritten += 1
            else:
                trace.kept += 1
            candidates.append(Candidate(claim.finding, text, claim.text, claim.quote, scores))
    return candidates


# --- selection ---------------------------------------------------------------

def _words(text: str) -> set[str]:
    """Every token, numbers and single letters included: "until 22" and
    "until 23" are two different statements."""
    return set("".join(ch if ch.isalnum() else " " for ch in text.casefold()).split())


def _same_idea(a: str, b: str) -> bool:
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return False
    return len(wa & wb) / len(wa | wb) >= DUPLICATE_JACCARD


def dedupe(candidates: list[Candidate], taken: list[str]) -> list[Candidate]:
    """Drop statements that repeat an earlier one, or one the organizer
    already has (`taken`), by word overlap; keeps the first occurrence."""
    kept: list[Candidate] = []
    seen = list(taken)
    for candidate in candidates:
        if len(candidate.text) > SEED_MAX_CHARS:
            log.info("seed_statement_too_long", chars=len(candidate.text))
            continue
        if any(_same_idea(candidate.text, other) for other in seen):
            continue
        seen.append(candidate.text)
        kept.append(candidate)
    return kept


def by_finding(candidates: list[Candidate], findings: list[Finding]) -> list[tuple[Finding, list[Candidate]]]:
    """Candidates grouped per finding in priority order, best scored first
    (a stable sort: equal scores keep the model's order)."""
    groups: dict[str, list[Candidate]] = {f.id: [] for f in findings}
    for candidate in candidates:
        groups.setdefault(candidate.finding.id, []).append(candidate)
    ordered = []
    for finding in findings:
        items = sorted(groups.get(finding.id, []), key=lambda c: -c.total)
        if items:
            ordered.append((finding, items))
    return ordered


# --- the run -----------------------------------------------------------------

def run(
    session: Session, store, assembly, findings: list[Finding], budget: int,
    taken: list[str], language: str, draft_system: str, config: tuple[str, str, str],
) -> tuple[list[tuple[Finding, list[Candidate]]], Trace]:
    """Ground, draft and critique; returns the candidates grouped per finding
    in priority order, deduplicated against `taken`, and the trace.

    Everything the database must provide is read BEFORE the first model call
    (the caller commits in between), so the session stays idle during the
    network round-trips, like seeds.generate always did."""
    hidden = pseudonyms.name_map(session, assembly)
    quotes = {f.id: evidence_quotes(session, f, hidden) for f in findings}
    assembly_name = assembly.name
    instructions = assembly.analysis_instructions
    session.commit()

    base_url, key, model = config
    trace = Trace()

    def call(system_template: str, user_prompt: str, schema):
        system_prompt = build_system_prompt(system_template, language, store, instructions)
        return chat_json(base_url, key, model, system_prompt, user_prompt, schema)

    claims = ground(call, assembly_name, language, budget, findings, quotes, hidden, trace)
    drafts = draft(call, draft_system, claims, trace)
    candidates = critique(call, claims, drafts, trace)
    candidates = dedupe(candidates, taken)
    log.info(
        "seed_pipeline_done", assembly_id=assembly.id, claims=trace.claims, drafts=trace.drafts,
        kept=trace.kept, rewritten=trace.rewritten, dropped=trace.dropped,
        candidates=len(candidates),
    )
    return by_finding(candidates, findings), trace
