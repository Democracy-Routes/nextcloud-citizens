# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The AI facilitator (0.7): a quiet voice beside the table, opt-in.

Once a minute (jobs/sweep.py) it looks at every table of every running
session whose level is not Off: how much time is left, what the live
captions say was said since it last spoke, how the speaking time is spread
when the engine labels speakers. When one of its triggers fires — time
running out, silence, a stretch of new discussion, one voice dominating — it
asks a language model for ONE short sentence (a gentle question, a reminder
of the objective, a time note) or nothing, and delivers it:

- to the facilitator's own phone when one is connected to the table
  (services/facilitators.py), as an advice card the facilitator may dismiss
  or send on to the table;
- to the table's phones otherwise, as a banner labelled "AI facilitator".

Levels (Off / Light / Normal / Active) bound how often and how much it
speaks per session; three "not helpful" thumbs at a table silence it there.
The model and its key are the Settings' own for the facilitator, falling
back to the analysis model's. Captions reach the model pseudonymised, never
raw names; nothing here touches the recording or the transcript of record.

Config is read from the in-memory snapshot and the key from Nextcloud BEFORE
any database transaction; the model is called with no transaction open; the
delivery is one short write. The sweep is best-effort: a failure is logged
and the next minute tries again.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from citizens.db.models import (
    Assembly,
    FacilitatorFeedback,
    FacilitatorIntervention,
    FacilitatorSession,
    Round,
    TableFacilitation,
)
from citizens.db.models.base import utcnow
from citizens.db.session import read_only_scope, session_scope
from citizens.domain.analysis_schemas import FacilitatorAdvice
from citizens.logging_setup import get_logger
from citizens.providers.analysis.openai_compat import chat_json
from citizens.services import facilitators as facilitators_svc
from citizens.services import live_source, provider_config, pseudonyms, speaking_live
from citizens.services import messages as messages_svc
from citizens.services.audit import record_audit_event
from citizens.services.live_captions import LIVE_CAPTIONS

log = get_logger(__name__)

LEVELS = ("off", "light", "normal", "active")
#: how many times it may speak to one table in one session, by level
MAX_PER_SESSION = {"light": 2, "normal": 4, "active": 8}
#: how many new caption lines count as "a stretch of discussion", by level
MIN_NEW_LINES = {"light": 14, "normal": 8, "active": 5}
#: "not helpful" thumbs at a table (whole assembly) after which it stays quiet there
UNHELPFUL_THROTTLE = 3
#: how long an undelivered advice card stays on the facilitator's phone
ADVICE_VISIBLE = timedelta(minutes=30)
#: how many recent caption lines the model reads
CAPTION_CONTEXT = 40
#: the time nudge fires inside the last three minutes, and within the first
#: ten minutes of overrun
TIME_NUDGE_BEFORE_S = 180
TIME_NUDGE_AFTER_S = -600

SYSTEM_PROMPT = """You are a quiet assistant to the facilitator of ONE small-group table at an
in-person citizens' assembly. Every minute you may be shown what the table
said recently (automatic captions, imperfect), the session's question and
objective, how much time is left, and sometimes how speaking time is spread
between anonymous voices. You decide whether ONE short sentence would help
the group right now — or whether silence is better. Silence is usually
better.

Respond with ONLY a JSON object: {{"kind": "time"|"objective"|"silence"|"balance"|"none",
"text": "..."}}.

Rules:
- "none" with empty text whenever nothing clearly useful can be said. Prefer it.
- At most ONE sentence, under 25 words, addressed to the whole table, in
  {language}. A gentle question or a plain reminder, never an instruction
  barked, never a judgement of anyone.
- "time": only when the time facts given make it relevant (a few minutes left,
  or the time is over) — say what to do with the time, not just the number.
- "objective": the discussion has drifted or the objective is still untouched;
  remind the group what the session should produce, in their own terms.
- "silence": the captions show a long pause; offer one open question from the
  session's own question.
- "balance": ONLY when speaking-time figures are given AND show one voice far
  ahead; invite voices not yet heard, without naming or counting anyone.
  Never use "balance" when no figures are given.
- Never repeat earlier advice given to this table; never quote participants;
  never mention percentages, speaker labels, captions, or that you are an AI.
- Never state or imply what "most people" think."""


# ---------------------------------------------------------------- levels --


