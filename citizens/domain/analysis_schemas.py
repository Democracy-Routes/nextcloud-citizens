# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pydantic schemas that AI analysis output MUST match (brief §37).

Invalid model output is never stored — the provider retries with a correction
prompt, and anything that still fails validation is rejected.
"""

from typing import Literal

from pydantic import BaseModel, Field

FindingType = Literal[
    "proposal", "agreement", "disagreement", "concern",
    "question", "minority_position", "new_idea",
]


class TableFindingItem(BaseModel):
    type: FindingType
    title: str = Field(min_length=3, max_length=300)
    summary: str = Field(min_length=3, max_length=2000)
    support: Literal["strong", "mixed", "weak", "unclear"] | None = None
    evidence_segment_ids: list[str] = Field(min_length=1, max_length=20)


class TableAnalysis(BaseModel):
    # ALWAYS produced: a neutral 2–4 sentence description of the discussion,
    # even when there are no substantive findings
    summary: str = Field(min_length=10, max_length=1500)
    findings: list[TableFindingItem] = Field(max_length=40)


class RoundClusterItem(BaseModel):
    type: FindingType
    title: str = Field(min_length=3, max_length=300)
    summary: str = Field(min_length=3, max_length=2000)
    source_finding_ids: list[str] = Field(min_length=1, max_length=50)


class RoundAnalysis(BaseModel):
    summary: str = Field(min_length=10, max_length=1500)
    clusters: list[RoundClusterItem] = Field(max_length=40)


class SynthesisStage(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    summary: str = Field(min_length=3, max_length=2000)


class AssemblySynthesis(BaseModel):
    """How the discussion developed across sessions: a narrative, the stages
    it went through, and what was carried from one session to the next."""

    narrative: str = Field(min_length=10, max_length=4000)
    stages: list[SynthesisStage] = Field(max_length=12)
    carried_forward: list[str] = Field(default_factory=list, max_length=20)


class FacilitatorAdvice(BaseModel):
    """What the AI facilitator may say about one table, one tick: a kind the
    organizer can filter on and one short sentence — or nothing."""

    kind: Literal["time", "objective", "silence", "balance", "none"]
    text: str = Field(default="", max_length=240)


class StatementSeedItem(BaseModel):
    """One to three statements written from one approved finding."""

    finding_id: str = Field(min_length=1, max_length=64)
    statements: list[str] = Field(min_length=1, max_length=3)


class StatementSeeds(BaseModel):
    """Polis seeds: short, neutral statements participants can agree or
    disagree with, one idea each, no names, no table numbers."""

    seeds: list[StatementSeedItem] = Field(max_length=60)


# --- the seeds pipeline (services/seed_pipeline.py): ground → draft → critique

class SeedClaim(BaseModel):
    """One concrete position people took, in the finding's own words; `quote`
    is the 1-based number of the excerpt that supports it, or null."""

    text: str = Field(min_length=1, max_length=400)
    quote: int | None = None


class SeedClaimsForFinding(BaseModel):
    finding_id: str = Field(min_length=1, max_length=64)
    claims: list[SeedClaim] = Field(max_length=4)


class SeedClaims(BaseModel):
    findings: list[SeedClaimsForFinding] = Field(max_length=40)


class SeedDraft(BaseModel):
    """`ref` is the claim's label from the input ("F3.2"), copied exactly."""

    ref: str = Field(min_length=1, max_length=16)
    text: str = Field(min_length=1, max_length=400)


class SeedDrafts(BaseModel):
    statements: list[SeedDraft] = Field(max_length=120)


class SeedReview(BaseModel):
    """The critic's verdict on one draft: four scores from 0 (fails) to 2
    (clearly passes), what to do, and the text to keep (the rewrite when the
    verdict is rewrite, the draft itself when it is keep)."""

    ref: str = Field(min_length=1, max_length=16)
    grounded: int = Field(ge=0, le=2)
    contestable: int = Field(ge=0, le=2)
    single_idea: int = Field(ge=0, le=2)
    clear: int = Field(ge=0, le=2)
    verdict: Literal["keep", "rewrite", "drop"]
    text: str = Field(default="", max_length=400)


class SeedReviews(BaseModel):
    reviews: list[SeedReview] = Field(max_length=120)
