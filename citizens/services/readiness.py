# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Is this table ready to record? A machine-readable answer with its reasons.

Backend complexity should disappear from a healthy room: the future UI says
"Ready" or "Needs attention" and lists exceptions, and an organizer's autopilot
needs the same answer as data. So this returns a status and structured reason
codes — never prose. Wording belongs to the client, in its language.

    READY            every recorder reachable and sound; nothing to do
    NEEDS_ATTENTION  something is off but the table can still run (a backup
                     offline, a low battery, an upload backlog, no captions)
    BLOCKED          nothing can record here: no recorder phone, or every one
                     of them unreachable or unable to capture

Not every problem blocks. One healthy recorder with no backup is READY; one of
two recorders offline is NEEDS_ATTENTION; the only recorder offline is BLOCKED.
Inputs are what the monitor already computes from heartbeats and recordings
(services/rounds.py); this module is pure so the rules are unit-testable.
"""

from dataclasses import dataclass, field

READY = "READY"
NEEDS_ATTENTION = "NEEDS_ATTENTION"
BLOCKED = "BLOCKED"

NO_RECORDER = "NO_RECORDER"
RECORDER_OFFLINE = "RECORDER_OFFLINE"
MIC_UNAVAILABLE = "MIC_UNAVAILABLE"
LOW_STORAGE = "LOW_STORAGE"
LOW_BATTERY = "LOW_BATTERY"
UPLOAD_STALLED = "UPLOAD_STALLED"
LIVE_STT_UNAVAILABLE = "LIVE_STT_UNAVAILABLE"
#: the table raised its hand (services/help.py); never a blocker — the phone
#: may well be recording fine while somebody has a question
HELP_REQUESTED = "HELP_REQUESTED"

BLOCKER = "blocker"
WARNING = "warning"

#: Below this a phone will not last the round (the Live tab's own threshold).
LOW_BATTERY_LEVEL = 0.2
#: Megabytes of free storage under which the next round is at risk.
LOW_STORAGE_MB = 200
#: Chunks captured but not acknowledged: at ~10 s each, twelve is two minutes
#: of audio the server does not have yet — a backlog, not a blip.
UPLOAD_BACKLOG_CHUNKS = 12


@dataclass(frozen=True)
class Reason:
    code: str
    severity: str
    #: the recorder concerned, or None for the table as a whole
    slot: int | None = None
    data: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"code": self.code, "severity": self.severity, "slot": self.slot, "data": self.data}


@dataclass(frozen=True)
class TableReadiness:
    status: str
    reasons: list[Reason]

    def as_dict(self) -> dict:
        return {"status": self.status, "reasons": [reason.as_dict() for reason in self.reasons]}


def _incapacitates(issue: Reason) -> bool:
    """Does this issue leave the recorder unable to record at all? Being
    unreachable, having no microphone, or having nowhere to store audio do; a
    low battery, a thin margin of storage or an upload backlog do not (yet)."""
    if issue.code in (RECORDER_OFFLINE, MIC_UNAVAILABLE):
        return True
    return issue.code == LOW_STORAGE and issue.data.get("storage_ok") is False


def table_readiness(
    recorders: list[dict],
    *,
    live_stt_enabled: bool = False,
    live_source_slot: int | None = None,
    live_caption_reason: str | None = None,
    round_active: bool = False,
    help_requested: str | None = None,
) -> TableReadiness:
    """Decide from the monitor's per-recorder entries.

    Each entry: {slot, connected, status: <heartbeat payload>, recording:
    {state, live_source} | None} — see services/rounds._table_recorders.
    `help_requested` is the kind of help the table asked for, if its hand is
    up: a warning on top of whatever else, so the table stays in view.
    """
    hand = [Reason(HELP_REQUESTED, WARNING, None, {"kind": help_requested})] if help_requested else []
    if not recorders:
        return TableReadiness(BLOCKED, [Reason(NO_RECORDER, BLOCKER), *hand])

    reasons: list[Reason] = []
    sound_slots: list[int] = []
    for recorder in recorders:
        slot = recorder.get("slot")
        status = recorder.get("status") or {}
        recording = recorder.get("recording") or {}
        recording_now = recording.get("state") == "RECORDING"
        issues: list[Reason] = []
        if not recorder.get("connected"):
            issues.append(Reason(
                RECORDER_OFFLINE, WARNING, slot,
                {"seconds_since_contact": recorder.get("seconds_since_contact")},
            ))
        else:
            if recording_now and status.get("capture_ok") is False:
                issues.append(Reason(MIC_UNAVAILABLE, WARNING, slot))
            if status.get("storage_ok") is False:
                issues.append(Reason(LOW_STORAGE, WARNING, slot, {"storage_ok": False}))
            elif isinstance(status.get("storage_free_mb"), (int, float)) and (
                status["storage_free_mb"] < LOW_STORAGE_MB
            ):
                issues.append(Reason(
                    LOW_STORAGE, WARNING, slot, {"storage_free_mb": status["storage_free_mb"]}
                ))
            level = status.get("battery_level")
            if isinstance(level, (int, float)) and level < LOW_BATTERY_LEVEL:
                issues.append(Reason(LOW_BATTERY, WARNING, slot, {"battery_level": level}))
            pending = int(status.get("local_chunks") or 0) - int(status.get("acked_chunks") or 0)
            if pending >= UPLOAD_BACKLOG_CHUNKS:
                issues.append(Reason(UPLOAD_STALLED, WARNING, slot, {"pending_chunks": pending}))
        # a recorder that is reachable and can capture and store is sound,
        # whatever else it warns about
        if not any(_incapacitates(issue) for issue in issues):
            sound_slots.append(slot)
        reasons.extend(issues)

    blocked = not sound_slots
    if blocked:
        # the reasons that leave the table with nobody able to record are the
        # blockers; the rest stay warnings
        reasons = [
            Reason(
                reason.code,
                BLOCKER if reason.code in (RECORDER_OFFLINE, MIC_UNAVAILABLE, LOW_STORAGE) else WARNING,
                reason.slot,
                reason.data,
            )
            for reason in reasons
        ]

    if live_stt_enabled and round_active and any(
        (r.get("recording") or {}).get("state") == "RECORDING" for r in recorders
    ):
        if live_source_slot is None:
            reasons.append(Reason(LIVE_STT_UNAVAILABLE, WARNING, None, {"reason": "no_source"}))
        elif live_caption_reason in ("error", "capacity"):
            reasons.append(Reason(
                LIVE_STT_UNAVAILABLE, WARNING, live_source_slot, {"reason": live_caption_reason}
            ))

    reasons.extend(hand)
    if blocked:
        return TableReadiness(BLOCKED, reasons)
    return TableReadiness(NEEDS_ATTENTION if reasons else READY, reasons)


def summarize(tables: list[dict]) -> dict:
    """Counts for a round: how many tables are READY, NEEDS_ATTENTION, BLOCKED."""
    counts = {READY: 0, NEEDS_ATTENTION: 0, BLOCKED: 0}
    for table in tables:
        counts[table["readiness"]["status"]] += 1
    worst = BLOCKED if counts[BLOCKED] else NEEDS_ATTENTION if counts[NEEDS_ATTENTION] else READY
    return {"status": worst, **{key.lower(): value for key, value in counts.items()}}
