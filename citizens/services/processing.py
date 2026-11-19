# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Is anything of an assembly still being processed? Shared by zero retention
and the automatic finish of a Record now session."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from citizens.db.models import Assembly, Recording
from citizens.services.jobs import has_live_job

#: states in which a recording is still being made or uploaded: nothing is
#: deleted under it
TRANSIENT_STATES = (
    "CREATED", "RECORDING", "FINALIZING", "WAITING_FOR_CHUNKS", "ASSEMBLING",
    "TRANSCRIBING", "ANALYZING",
)
PROCESSING_JOBS = ("ASSEMBLE_AUDIO", "TRANSCRIBE_FINAL", "TRANSCRIBE_FROM_LIVE", "ANALYZE_TABLE")
ROUND_JOBS = ("ANALYZE_ROUND",)
ASSEMBLY_JOBS = ("ANALYZE_ASSEMBLY",)


def still_processing(
    session: Session, assembly: Assembly, *, running_round_id: str | None = None
) -> str | None:
    """Why it is too early, or None. `running_round_id`: the round whose
    ANALYZE_ROUND job is the caller itself (it is RUNNING while it asks)."""
    recordings = list(
        session.execute(select(Recording).where(Recording.assembly_id == assembly.id)).scalars()
    )
    for recording in recordings:
        if recording.state in TRANSIENT_STATES:
            return f"recording {recording.id} is {recording.state}"
        for kind in PROCESSING_JOBS:
            if has_live_job(session, kind, "recording_id", recording.id):
                return f"{kind} live for recording {recording.id}"
    for round_ in assembly.rounds:
        if round_.id == running_round_id:
            continue
        for kind in ROUND_JOBS:
            if has_live_job(session, kind, "round_id", round_.id):
                return f"{kind} live for round {round_.id}"
    for kind in ASSEMBLY_JOBS:
        if has_live_job(session, kind, "assembly_id", assembly.id):
            return f"{kind} live"
    return None
