# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Keeping participants' names out of what is sent to the analysis model.

Speaker labels were already anonymous — SPEAKER_01, never a name. But people
say each other's names out loud, and the transcript records what was said. A
real report carried "Simone, you spoke too much, you should let other people…",
which is a named criticism of a participant, printed.

**This protects the analysis step only.** Two things leave the server: audio
goes to the transcription provider, and transcript text goes to the analysis
model. The audio carries the names as spoken, so nothing here can hide them
from a transcription provider — the answer to that is to self-host it, which
Vosk and a local Whisper endpoint both allow.

**Redact what is sent, keep what is stored.** Transcripts on disk are the
record and the source of the report's quotes; only the copy composed into the
prompt is masked. So a finding the model writes says "[Person A]", while the
evidence beneath it still shows what the table actually said.

Names come from the organizer, never from a guess. The roster they imported,
plus anything they add by hand — nicknames, a surname, a councillor everyone
refers to. A statistical name detector would need a model this host cannot
afford, and a list of common first names would mangle ordinary words: "Ale" is
a name here and a word elsewhere. A list the organizer controls is predictable,
which for a privacy feature is worth more than reach.
"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from citizens.db.models import Assembly, Participant

#: Below this a "name" matches far too much to be worth replacing — a two-letter
#: token appears inside ordinary words and as an abbreviation.
MIN_NAME_LENGTH = 3


def _labels() -> list[str]:
    """Stable, readable stand-ins. Letters before numbers: a discussion rarely
    names more than a handful of people, and "[Person A]" reads as a person in
    a way "[NAME_1]" does not."""
    return [f"[Person {chr(ord('A') + i)}]" for i in range(26)]


def name_map(session: Session, assembly: Assembly) -> dict[str, str]:
    """Every name to hide, mapped to the stand-in used for it.

    One stable label per name for the whole assembly, so the model can still
    follow who is being referred to across a transcript — replacing every name
    with the same token would destroy exactly the discourse the analysis is
    trying to read.
    """
    names: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        for part in re.split(r"[,\n;]+", raw or ""):
            for token in part.split():
                cleaned = token.strip().strip(".,;:!?\"'()[]")
                if len(cleaned) >= MIN_NAME_LENGTH and cleaned.lower() not in seen:
                    seen.add(cleaned.lower())
                    names.append(cleaned)

    for participant in session.execute(
        select(Participant).where(Participant.assembly_id == assembly.id)
    ).scalars():
        add(participant.name or "")
    add(assembly.redact_names or "")

    # longest first: "Anna Maria" must be replaced before "Anna" eats half of it
    names.sort(key=len, reverse=True)
    labels = _labels()
    mapping: dict[str, str] = {}
    for index, name in enumerate(names):
        mapping[name] = labels[index] if index < len(labels) else "[Person]"
    return mapping


def redact(text: str, mapping: dict[str, str]) -> str:
    """Replace known names, matching whole words and ignoring case."""
    if not mapping or not text:
        return text
    for name, label in mapping.items():
        text = re.sub(rf"\b{re.escape(name)}\b", label, text, flags=re.IGNORECASE)
    return text