def set_table_level(
    session: Session, assembly: Assembly, table_number: int, level: str | None, actor: str
) -> dict:
    """A table's own switch: `level` in LEVELS, or None to follow the assembly."""
    if level is not None and level not in LEVELS:
        raise HTTPException(status_code=422, detail="Unknown facilitator level")
    row = session.execute(
        select(TableFacilitation).where(
            TableFacilitation.assembly_id == assembly.id,
            TableFacilitation.table_number == table_number,
        )
    ).scalar_one_or_none()
    if level is None:
        if row is not None:
            session.delete(row)
    elif row is None:
        session.add(
            TableFacilitation(
                assembly_id=assembly.id, table_number=table_number, level=level, updated_by=actor
            )
        )
    else:
        row.level = level
        row.updated_by = actor
    session.flush()
    record_audit_event(
        session, "facilitator_level_set", "assembly", assembly.id, actor=actor,
        data={"table": table_number, "level": level or "default"},
    )
    return table_level_state(session, assembly, table_number)


def table_overrides(session: Session, assembly_id: str) -> dict[int, str]:
    rows = session.execute(
        select(TableFacilitation).where(TableFacilitation.assembly_id == assembly_id)
    ).scalars()
    return {row.table_number: row.level for row in rows}


def effective_level(
    assembly: Assembly, override: str | None, instance: dict | None = None
) -> str:
    """Table override > assembly level > instance default."""
    if override in LEVELS:
        return override
    if assembly.ai_facilitator in LEVELS:
        return assembly.ai_facilitator
    settings = instance if instance is not None else provider_config.facilitator_settings_cached()
    level = settings.get("level", "off")
    return level if level in LEVELS else "off"


def table_level_state(session: Session, assembly: Assembly, table_number: int) -> dict:
    """What a phone or the Live tab shows about a table's AI facilitator."""
    override = table_overrides(session, assembly.id).get(table_number)
    settings = provider_config.facilitator_settings_cached()
    return {
        "level": effective_level(assembly, override, settings),
        "override": override,
        "assembly_level": assembly.ai_facilitator,
        "instance_level": settings.get("level", "off"),
        "configured": bool(settings.get("configured")),
    }


# ------------------------------------------------------------------ tick --


@dataclass
class Candidate:
    assembly_id: str
    assembly_name: str
    round_id: str
    table_number: int
    level: str
    language: str
    user_prompt: str
    caption_t: float | None
    triggers: list[str] = field(default_factory=list)


def _lines_for(recording_id: str) -> list[dict]:
    return [
        line for line in LIVE_CAPTIONS.status(recording_id).get("lines", [])
        if not line.get("provisional") and line.get("text")
    ]


def _history(session: Session, round_id: str, table_number: int) -> list[FacilitatorIntervention]:
    return list(
        session.execute(
            select(FacilitatorIntervention)
            .where(
                FacilitatorIntervention.round_id == round_id,
                FacilitatorIntervention.table_number == table_number,
            )
            .order_by(FacilitatorIntervention.created_at.asc())
        ).scalars()
    )


def unhelpful_count(session: Session, assembly_id: str, table_number: int) -> int:
    return int(
        session.execute(
            select(func.count(FacilitatorFeedback.id))
            .join(
                FacilitatorIntervention,
                FacilitatorIntervention.id == FacilitatorFeedback.intervention_id,
            )
            .where(
                FacilitatorIntervention.assembly_id == assembly_id,
                FacilitatorFeedback.table_number == table_number,
                FacilitatorFeedback.helpful.is_(False),
            )
        ).scalar_one()
        or 0
    )


