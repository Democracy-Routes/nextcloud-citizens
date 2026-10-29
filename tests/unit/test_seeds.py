# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Polis seeds, the pure parts: what the model's statements go through
before they are stored, when an export is allowed, and what the files
look like."""

import csv
import io
import json
from datetime import UTC, datetime

from citizens.db.models import Assembly, StatementSeed
from citizens.db.models.seeds import SEED_MAX_CHARS
from citizens.services import seeds


def _seed(text, status="DRAFT", origin="ai", source=None, position=0):
    return StatementSeed(
        text=text, source_text=text if source is None else source, status=status,
        origin=origin, position=position, language="en",
    )


def test_statements_are_trimmed_deduplicated_and_capped():
    seen: set[str] = set()
    kept = seeds.clean_statements(
        ["  Evening buses should  run until midnight. ", "", "evening buses should run until midnight",
         "x" * (SEED_MAX_CHARS + 1), "Bike lanes need lighting"],
        seen,
    )
    assert kept == ["Evening buses should run until midnight.", "Bike lanes need lighting"]
    # a later finding repeating the idea adds nothing
    assert seeds.clean_statements(["Bike lanes need lighting!"], seen) == []


def test_a_person_touching_a_seed_protects_it_from_regeneration():
    assert not _seed("a").touched
    assert _seed("a", status="APPROVED").touched
    assert _seed("a", status="REJECTED").touched
    assert _seed("a", origin="manual").touched
    edited = _seed("rewritten", source="original")
    assert edited.edited and edited.touched


def test_export_needs_every_seed_reviewed_and_one_approved():
    assert not seeds.ready_to_export([])
    assert not seeds.ready_to_export([_seed("a", "APPROVED"), _seed("b")])
    assert not seeds.ready_to_export([_seed("a", "REJECTED")])
    assert seeds.ready_to_export([_seed("a", "APPROVED"), _seed("b", "REJECTED")])
    assert seeds.ready_to_export([_seed("a", "EXPORTED")])


def test_csv_quotes_commas_and_quotes_like_rfc_4180():
    rows = [_seed('Buses should run "late", every night', "APPROVED"), _seed("Plain", "APPROVED")]
    text = seeds.render_csv(rows)
    assert text.startswith("position,statement\r\n")
    parsed = list(csv.reader(io.StringIO(text)))
    assert parsed == [
        ["position", "statement"], ["1", 'Buses should run "late", every night'], ["2", "Plain"]
    ]


def test_json_carries_statement_text_only():
    assembly = Assembly(name="Comune di Prova", language="it", created_by="anna")
    rows = [_seed("Più autobus la sera", "APPROVED", position=2)]
    body = json.loads(seeds.render_json(assembly, rows, datetime(2026, 10, 29, 12, tzinfo=UTC)))
    assert body["schema"] == "citizens.statement-seeds/1"
    assert body["assembly"] == {"name": "Comune di Prova", "language": "it"}
    assert body["exported_at"] == "2026-10-29T12:00:00+00:00"
    assert body["statements"] == [{"position": 1, "statement": "Più autobus la sera"}]
    assert set(body["statements"][0]) == {"position", "statement"}


def test_export_filename_is_short_and_without_spaces():
    assembly = Assembly(
        name="A very long assembly name that goes on and on and on", language="en", created_by="a"
    )
    assert seeds.export_filename(assembly, "csv") == "A-very-long-assembly-name-that-goes-on-a-statements.csv"


def test_the_prompt_asks_for_the_assembly_language():
    from citizens.services.analysis import LANGUAGE_NAMES

    assert "Write everything in {language}." in seeds.SEEDS_SYSTEM
    assert seeds.SEEDS_SYSTEM.format(language=LANGUAGE_NAMES["de"]).endswith("German.")
