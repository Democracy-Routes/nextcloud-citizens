# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Caption sessions must always be ended by something.

`finish()` had exactly one caller: a successful /complete. The only other way a
session ended was `_garbage_collect`, which ran solely as a side effect of some
OTHER recording's chunk upload. So a phone that died in the last round of the
day was never cleaned up at all — the remaining tables finished inside the idle
timeout and nothing ran again.

Two things were lost each time: the captions the session had already produced,
which are never written to disk unless the session ends (and which, with final
transcription off, are the table's ONLY transcript), and the provider
websocket, which Deepgram's keepalive loop actively held open — a billable
connection kept alive for a phone that was switched off.
"""

import asyncio
import json
import time

from citizens.services import live_captions as lc
from citizens.services.live_captions import LiveCaptionManager, _BaseSession


class _FakeStream:
    """Stands in for the ffmpeg PcmStream."""

    def __init__(self, *, starts: bool = True):
        self.starts = starts
        self.closed = False

    async def start(self) -> bool:
        return self.starts

    async def close(self) -> None:
        self.closed = True

    def feed(self, _data: bytes) -> None:
        pass

    async def read(self):
        # a real PcmStream returns None once closed, which is what lets the
        # pump task finish instead of parking forever
        if self.closed:
            return None
        await asyncio.sleep(0.01)
        return b""



def _session(tmp_path, recording_id="rec-1", assembly_id="asm-1") -> _BaseSession:
    session = _BaseSession(recording_id, "", "model", "en", assembly_id=assembly_id)
    session.lines = [{"t": 0.0, "end": 2.0, "text": "we should widen the cycle lanes"}]
    return session


def test_an_idle_session_is_reaped_without_any_other_upload(settings_env, tmp_path):
    asyncio.run(_test_an_idle_session_is_reaped_without_any_other_upload(settings_env, tmp_path))


async def _test_an_idle_session_is_reaped_without_any_other_upload(settings_env, tmp_path):
    """The whole point: no other table has to upload anything."""
    manager = LiveCaptionManager()
    session = _session(tmp_path)
    session.pcm_stream = _FakeStream()
    session.last_fed = time.monotonic() - (lc.SESSION_IDLE_TIMEOUT + 5)
    session.task = asyncio.get_running_loop().create_task(
        manager._run_and_persist(session)
    )
    manager._sessions[session.recording_id] = session

    await manager.reap_idle()

    assert session.recording_id not in manager._sessions
    assert session.pcm_stream.closed, "the decoder was left running"

    path = lc.live_caption_path(
        settings_env.app_persistent_storage, "asm-1", session.recording_id
    )
    assert path.exists(), "the captions it had already produced were never written down"
    assert "cycle lanes" in json.dumps(json.loads(path.read_text()))


def test_a_session_still_being_fed_is_left_alone(settings_env):
    asyncio.run(_test_a_session_still_being_fed_is_left_alone(settings_env))


async def _test_a_session_still_being_fed_is_left_alone(settings_env):
    manager = LiveCaptionManager()
    session = _BaseSession("rec-live", "", "m", "en", assembly_id="asm-1")
    session.last_fed = time.monotonic()
    manager._sessions["rec-live"] = session

    await manager.reap_idle()

    assert "rec-live" in manager._sessions


def test_a_failed_session_is_disposed_before_its_replacement(settings_env, monkeypatch):
    asyncio.run(_test_a_failed_session_is_disposed_before_its_replacement(settings_env, monkeypatch))


async def _test_a_failed_session_is_disposed_before_its_replacement(settings_env, monkeypatch):
    """The cooldown path used to drop the session without closing the stream,
    orphaning ffmpeg: _pump_pcm parks forever on a queue nobody drains, so its
    cleanup never runs and the reaper can no longer see the session either."""
    manager = LiveCaptionManager()
    manager.set_loop(asyncio.get_running_loop())

    dead = _BaseSession("rec-2", "", "m", "en", assembly_id="asm-1")
    dead.pcm_stream = _FakeStream()
    dead.failed_at = time.monotonic() - (lc.FAILURE_COOLDOWN + 5)
    dead.pump_task = asyncio.get_running_loop().create_task(
        LiveCaptionManager()._pump_pcm(dead, dead.pcm_stream)
    )
    manager._sessions["rec-2"] = dead

    created = []

    class _Recording(_BaseSession):
        wants_pcm = False

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)

        async def run(self):
            await self.queue.get()

    monkeypatch.setitem(lc.SESSION_TYPES, "deepgram", _Recording)

    await manager._feed_async(
        "rec-2", b"audio", {"provider": "deepgram", "api_key": "k"}, "en", "asm-1"
    )

    assert dead.pcm_stream.closed, "the failed session's decoder was never closed"
    assert dead.pump_task.cancelled() or dead.pump_task.done(), "its pump task leaked"
    assert len(created) == 1

    await manager.shutdown()


def test_a_decoder_that_cannot_start_does_not_leak_a_session(settings_env, monkeypatch):
    asyncio.run(_test_a_decoder_that_cannot_start_does_not_leak_a_session(settings_env, monkeypatch))


async def _test_a_decoder_that_cannot_start_does_not_leak_a_session(settings_env, monkeypatch):
    """failed_at was set on an object that was never stored, so the cooldown
    could not see it — and every following chunk built another session, task
    and websocket, without limit."""
    manager = LiveCaptionManager()
    manager.set_loop(asyncio.get_running_loop())

    created = []

    class _PcmRecording(_BaseSession):
        wants_pcm = True

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)

        async def run(self):
            await self.queue.get()

    monkeypatch.setitem(lc.SESSION_TYPES, "vosk", _PcmRecording)
    monkeypatch.setattr(lc.live_audio, "PcmStream", lambda _rid: _FakeStream(starts=False))

    config = {"provider": "vosk", "endpoint": "ws://vosk:2700"}
    for _ in range(4):
        await manager._feed_async("rec-3", b"audio", config, "en", "asm-1")

    assert len(created) == 1, (
        f"{len(created)} sessions were built for one recording — the failure "
        "cooldown is being bypassed, so every chunk leaks a connection"
    )
    assert created[0].task is None, "a task was started for a session that never got a decoder"


def test_shutdown_disposes_every_session(settings_env):
    asyncio.run(_test_shutdown_disposes_every_session(settings_env))


async def _test_shutdown_disposes_every_session(settings_env):
    manager = LiveCaptionManager()
    streams = []
    for index in range(3):
        session = _BaseSession(f"rec-{index}", "", "m", "en", assembly_id="asm-1")
        session.pcm_stream = _FakeStream()
        streams.append(session.pcm_stream)
        manager._sessions[session.recording_id] = session

    await manager.shutdown()

    assert manager._sessions == {}
    assert all(stream.closed for stream in streams)


def test_abandoning_an_upload_ends_the_caption_session(client, monkeypatch):
    """The organizer gives up on a table whose phone died. Nothing else will
    ever end that caption session — /complete is never coming."""
    import re

    finished: list[str] = []
    monkeypatch.setattr(
        "citizens.api.recorders.LIVE_CAPTIONS.finish", lambda rid: finished.append(rid)
    )

    assembly = client.post(
        "/api/v1/assemblies",
        json={
            "name": "TEST Abandon Captions",
            "default_table_count": 1,
            "rounds": [{"title": "R1", "question": "Q?", "duration_minutes": 30}],
        },
    ).json()
    client.post(f"/api/v1/rounds/{assembly['rounds'][0]['id']}/start")
    invites = client.post(f"/api/v1/assemblies/{assembly['id']}/invites/generate").json()
    token = re.search(r"#/join/(.+)$", invites[0]["url"]).group(1)
    joined = client.post(
        "/api/v1/public/join", json={"token": token}, headers={"X-Origin-IP": "203.0.113.7"}
    ).json()
    headers = {"Authorization": f"Bearer {joined['session_token']}"}
    recording_id = client.post(
        "/api/v1/public/recorder/start",
        json={"round_id": assembly["rounds"][0]["id"], "mime_type": "audio/webm"},
        headers=headers,
    ).json()["recording_id"]

    response = client.post(f"/api/v1/recordings/{recording_id}/abandon-upload")
    assert response.status_code == 200, response.text
    assert finished == [recording_id], (
        "abandoning the upload left the caption session running: it holds a "
        "provider connection open and never writes down what it heard"
    )


def test_sweeping_a_stalled_upload_ends_its_caption_session(client, monkeypatch):
    """Same for the automatic path, which is what fires when nobody notices."""
    from datetime import timedelta

    from sqlalchemy import select

    from citizens.db.models import Recording
    from citizens.db.models.base import utcnow
    from citizens.db.session import session_scope
    from citizens.jobs import sweep

    finished: list[str] = []
    monkeypatch.setattr(sweep.LIVE_CAPTIONS, "finish", lambda rid: finished.append(rid))

    assembly = client.post(
        "/api/v1/assemblies",
        json={
            "name": "TEST Sweep Captions",
            "default_table_count": 1,
            "rounds": [{"title": "R1", "question": "Q?", "duration_minutes": 30}],
        },
    ).json()
    round_id = assembly["rounds"][0]["id"]
    client.post(f"/api/v1/rounds/{round_id}/start")

    with session_scope() as session:
        from citizens.db.models.assembly import Table

        table = session.execute(
            select(Table).where(Table.round_id == round_id, Table.number == 1)
        ).scalar_one()
        recording = Recording(
            assembly_id=assembly["id"],
            round_id=round_id,
            table_id=table.id,
            table_number=1,
            state="RECORDING",
            mime_type="audio/webm",
        )
        session.add(recording)
        session.flush()
        recording_id = recording.id
        # older than STALLED_UPLOAD_MINUTES: the phone is gone
        recording.updated_at = utcnow() - timedelta(minutes=sweep.STALLED_UPLOAD_MINUTES + 5)

    assert sweep.sweep_stalled_uploads() == 1
    assert finished == [recording_id], "the swept recording's caption session was left running"


# ---------------------------------------------------------------- capacity


def test_the_capacity_gate_holds_and_frees(settings_env, monkeypatch):
    asyncio.run(_test_the_capacity_gate_holds_and_frees(settings_env, monkeypatch))


async def _test_the_capacity_gate_holds_and_frees(settings_env, monkeypatch):
    """With the provider capped at one, a second phone's captions wait —
    honestly labelled — and take the slot the moment the first phone is done."""
    from citizens.services import stt_capacity

    stt_capacity.reset_for_tests()
    manager = LiveCaptionManager()
    manager.set_loop(asyncio.get_running_loop())

    created = []

    class _Recording(_BaseSession):
        wants_pcm = False

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)

        async def run(self):
            await self.queue.get()

    monkeypatch.setitem(lc.SESSION_TYPES, "deepgram", _Recording)
    config = {"provider": "deepgram", "api_key": "k", "concurrency": 1}

    await manager._feed_async("rec-a", b"audio", config, "en", "asm-1")
    await manager._feed_async("rec-b", b"audio", config, "en", "asm-1")

    assert len(created) == 1, "the cap did not hold"
    assert "rec-b" not in manager._sessions
    assert manager.status("rec-b") == {"active": False, "lines": [], "reason": "capacity"}
    assert stt_capacity.in_use("deepgram:live") == 1

    # the first phone finishes: its lease comes back, and the next chunk from
    # the waiting phone gets a session — no restart, no organizer action
    await manager._finish_async("rec-a")
    assert stt_capacity.in_use("deepgram:live") == 0

    await manager._feed_async("rec-b", b"audio", config, "en", "asm-1")
    assert len(created) == 2
    assert "rec-b" in manager._sessions
    assert "reason" not in manager.status("rec-b")

    await manager.shutdown()
    stt_capacity.reset_for_tests()


def test_a_config_without_a_cap_means_no_cap(settings_env, monkeypatch):
    asyncio.run(_test_a_config_without_a_cap_means_no_cap(settings_env, monkeypatch))


async def _test_a_config_without_a_cap_means_no_cap(settings_env, monkeypatch):
    """A snapshot cached across an upgrade has no concurrency key; absence
    must mean "unlimited", never "captions off for everyone"."""
    from citizens.services import stt_capacity

    stt_capacity.reset_for_tests()
    manager = LiveCaptionManager()
    manager.set_loop(asyncio.get_running_loop())

    created = []

    class _Recording(_BaseSession):
        wants_pcm = False

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)

        async def run(self):
            await self.queue.get()

    monkeypatch.setitem(lc.SESSION_TYPES, "deepgram", _Recording)
    config = {"provider": "deepgram", "api_key": "k"}  # no "concurrency"

    for rec in ("rec-1", "rec-2", "rec-3"):
        await manager._feed_async(rec, b"audio", config, "en", "asm-1")

    assert len(created) == 3
    assert stt_capacity.in_use("deepgram:live") == 0, "an uncapped session took a lease"

    await manager.shutdown()
    stt_capacity.reset_for_tests()


def test_a_failed_sessions_replacement_does_not_leak_the_lease(settings_env, monkeypatch):
    asyncio.run(_test_a_failed_sessions_replacement_does_not_leak_the_lease(settings_env, monkeypatch))


async def _test_a_failed_sessions_replacement_does_not_leak_the_lease(settings_env, monkeypatch):
    """The failed session is disposed (lease back) before its replacement
    acquires — so a cap of one survives the failure/replace cycle instead of
    deadlocking the recording out of its own slot."""
    from citizens.services import stt_capacity

    stt_capacity.reset_for_tests()
    manager = LiveCaptionManager()
    manager.set_loop(asyncio.get_running_loop())

    created = []

    class _Recording(_BaseSession):
        wants_pcm = False

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            created.append(self)

        async def run(self):
            await self.queue.get()

    monkeypatch.setitem(lc.SESSION_TYPES, "deepgram", _Recording)
    config = {"provider": "deepgram", "api_key": "k", "concurrency": 1}

    await manager._feed_async("rec-x", b"audio", config, "en", "asm-1")
    assert stt_capacity.in_use("deepgram:live") == 1
    # the session fails; its cooldown expires
    manager._sessions["rec-x"].failed_at = time.monotonic() - (lc.FAILURE_COOLDOWN + 5)

    await manager._feed_async("rec-x", b"audio", config, "en", "asm-1")

    assert len(created) == 2, "the replacement was denied its own freed slot"
    assert stt_capacity.in_use("deepgram:live") == 1, "the failed session's lease leaked"

    await manager.shutdown()
    assert stt_capacity.in_use("deepgram:live") == 0
    stt_capacity.reset_for_tests()


def test_status_names_the_cooldown_after_a_failure(settings_env):
    manager = LiveCaptionManager()
    session = _BaseSession("rec-err", "", "m", "en", assembly_id="asm-1")
    session.active = False
    session.failed_at = time.monotonic()
    manager._sessions["rec-err"] = session

    status = manager.status("rec-err")

    assert status["active"] is False
    assert status["reason"] == "error"
