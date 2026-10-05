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
