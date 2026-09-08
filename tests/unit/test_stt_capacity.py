# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The per-provider cap on concurrent transcription work.

Uncapped, every recording phone opens its own connection to the transcription
provider — a plenary room of phones saturates a self-hosted Vosk server (or a
hosted provider's rate limit), EVERY caption session drops at once, and the
whole room flashes "captions unavailable" through failure cooldown. The ledger
in services/stt_capacity.py is the bound; these tests pin its semantics and
how batch (final) transcription waits its turn behind it.
"""

import pytest

from citizens.db.models import AppJob, Recording
from citizens.db.models.assembly import Assembly, Round, Table
from citizens.db.models.base import utcnow
from citizens.db.session import session_scope
from citizens.jobs import handlers, runner
from citizens.jobs.handlers import CapacityBusyError
from citizens.services import provider_config, stt_capacity
from citizens.services.jobs import enqueue_job


@pytest.fixture(autouse=True)
def _clean_ledger():
    stt_capacity.reset_for_tests()
    yield
    stt_capacity.reset_for_tests()


# ------------------------------------------------------------- the ledger


def test_leases_are_counted_per_provider():
    assert stt_capacity.try_acquire("vosk", 2)
    assert stt_capacity.try_acquire("vosk", 2)
    assert not stt_capacity.try_acquire("vosk", 2), "a third lease broke the cap"
    # another provider's budget is untouched
    assert stt_capacity.try_acquire("mistral", 1)


def test_release_frees_a_slot():
    assert stt_capacity.try_acquire("vosk", 1)
    assert not stt_capacity.try_acquire("vosk", 1)
    stt_capacity.release("vosk")
    assert stt_capacity.try_acquire("vosk", 1)


def test_a_double_release_cannot_poison_the_ledger():
    stt_capacity.release("vosk")  # nothing held: logged, ignored
    assert stt_capacity.in_use("vosk") == 0
    assert stt_capacity.try_acquire("vosk", 1), (
        "a stray release drove the counter negative and now blocks real work"
    )


def test_a_zero_or_negative_limit_denies():
    # limit 0 reaches the ledger only for unknown providers; deny, don't crash
    assert not stt_capacity.try_acquire("vosk", 0)
    assert not stt_capacity.try_acquire("vosk", -1)


# ------------------------------------------- the config that feeds the limit


class _MemoryStore:
    def __init__(self, values=None):
        self.values = values or {}

    def get_value(self, key):
        return self.values.get(key)

    def set_value(self, key, value, sensitive=False):
        self.values[key] = value

    def delete_value(self, key):
        self.values.pop(key, None)


def test_limits_come_from_settings_with_shipped_defaults():
    store = _MemoryStore()
    assert provider_config.stt_concurrency_limit(store, "mistral", "live") == 15
    assert provider_config.stt_concurrency_limit(store, "vosk", "live") == 5
    # live and batch are separate settings with separate defaults
    assert provider_config.stt_concurrency_limit(store, "mistral", "batch") == 5
    assert provider_config.stt_concurrency_limit(store, "vosk", "batch") == 2
    store.set_value("stt_concurrency_vosk_live", "2")
    assert provider_config.stt_concurrency_limit(store, "vosk", "live") == 2
    assert provider_config.stt_concurrency_limit(store, "vosk", "batch") == 2


def test_garbage_or_zero_in_settings_degrades_to_the_default_not_to_off():
    """A typo must never silently turn captions off for the whole server."""
    store = _MemoryStore({"stt_concurrency_vosk_live": "banana"})
    assert provider_config.stt_concurrency_limit(store, "vosk", "live") == 5
    store.set_value("stt_concurrency_vosk_live", "0")
    assert provider_config.stt_concurrency_limit(store, "vosk", "live") == 5
    assert provider_config.stt_concurrency_limit(store, "not-a-provider", "live") == 0
    assert provider_config.stt_concurrency_limit(store, "vosk", "not-a-kind") == 0


# ------------------------------------- batch transcription waits its turn


def _recording(state="AUDIO_READY") -> str:
    with session_scope() as session:
        assembly = Assembly(name="TEST Capacity", created_by="tester")
        session.add(assembly)
        session.flush()
        round_ = Round(assembly_id=assembly.id, position=1)
        session.add(round_)
        session.flush()
        table = Table(round_id=round_.id, number=1)
        session.add(table)
        session.flush()
        recording = Recording(
            assembly_id=assembly.id, round_id=round_.id, table_id=table.id,
            table_number=1, state=state, mime_type="audio/webm",
            canonical_audio_path="assembled/x/rec.webm",
        )
        session.add(recording)
        session.flush()
        return recording.id


def test_a_full_ledger_makes_the_batch_job_wait_not_transcribe(database, monkeypatch):
    recording_id = _recording()
    store = _MemoryStore({"stt_provider": "vosk", "stt_concurrency_vosk_batch": "1"})
    monkeypatch.setattr(provider_config, "default_store", lambda: store)
    monkeypatch.setattr(
        handlers.transcription_svc, "transcribe_recording",
        lambda *a, **k: pytest.fail("transcription ran with every slot taken"),
    )
    assert stt_capacity.try_acquire("vosk:batch", 1)  # another job holds the slot

    with session_scope() as session:
        with pytest.raises(CapacityBusyError):
            handlers.handle_transcribe_final(session, {"recording_id": recording_id})

    assert stt_capacity.in_use("vosk:batch") == 1, "the denied attempt leaked a lease"


def test_a_full_live_pool_does_not_block_batch(database, monkeypatch):
    """Live and batch are independent pools: a live event holding every
    caption slot must not stall the canonical transcripts behind it."""
    recording_id = _recording()
    store = _MemoryStore({
        "stt_provider": "vosk",
        "stt_concurrency_vosk_live": "1",
        "stt_concurrency_vosk_batch": "1",
    })
    monkeypatch.setattr(provider_config, "default_store", lambda: store)
    monkeypatch.setattr(handlers, "_maybe_enqueue_analysis", lambda *a, **k: None)
    monkeypatch.setattr(
        handlers.transcription_svc, "transcribe_recording", lambda *a, **k: None
    )
    assert stt_capacity.try_acquire("vosk:live", 1)  # captions saturated

    with session_scope() as session:
        handlers.handle_transcribe_final(session, {"recording_id": recording_id})

    assert stt_capacity.in_use("vosk:batch") == 0


def test_the_lease_is_released_after_transcription_success_and_failure(
    database, monkeypatch
):
    recording_id = _recording()
    store = _MemoryStore({"stt_provider": "vosk", "stt_concurrency_vosk_batch": "1"})
    monkeypatch.setattr(provider_config, "default_store", lambda: store)
    monkeypatch.setattr(
        handlers, "_maybe_enqueue_analysis", lambda *a, **k: None
    )

    monkeypatch.setattr(
        handlers.transcription_svc, "transcribe_recording", lambda *a, **k: None
    )
    with session_scope() as session:
        handlers.handle_transcribe_final(session, {"recording_id": recording_id})
    assert stt_capacity.in_use("vosk:batch") == 0, "success leaked its lease"

    from citizens.providers.transcription.base import TranscriptionError

    failing_id = _recording()

    def boom(*_a, **_k):
        raise TranscriptionError("provider down", permanent=False)

    monkeypatch.setattr(handlers.transcription_svc, "transcribe_recording", boom)
    with session_scope() as session:
        with pytest.raises(TranscriptionError):
            handlers.handle_transcribe_final(session, {"recording_id": failing_id})
    assert stt_capacity.in_use("vosk:batch") == 0, "failure leaked its lease"


def test_waiting_for_capacity_burns_no_attempt(database, monkeypatch):
    """The retry ladder is for failures. A job waiting for a live event to
    release its slots can wait hours — it must not march to FAILED."""
    with session_scope() as session:
        job = enqueue_job(session, "TRANSCRIBE_FINAL", {"recording_id": "r"})
        job_id = job.id

    claimed = runner._claim_next_job()
    assert claimed == job_id

    def busy(_session, _payload):
        raise CapacityBusyError("vosk is at its concurrency cap")

    monkeypatch.setitem(handlers.HANDLERS, "TRANSCRIBE_FINAL", busy)
    runner._run_job(job_id)

    with session_scope() as session:
        job = session.get(AppJob, job_id)
        assert job.state == "RETRY"
        assert job.attempts == 0, "waiting consumed an attempt"
        assert job.locked_at is None
        assert job.next_attempt_at > utcnow(), "no delay before the next look"