def _consider(
    session: Session, round_: Round, table, level: str, settings: dict, now: datetime
) -> Candidate | None:
    """One table of one running session: is there a reason to speak, and what
    would the model be told? None when it should stay quiet this minute."""
    assembly = round_.assembly
    history = _history(session, round_.id, table.number)
    if len(history) >= MAX_PER_SESSION[level]:
        return None
    interval = timedelta(minutes=int(settings.get("interval_minutes", 4)))
    if history and now - history[-1].created_at < interval:
        return None
    if unhelpful_count(session, assembly.id, table.number) >= UNHELPFUL_THROTTLE:
        return None
    recording = live_source.current(session, round_.id, table.id)
    if recording is None:
        return None
    lines = _lines_for(recording.id)
    last_t = max((h.caption_t or 0.0 for h in history), default=None)
    new_lines = [ln for ln in lines if last_t is None or float(ln["t"]) > last_t]

    elapsed = (now - round_.started_at).total_seconds() if round_.started_at else 0.0
    remaining = round_.duration_minutes * 60 - elapsed
    triggers: list[str] = []
    if TIME_NUDGE_AFTER_S < remaining <= TIME_NUDGE_BEFORE_S and not any(
        h.kind == "time" for h in history
    ):
        triggers.append("time")
    rec_elapsed = (
        (now - recording.started_at).total_seconds() if recording.started_at else elapsed
    )
    if lines and rec_elapsed >= 120:
        quiet_for = rec_elapsed - float(lines[-1]["t"])
        if quiet_for >= int(settings.get("silence_seconds", 90)):
            triggers.append("silence")
    if len(new_lines) >= MIN_NEW_LINES[level]:
        triggers.append("content")
    balance = speaking_live.live_balance(lines)
    if balance and balance["largest_percent"] >= int(settings.get("dominance_percent", 60)):
        triggers.append("balance")
    if not triggers:
        return None

    hidden = pseudonyms.name_map(session, assembly)
    recent = lines[-CAPTION_CONTEXT:]
    caption_block = "\n".join(
        f"[{int(float(ln['t']) // 60):02d}:{int(float(ln['t']) % 60):02d}] "
        f"{pseudonyms.redact(str(ln['text']), hidden)}"
        for ln in recent
    ) or "(nothing captioned yet)"
    if balance:
        letters = [chr(65 + i) for i in range(len(balance["shares"]))]
        balance_line = "Speaking time, last 5 minutes: " + ", ".join(
            f"Voice {letter} {share}%" for letter, share in zip(letters, balance["shares"], strict=False)
        )
    else:
        balance_line = "Speaking time: not measured (no \"balance\" advice allowed)."
    earlier = "\n".join(f"- ({h.kind}) {h.text}" for h in history) or "- none yet"
    minutes_left = int(remaining // 60)
    time_line = (
        f"Time: {int(elapsed // 60)} min elapsed of {round_.duration_minutes}; "
        + (f"{minutes_left} min left." if remaining >= 0 else f"over by {-minutes_left} min.")
    )
    objective = f"Objective: {round_.objective}\n" if round_.objective else ""
    user_prompt = (
        f"Assembly: {assembly.name}\nSession {round_.position}: {round_.title}\n"
        f"Question: {round_.question}\n{objective}{time_line}\n{balance_line}\n"
        f"Why you are asked now: {', '.join(triggers)}.\n"
        f"Earlier advice to this table:\n{earlier}\n\n"
        f"Recently said at the table (captions):\n{caption_block}"
    )
    return Candidate(
        assembly_id=assembly.id,
        assembly_name=assembly.name,
        round_id=round_.id,
        table_number=table.number,
        level=level,
        language=assembly.language or "en",
        user_prompt=user_prompt,
        caption_t=float(lines[-1]["t"]) if lines else last_t,
        triggers=triggers,
    )


def plan(session: Session, settings: dict, now: datetime | None = None) -> list[Candidate]:
    """Read-only: every table that deserves a word this minute, with its prompt."""
    now = now or utcnow()
    candidates: list[Candidate] = []
    rounds = session.execute(select(Round).where(Round.status == "ACTIVE")).scalars()
    for round_ in rounds:
        assembly = round_.assembly
        if assembly.closed_at is not None:
            continue
        overrides = table_overrides(session, assembly.id)
        for table in round_.tables:
            level = effective_level(assembly, overrides.get(table.number), settings)
            if level == "off":
                continue
            candidate = _consider(session, round_, table, level, settings, now)
            if candidate is not None:
                candidates.append(candidate)
    return candidates


def ask_model(candidate: Candidate, base_url: str, key: str, model: str) -> FacilitatorAdvice:
    from citizens.services.analysis import LANGUAGE_NAMES

    language = LANGUAGE_NAMES.get(candidate.language, "English")
    system_prompt = SYSTEM_PROMPT.format(language=language)
    return chat_json(base_url, key, model, system_prompt, candidate.user_prompt, FacilitatorAdvice)


def deliver(
    session: Session, candidate: Candidate, advice: FacilitatorAdvice, model: str
) -> FacilitatorIntervention:
    """The facilitator's phone first; the table's phones when none is connected."""
    text = advice.text.strip()
    facilitator = facilitators_svc.connected_for_table(
        session, candidate.assembly_id, candidate.table_number
    )
    intervention = FacilitatorIntervention(
        assembly_id=candidate.assembly_id,
        round_id=candidate.round_id,
        table_number=candidate.table_number,
        kind=advice.kind,
        text=text,
        delivered_to="facilitator" if facilitator else "table",
        facilitator_session_id=facilitator.id if facilitator else None,
        caption_t=candidate.caption_t,
        model=model,
    )
    if facilitator is None:
        round_ = session.get(Round, candidate.round_id)
        if round_ is None or round_.status != "ACTIVE":
            raise HTTPException(status_code=409, detail="The session is no longer running")
        message = messages_svc.post_message(
            session, round_, actor="ai", kind="PROMPT", text=text,
            target_table_number=candidate.table_number, sound=True,
        )
        intervention.message_id = message.id
    session.add(intervention)
    session.flush()
    record_audit_event(
        session, "facilitator_intervention", "assembly", candidate.assembly_id, actor="ai",
        data={
            "intervention_id": intervention.id, "table": candidate.table_number,
            "round_id": candidate.round_id, "kind": advice.kind,
            "delivered_to": intervention.delivered_to, "triggers": candidate.triggers,
            "chars": len(text),
        },
    )
    log.info(
        "facilitator_intervention", assembly_id=candidate.assembly_id,
        table_number=candidate.table_number, kind=advice.kind,
        delivered_to=intervention.delivered_to, triggers=candidate.triggers,
    )
    return intervention


def tick(now: datetime | None = None) -> int:
    """One minute of the AI facilitator. Returns how many tables were spoken to."""
    settings = provider_config.facilitator_settings_cached()
    if not settings or not settings.get("configured"):
        return 0
    with read_only_scope() as session:
        candidates = plan(session, settings, now)
    if not candidates:
        return 0
    # the key is a Nextcloud read: outside any transaction, like the snapshot
    base_url, key, model = provider_config.facilitator_model_config(provider_config.default_store())
    if not key:
        log.info("facilitator_skipped", reason="no_key", tables=len(candidates))
        return 0
    spoken: list[tuple[Candidate, FacilitatorAdvice]] = []
    for candidate in candidates:
        try:
            advice = ask_model(candidate, base_url, key, model)
        except Exception as exc:  # the model failing must never stop the sweep
            log.warning(
                "facilitator_model_failed", assembly_id=candidate.assembly_id,
                table_number=candidate.table_number, error=type(exc).__name__,
            )
            continue
        if advice.kind == "none" or not advice.text.strip():
            log.info(
                "facilitator_quiet", assembly_id=candidate.assembly_id,
                table_number=candidate.table_number, triggers=candidate.triggers,
            )
            continue
        if advice.kind == "balance" and "balance" not in candidate.triggers:
            # the model may not invent a balance problem without figures
            continue
        spoken.append((candidate, advice))
    if not spoken:
        return 0
    delivered = 0
    with session_scope() as session:
        for candidate, advice in spoken:
            try:
                deliver(session, candidate, advice, model)
                delivered += 1
            except HTTPException as exc:
                log.info("facilitator_not_delivered", table_number=candidate.table_number,
                         reason=exc.detail)
    return delivered


# -------------------------------------------- the facilitator's advice --


def as_dict(intervention: FacilitatorIntervention) -> dict:
    return {
        "id": intervention.id,
        "kind": intervention.kind,
        "text": intervention.text,
        "table_number": intervention.table_number,
        "delivered_to": intervention.delivered_to,
        "created_at": intervention.created_at,
        "sent_to_table_at": intervention.sent_to_table_at,
        "dismissed_at": intervention.dismissed_at,
    }


def pending_advice(session: Session, assembly_id: str, table_number: int) -> list[dict]:
    """Advice cards still open on the facilitator's phone for this table."""
    rows = session.execute(
        select(FacilitatorIntervention)
        .where(
            FacilitatorIntervention.assembly_id == assembly_id,
            FacilitatorIntervention.table_number == table_number,
            FacilitatorIntervention.delivered_to == "facilitator",
            FacilitatorIntervention.dismissed_at.is_(None),
            FacilitatorIntervention.sent_to_table_at.is_(None),
            FacilitatorIntervention.created_at >= utcnow() - ADVICE_VISIBLE,
        )
        .order_by(FacilitatorIntervention.created_at.asc())
    ).scalars()
    return [as_dict(row) for row in rows]


def _advice_for(
    session: Session, facilitator: FacilitatorSession, intervention_id: str
) -> FacilitatorIntervention:
    intervention = session.get(FacilitatorIntervention, intervention_id)
    if (
        intervention is None
        or intervention.assembly_id != facilitator.assembly_id
        or intervention.table_number != facilitator.table_number
    ):
        raise HTTPException(status_code=404, detail="No such advice")
    return intervention


def dismiss(session: Session, facilitator: FacilitatorSession, intervention_id: str) -> dict:
    intervention = _advice_for(session, facilitator, intervention_id)
    if intervention.dismissed_at is None:
        intervention.dismissed_at = utcnow()
    return as_dict(intervention)


def send_to_table(session: Session, facilitator: FacilitatorSession, intervention_id: str) -> dict:
    """The facilitator vouches for the advice: it reaches the table's phones
    as THEIR prompt (labelled "From the facilitator")."""
    intervention = _advice_for(session, facilitator, intervention_id)
    if intervention.sent_to_table_at is not None:
        return as_dict(intervention)
    message = facilitators_svc.send_prompt(session, facilitator, intervention.text)
    intervention.sent_to_table_at = utcnow()
    intervention.message_id = message["id"]
    record_audit_event(
        session, "facilitator_advice_sent", "assembly", intervention.assembly_id,
        actor=f"facilitator:{facilitator.id}",
        data={"intervention_id": intervention.id, "table": intervention.table_number},
    )
    return as_dict(intervention)


def give_feedback(
    session: Session, intervention: FacilitatorIntervention, table_number: int, source: str,
    helpful: bool,
) -> dict:
    """A thumb. The last word from one source wins (a mis-tap can be undone)."""
    existing = session.execute(
        select(FacilitatorFeedback).where(
            FacilitatorFeedback.intervention_id == intervention.id,
            FacilitatorFeedback.source == source,
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            FacilitatorFeedback(
                intervention_id=intervention.id, table_number=table_number, source=source,
                helpful=helpful,
            )
        )
    else:
        existing.helpful = helpful
    session.flush()
    record_audit_event(
        session, "facilitator_feedback", "assembly", intervention.assembly_id,
        actor=source,
        data={"intervention_id": intervention.id, "table": table_number, "helpful": helpful},
    )
    return {"intervention_id": intervention.id, "helpful": helpful}


def intervention_for_message(
    session: Session, assembly_id: str, message_id: int
) -> FacilitatorIntervention | None:
    return session.execute(
        select(FacilitatorIntervention).where(
            FacilitatorIntervention.assembly_id == assembly_id,
            FacilitatorIntervention.message_id == message_id,
        )
    ).scalar_one_or_none()


def interventions_for_round(session: Session, round_: Round) -> list[dict]:
    """The Live tab's log: what the AI said at each table, and what people
    thought of it."""
    rows = list(
        session.execute(
            select(FacilitatorIntervention)
            .where(FacilitatorIntervention.round_id == round_.id)
            .order_by(FacilitatorIntervention.created_at.desc())
            .limit(50)
        ).scalars()
    )
    if not rows:
        return []
    thumbs: dict[str, dict[str, int]] = {}
    for intervention_id, helpful, count in session.execute(
        select(
            FacilitatorFeedback.intervention_id, FacilitatorFeedback.helpful,
            func.count(FacilitatorFeedback.id),
        )
        .where(FacilitatorFeedback.intervention_id.in_([r.id for r in rows]))
        .group_by(FacilitatorFeedback.intervention_id, FacilitatorFeedback.helpful)
    ):
        thumbs.setdefault(intervention_id, {"helpful": 0, "not_helpful": 0})
        thumbs[intervention_id]["helpful" if helpful else "not_helpful"] += int(count)
    return [
        {**as_dict(row), "feedback": thumbs.get(row.id, {"helpful": 0, "not_helpful": 0})}
        for row in rows
    ]
