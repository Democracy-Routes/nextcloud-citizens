# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The seeds pipeline's passes, run against a scripted model: what the critic
drops and keeps, how a skipped finding still gets a statement, how the
duplicates and the ordering fall out. No database, no network."""

import threading
from types import SimpleNamespace

import pytest

from citizens.domain.analysis_schemas import (
    SeedClaim,
    SeedClaims,
    SeedClaimsForFinding,
    SeedDraft,
    SeedDrafts,
    SeedReview,
    SeedReviews,
)
from citizens.providers.analysis.openai_compat import AnalysisError
from citizens.services import seed_pipeline as sp


def _finding(fid, title="Later buses", type_="proposal", scope="round", tables=3):
    return SimpleNamespace(
        id=fid, title=title, summary=f"Summary of {title}.", type=type_, scope=scope,
        mentioned_table_count=tables,
    )


def _quote(fid, text="The last bus leaves at ten and the shift ends at eleven, so people walk."):
    return sp.Quote(segment_id=f"seg-{fid}", text=text)


class TestGround:
    def test_claims_carry_their_quote_and_a_skipped_finding_falls_back_to_its_title(self):
        f1, f2 = _finding("a"), _finding("b", title="Cycle lanes", type_="concern")
        trace = sp.Trace()

        def call(system, user, schema):
            assert schema is SeedClaims
            assert "F1 finding_id: a" in user and "F2 finding_id: b" in user
            assert "excerpt [1]" in user and "Budget: at most 10" in user
            return SeedClaims(findings=[
                SeedClaimsForFinding(finding_id="a", claims=[
                    SeedClaim(text="Buses should run until the shift ends", quote=1),
                    SeedClaim(text="Night taxis are too dear", quote=9),  # no such excerpt
                ]),
                SeedClaimsForFinding(finding_id="nope", claims=[SeedClaim(text="ignored")]),
            ])

        claims = sp.ground(call, "A", "English", 10, [f1, f2], {"a": [_quote("a")]}, {}, trace)
        assert [(c.ref, c.finding.id) for c in claims] == [("F1.1", "a"), ("F1.2", "a"), ("F2.1", "b")]
        assert claims[0].quote is not None and claims[0].quote.segment_id == "seg-a"
        assert claims[1].quote is None
        assert claims[2].text == "Cycle lanes" and claims[2].quote is None
        assert trace.claims == 3

    def test_names_are_masked_in_what_the_model_writes(self):
        f1 = _finding("a")

        def call(system, user, schema):
            assert "Anna" not in user
            return SeedClaims(findings=[SeedClaimsForFinding(
                finding_id="a", claims=[SeedClaim(text="Anna wants later buses")],
            )])

        f1.summary = "Anna asked for later buses."
        claims = sp.ground(call, "A", "English", 10, [f1], {}, {"Anna": "Participant 1"}, sp.Trace())
        assert claims[0].text == "Participant 1 wants later buses"


class TestDraftAndCritique:
    def _claims(self):
        f1, f2 = _finding("a"), _finding("b", title="Cycle lanes")
        return [
            sp.Claim("F1.1", f1, "Buses should run until the shift ends", _quote("a")),
            sp.Claim("F1.2", f1, "Everyone should be included", None),
            sp.Claim("F2.1", f2, "Lanes need lights", None),
        ]

    def test_drafts_keep_their_refs_and_unknown_refs_are_ignored(self):
        def call(system, user, schema):
            assert schema is SeedDrafts and "F1.1: Buses" in user and "excerpt:" in user
            return SeedDrafts(statements=[
                SeedDraft(ref="F1.1", text="Evening buses should run until midnight."),
                SeedDraft(ref="F9.9", text="Nope."),
                SeedDraft(ref="F2.1", text="  Cycle lanes should be lit at night. "),
            ])

        drafts = sp.draft(call, "style card", self._claims(), sp.Trace())
        assert drafts == {
            "F1.1": "Evening buses should run until midnight.",
            "F2.1": "Cycle lanes should be lit at night.",
        }

    def test_the_critic_rewrites_drops_and_a_forgotten_draft_is_kept_unscored(self):
        claims = self._claims()
        drafts = {
            "F1.1": "Evening buses should run until midnight.",
            "F1.2": "Everyone should be included.",
            "F2.1": "Cycle lanes should be lit at night.",
        }
        trace = sp.Trace()

        def call(system, user, schema):
            assert schema is SeedReviews and "statement: Everyone" in user
            return SeedReviews(reviews=[
                SeedReview(ref="F1.1", grounded=2, contestable=2, single_idea=2, clear=1,
                           verdict="rewrite", text="Evening buses should run until the last shift ends."),
                SeedReview(ref="F1.2", grounded=1, contestable=0, single_idea=2, clear=2,
                           verdict="drop", text=""),
            ])

        candidates = sp.critique(call, claims, drafts, trace)
        assert [c.text for c in candidates] == [
            "Evening buses should run until the last shift ends.",
            "Cycle lanes should be lit at night.",
        ]
        assert candidates[0].scores == {"grounded": 2, "contestable": 2, "single_idea": 2, "clear": 1}
        assert candidates[0].quote.segment_id == "seg-a"
        assert candidates[1].scores is None  # the critic forgot it: kept, not lost
        assert (trace.rewritten, trace.dropped, trace.kept) == (1, 1, 0)
        assert '"claim": "Buses should run' in candidates[0].quality_json()

    def test_a_draft_the_critic_calls_ungrounded_is_dropped_even_when_kept(self):
        claims = self._claims()[:1]
        drafts = {"F1.1": "The city should ban cars."}

        def call(system, user, schema):
            return SeedReviews(reviews=[SeedReview(
                ref="F1.1", grounded=0, contestable=2, single_idea=2, clear=2, verdict="keep", text="",
            )])

        assert sp.critique(call, claims, drafts, sp.Trace()) == []


class TestSelection:
    def test_duplicates_and_statements_the_organizer_has_are_removed(self):
        f = _finding("a")
        cands = [
            sp.Candidate(f, "Evening buses should run until midnight.", "c", None),
            sp.Candidate(f, "Evening buses should run until midnight", "c", None),  # same words
            sp.Candidate(f, "Cycle lanes should be lit at night.", "c", None),
            sp.Candidate(f, "x" * 401, "c", None),
        ]
        kept = sp.dedupe(cands, taken=["Cycle lanes should be lit at night"])
        assert [c.text for c in kept] == ["Evening buses should run until midnight."]

    def test_grouping_keeps_the_priority_order_and_puts_the_best_scored_first(self):
        f1, f2 = _finding("a"), _finding("b")
        full = {"grounded": 2, "contestable": 2, "single_idea": 2, "clear": 2}
        weak = {"grounded": 2, "contestable": 1, "single_idea": 2, "clear": 1}
        cands = [
            sp.Candidate(f2, "B weak", "c", None, weak),
            sp.Candidate(f1, "A first", "c", None, weak),
            sp.Candidate(f1, "A best", "c", None, full),
            sp.Candidate(f2, "B unscored", "c", None, None),
        ]
        grouped = sp.by_finding(cands, [f1, f2])
        assert [(f.id, [c.text for c in items]) for f, items in grouped] == [
            ("a", ["A best", "A first"]),
            ("b", ["B weak", "B unscored"]),
        ]

    def test_equal_scores_keep_the_models_order(self):
        f = _finding("a")
        cands = [sp.Candidate(f, f"S{n}", "c", None, None) for n in range(4)]
        [(_, items)] = sp.by_finding(cands, [f])
        assert [c.text for c in items] == ["S0", "S1", "S2", "S3"]


class TestBatches:
    """A pass over many findings is several calls; they run side by side, a
    transient failure is tried once more, and the answers are put back in
    batch order."""

    def _findings(self, n):
        return [_finding(f"f{i}", title=f"Finding {i}") for i in range(n)]

    def _claims_for(self, batch_findings):
        return SeedClaims(findings=[
            SeedClaimsForFinding(finding_id=f.id, claims=[SeedClaim(text=f"Claim of {f.title}")])
            for f in batch_findings
        ])

    def test_the_batches_of_a_pass_run_at_the_same_time_and_keep_their_order(self):
        findings = self._findings(13)  # three batches of six, six, one
        by_id = {f.id: f for f in findings}
        gate = threading.Barrier(3, timeout=5)  # trips unless all three run together

        def call(system, user, schema):
            gate.wait()
            ids = [line.split("finding_id: ")[1] for line in user.splitlines() if "finding_id:" in line]
            return self._claims_for([by_id[i] for i in ids])

        claims = sp.ground(call, "A", "English", 30, findings, {}, {}, sp.Trace())
        assert [c.ref for c in claims] == [f"F{n}.1" for n in range(1, 14)]
        assert [c.text for c in claims] == [f"Claim of Finding {i}" for i in range(13)]

    def test_a_transient_failure_of_one_batch_is_tried_once_more(self, monkeypatch):
        monkeypatch.setattr(sp.time, "sleep", lambda seconds: None)
        findings = self._findings(2)
        attempts = []

        def call(system, user, schema):
            attempts.append(user)
            if len(attempts) == 1:
                raise AnalysisError("Analysis request failed: ReadTimeout", retry_after=1)
            return self._claims_for(findings)

        trace = sp.Trace()
        claims = sp.ground(call, "A", "English", 10, findings, {}, {}, trace)
        assert len(attempts) == 2 and attempts[0] == attempts[1]
        assert [c.text for c in claims] == ["Claim of Finding 0", "Claim of Finding 1"]
        assert len(trace.prompts) == 1, "a retry is not a new prompt"

    def test_a_second_failure_or_a_permanent_one_ends_the_run(self, monkeypatch):
        monkeypatch.setattr(sp.time, "sleep", lambda seconds: None)
        findings = self._findings(1)

        def always(system, user, schema):
            raise AnalysisError("Analysis endpoint returned HTTP 502", status=502)

        with pytest.raises(AnalysisError):
            sp.ground(always, "A", "English", 10, findings, {}, {}, sp.Trace())

        calls = []

        def refused(system, user, schema):
            calls.append(1)
            raise AnalysisError("Model output failed validation after retries", permanent=True)

        with pytest.raises(AnalysisError):
            sp.draft(refused, "style", [sp.Claim("F1.1", findings[0], "x", None)], sp.Trace())
        assert len(calls) == 1, "a permanent refusal is not retried"
