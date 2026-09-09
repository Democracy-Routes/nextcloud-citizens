# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Provisional live captions (brief §34, §51).

The phone's ~10 s chunks — already uploaded for safety — are forwarded into a
server-side Deepgram streaming session per recording, so live captions cost
the phone zero extra bandwidth or battery. Captions are PROVISIONAL; the
canonical transcript always comes from batch transcription of the complete
audio. Any failure here is low-severity by design: recording is never
affected, and a dead session backs off instead of reconnect-looping.

Every configured engine can produce them, through the protocol it actually
speaks: Deepgram (or any Deepgram-protocol server such as WhisperLiveKit)
takes the WebM stream directly, while Vosk, Mistral Voxtral Realtime and
Whisper endpoints are fed decoded PCM by citizens.services.live_audio.

Captions are provisional whenever a final transcription will follow. When an
administrator has turned final transcription OFF, they are the only record the
assembly will ever have, so a session keeps every line it produced (not just
the tail it displays) and writes them out when it ends, for
jobs.handlers.handle_transcribe_from_live to turn into a real transcript.
"""

import asyncio
import base64
import contextlib
import json
import time
import urllib.parse

from citizens.config import get_settings
from citizens.logging_setup import get_logger
from citizens.services import live_audio, stt_capacity
from citizens.storage.paths import live_caption_path

log = get_logger(__name__)

DEEPGRAM_URL = "wss://api.deepgram.com/v1/listen"
MISTRAL_URL = "wss://api.mistral.ai/v1/audio/transcriptions/realtime"
# Chunks arrive about every ten seconds while a table is recording, and
# last_fed is bumped by their arrival rather than by engine output, so a slow
# engine is never reaped. Ninety seconds of total silence therefore means the
# phone is gone. It also has to leave room inside the 300 s grace that
# handle_transcribe_from_live allows for captions to land.
SESSION_IDLE_TIMEOUT = 90.0
#: how often the reaper looks for sessions nobody is feeding any more
REAP_INTERVAL_SECONDS = 15.0
#: how long a session gets to finish writing its transcript before it is cancelled
DISPOSE_TIMEOUT_SECONDS = 20.0
FAILURE_COOLDOWN = 60.0
KEEPALIVE_SECONDS = 5.0
# how many lines the phone and the monitor are shown — a display window, not
# the record. self.lines keeps everything; status() returns this many.
MAX_LINES = 80
# Refusal point for a runaway session, about sixteen hours of speech. Dropping
# the oldest lines instead would quietly rewrite the beginning of a transcript
# somebody may rely on, so this stops appending and says so.
MAX_TRANSCRIPT_LINES = 20000
# byte-exact: vosk-server compares the terminator with a literal string
VOSK_EOF = '{"eof" : 1}'


class _BaseSession:
    """Shared caption-session state. Subclasses implement run() for one engine
    and append {"t", "end", "text", "speaker"} entries to self.lines.

    self.lines is the WHOLE session, because with final transcription switched
    off it becomes the assembly's transcript. It used to be a deque capped at
    MAX_LINES, which silently discarded everything before the last eighty lines
    — fine for a caption strip, useless as a record. status() does the capping
    now, so the phone still receives a display window.
    """

    #: True when the engine consumes decoded PCM rather than the WebM stream
    wants_pcm = False

    def __init__(
        self,
        recording_id: str,
        api_key: str,
        model: str,
        language: str,
        endpoint: str = "",
        assembly_id: str = "",
    ):
        self.endpoint = endpoint
        self.recording_id = recording_id
        # only needed to file the persisted transcript under its assembly, so
        # deleting the assembly takes it too
        self.assembly_id = assembly_id
        self.api_key = api_key
        self.model = model
        self.language = language
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=64)
        self.lines: list[dict] = []
        self.truncated = False
        # set true only on the TERMINAL dispose (from finish(), i.e. /complete
        # or a device-replace/silent release) so the persisted file can say the
        # captions are complete — the job must not adopt a partial one
        self.final = False
        self.active = True
        self.failed_at: float | None = None
        # the capacity lease this session holds (provider name), released
        # exactly once by _dispose — see services/stt_capacity.py
        self.lease_provider: str | None = None
        self.last_fed = time.monotonic()
        self.task: asyncio.Task | None = None
        # engines fed with PCM own a decoder for this recording, and the task
        # forwarding its output. Both are held so teardown can reach them: an
        # untracked pump task parks forever on a queue nobody drains and its
        # cleanup — which is what kills ffmpeg — never runs.
        self.pcm_stream = None
        self.pump_task: asyncio.Task | None = None

    def add_line(
        self,
        text: str,
        start: float = 0.0,
        end: float | None = None,
        speaker=None,
        words: list[dict] | None = None,
    ) -> None:
        text = (text or "").strip()
        if not text:
            return
        self._drop_provisional()
        if len(self.lines) >= MAX_TRANSCRIPT_LINES:
            if not self.truncated:
                self.truncated = True
                log.warning(
                    "live_transcript_truncated",
                    recording_id=self.recording_id,
                    lines=len(self.lines),
                )
            return
        line = {"t": start, "text": text, "speaker": speaker}
        if end is not None:
            line["end"] = end
        if words:
            line["words"] = words
        self.lines.append(line)

    def set_provisional(self, text: str, start: float = 0.0) -> None:
        """Show in-progress speech. Engines endpoint on pauses, so without this
        a table talking continuously would see nothing until they stop."""
        text = (text or "").strip()
        self._drop_provisional()
        if text:
            self.lines.append(
                {"t": start, "text": text, "speaker": None, "provisional": True}
            )
            self._has_provisional = True

    def _drop_provisional(self) -> None:
        if getattr(self, "_has_provisional", False) and self.lines:
            self.lines.pop()
        self._has_provisional = False

    async def run(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError


class DeepgramSession(_BaseSession):
    """Deepgram's streaming API, and any server speaking the same protocol
    (WhisperLiveKit's /v1/listen), which takes the WebM stream as-is."""

    async def run(self) -> None:
        try:
            from websockets.asyncio.client import connect
        except ImportError:  # older websockets
            from websockets import connect  # type: ignore[no-redef]

        params = {
            "model": self.model or "nova-3",
            "punctuate": "true",
            "smart_format": "true",
            "interim_results": "false",
            "diarize": "true",
        }
        if self.language:
            params["language"] = self.language
        base = self.endpoint or DEEPGRAM_URL
        headers = {}
        if self.api_key:
            if "api.deepgram.com" in base:
                headers["Authorization"] = f"Token {self.api_key}"
            else:
                # Deepgram-protocol servers (WhisperLiveKit) take a query token
                params["token"] = self.api_key
        url = base + ("&" if "?" in base else "?") + urllib.parse.urlencode(params)
        try:
            async with connect(url, additional_headers=headers) as ws:
                log.info("live_stt_session_started", recording_id=self.recording_id)
                sender = asyncio.create_task(self._send_loop(ws))
                keeper = asyncio.create_task(self._keepalive_loop(ws))
                try:
                    async for message in ws:
                        self._handle_message(message)
                finally:
                    sender.cancel()
                    keeper.cancel()
        except Exception as exc:
            self.failed_at = time.monotonic()
            log.warning(
                "live_stt_session_failed",
                recording_id=self.recording_id,
                error=type(exc).__name__,
            )
        finally:
            self.active = False
            log.info("live_stt_session_closed", recording_id=self.recording_id,
                     lines=len(self.lines))

    async def _send_loop(self, ws) -> None:
        while True:
            item = await self.queue.get()
            if item is None:
                await ws.send(json.dumps({"type": "CloseStream"}))
                return
            await ws.send(item)

    async def _keepalive_loop(self, ws) -> None:
        # Deepgram drops streams that go silent; our chunks arrive ~10 s apart
        while True:
            await asyncio.sleep(KEEPALIVE_SECONDS)
            await ws.send(json.dumps({"type": "KeepAlive"}))

    def _handle_message(self, message) -> None:
        try:
            data = json.loads(message)
        except (TypeError, ValueError):
            return
        if data.get("type") != "Results" or not data.get("is_final"):
            return
        alternatives = (data.get("channel") or {}).get("alternatives") or []
        text = (alternatives[0].get("transcript") if alternatives else "").strip()
        if text:
            words = alternatives[0].get("words") or []
            speaker = words[0].get("speaker") if words else None
            start = float(data.get("start") or 0.0)
            duration = float(data.get("duration") or 0.0)
            self.add_line(
                text, start=start, end=start + duration if duration else None, speaker=speaker
            )



class VoskSession(_BaseSession):
    """vosk-server's WebSocket protocol. It answers once per audio frame, so
    PCM is re-framed to ~250 ms — one 10 s frame would yield a single result
    and behave exactly like batch transcription."""

    wants_pcm = True
    # The batch provider feeds 0.2 s frames (vosk.py FRAME_BYTES). Matching it
    # closes the systematic gap between what a facilitator reads during the
    # round and the transcript that reaches the report: on 800 s of real
    # assembly audio, agreement went from 92.3% to 98.9%.
    # Not 100%, and it cannot be: vosk-server is not repeatable. The same
    # frames sent twice agreed only 99.3% with each other, so 98.9% is the
    # server's own noise floor rather than a defect left in this code.
    FRAME_SECONDS = 0.2

    async def run(self) -> None:
        try:
            from websockets.asyncio.client import connect
        except ImportError:  # older websockets
            from websockets import connect  # type: ignore[no-redef]

        url = self.endpoint or "ws://localhost:2700"
        try:
            async with connect(url, ping_interval=20, ping_timeout=60) as ws:
                config = {"sample_rate": live_audio.SAMPLE_RATE, "words": True}
                if self.model:
                    # the model for this table's language. On a stock
                    # vosk-server this would swap the model for every connected
                    # client, so scripts/vosk-up.sh runs a patched asr_server.py
                    # that keeps the choice per-connection.
                    config["model"] = self.model
                await ws.send(json.dumps({"config": config}))
                log.info("live_stt_session_started", recording_id=self.recording_id, provider="vosk")
                framer = live_audio.Framer(self.FRAME_SECONDS)
                while True:
                    item = await self.queue.get()
                    if item is None:
                        # the tail is part of the recording too — send it
                        # before the terminator, not after
                        for frame in framer.flush():
                            await ws.send(frame)
                            self._handle_message(await ws.recv())
                        await ws.send(VOSK_EOF)
                        try:
                            self._handle_message(await asyncio.wait_for(ws.recv(), timeout=15))
                        except (TimeoutError, asyncio.CancelledError):
                            pass
                        return
                    for frame in framer.push(item):
                        await ws.send(frame)
                        self._handle_message(await ws.recv())
        except Exception as exc:
            self.failed_at = time.monotonic()
            log.warning(
                "live_stt_session_failed",
                recording_id=self.recording_id,
                provider="vosk",
                error=type(exc).__name__,
            )
        finally:
            self.active = False
            log.info("live_stt_session_closed", recording_id=self.recording_id,
                     lines=len(self.lines))

    def _handle_message(self, message) -> None:
        try:
            data = json.loads(message)
        except (TypeError, ValueError):
            return
        if "partial" in data:
            self.set_provisional(data["partial"])
            return
        words = data.get("result") or []
        self.add_line(
            data.get("text", ""),
            start=float(words[0]["start"]) if words else 0.0,
            end=float(words[-1]["end"]) if words else None,
            # Vosk gives per-word timings and the batch path stores them; keep
            # them so a live transcript is as navigable as a final one
            words=[
                {"text": w.get("word") or "", "start": float(w.get("start", 0.0)),
                 "end": float(w.get("end", 0.0))}
                for w in words
            ],
        )


class MistralSession(_BaseSession):
    """Mistral Voxtral Realtime. The server speaks first (session.created),
    audio is base64 PCM inside JSON capped at 256 KiB per append, and partial
    text arrives as transcription.text.delta. No diarization in realtime."""

    wants_pcm = True
    # Mistral's own streaming example uses chunk_duration_ms=480. This was
    # 4.0 with a note about a 256 KiB cap, which is not in the current
    # documentation and could not be verified; it never took effect either,
    # because framing was applied per 8 KB block and one block is nowhere near
    # four seconds, so every block became its own base64 message.
    APPEND_SECONDS = 0.48

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pending = ""

    async def run(self) -> None:
        try:
            from websockets.asyncio.client import connect
        except ImportError:  # older websockets
            from websockets import connect  # type: ignore[no-redef]

        model = self.model or "voxtral-mini-transcribe-realtime-2602"
        url = f"{self.endpoint or MISTRAL_URL}?model={urllib.parse.quote(model)}"
        try:
            async with connect(
                url,
                additional_headers={"Authorization": f"Bearer {self.api_key}"},
                ping_interval=20,
                ping_timeout=60,
            ) as ws:
                # the handshake is server-first: wait for session.created
                await asyncio.wait_for(ws.recv(), timeout=30)
                await ws.send(
                    json.dumps(
                        {
                            "type": "session.update",
                            "session": {
                                "audio_format": {
                                    "encoding": "pcm_s16le",
                                    "sample_rate": live_audio.SAMPLE_RATE,
                                },
                                "target_streaming_delay_ms": 1000,
                            },
                        }
                    )
                )
                log.info("live_stt_session_started", recording_id=self.recording_id,
                         provider="mistral")
                receiver = asyncio.create_task(self._receive_loop(ws))
                framer = live_audio.Framer(self.APPEND_SECONDS)

                async def append(frame: bytes) -> None:
                    await ws.send(
                        json.dumps(
                            {
                                "type": "input_audio.append",
                                "audio": base64.b64encode(frame).decode(),
                            }
                        )
                    )

                try:
                    while True:
                        item = await self.queue.get()
                        if item is None:
                            for frame in framer.flush():
                                await append(frame)
                            await ws.send(json.dumps({"type": "input_audio.flush"}))
                            await ws.send(json.dumps({"type": "input_audio.end"}))
                            await asyncio.sleep(2)
                            return
                        for frame in framer.push(item):
                            await append(frame)
                finally:
                    receiver.cancel()
        except Exception as exc:
            self.failed_at = time.monotonic()
            log.warning(
                "live_stt_session_failed",
                recording_id=self.recording_id,
                provider="mistral",
                error=type(exc).__name__,
            )
        finally:
            self.active = False
            log.info("live_stt_session_closed", recording_id=self.recording_id,
                     lines=len(self.lines))

    async def _receive_loop(self, ws) -> None:
        async for message in ws:
            self._handle_message(message)

    def _handle_message(self, message) -> None:
        try:
            data = json.loads(message)
        except (TypeError, ValueError):
            return
        kind = data.get("type")
        if kind == "transcription.text.delta":
            self._pending += data.get("text") or ""
            self.set_provisional(self._pending)
        elif kind == "transcription.segment":
            # a segment supersedes the deltas accumulated for it
            self.add_line(
                data.get("text") or self._pending,
                start=float(data.get("start") or 0.0),
                end=float(data["end"]) if data.get("end") is not None else None,
                speaker=data.get("speaker_id"),
            )
            self._pending = ""
        elif kind == "transcription.done":
            self.add_line(self._pending)
            self._pending = ""


class WhisperSession(_BaseSession):
    """Whisper endpoints have no single streaming protocol, so captions are
    produced from the ordinary transcription endpoint over a sliding window:
    each chunk transcribes the last WINDOW_SECONDS of audio and only the text
    past the previous window is committed. Cutting at fixed chunk boundaries
    would slice words in half, which is what makes naive per-chunk Whisper
    produce nonsense."""

    wants_pcm = True
    WINDOW_SECONDS = 20.0
    STEP_SECONDS = 10.0
    # Whisper invents fluent text over near-silence; drop those segments
    MAX_NO_SPEECH_PROB = 0.6

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._buffer = bytearray()
        self._consumed_seconds = 0.0
        # audio already dropped off the front of the rolling buffer, and how
        # much new audio has arrived since the last window was transcribed
        self._dropped_seconds = 0.0
        self._pending_bytes = 0
        self._last_start: float | None = None

    async def run(self) -> None:
        log.info("live_stt_session_started", recording_id=self.recording_id, provider="whisper")
        try:
            while True:
                item = await self.queue.get()
                if item is None:
                    await self._transcribe_window(final=True)
                    return
                self._buffer.extend(item)
                self._pending_bytes += len(item)
                # transcribe once per STEP of NEW audio, not on every block:
                # keying off total length would fire on every 0.25 s once the
                # buffer passed the threshold
                if self._pending_bytes >= live_audio.BYTES_PER_SECOND * self.STEP_SECONDS:
                    await self._transcribe_window()
        except Exception as exc:
            self.failed_at = time.monotonic()
            log.warning(
                "live_stt_session_failed",
                recording_id=self.recording_id,
                provider="whisper",
                error=type(exc).__name__,
            )
        finally:
            self.active = False
            log.info("live_stt_session_closed", recording_id=self.recording_id,
                     lines=len(self.lines))

    async def _transcribe_window(self, final: bool = False) -> None:
        self._pending_bytes = 0
        window_bytes = int(live_audio.BYTES_PER_SECOND * self.WINDOW_SECONDS)
        window = bytes(self._buffer[-window_bytes:])
        if len(window) < live_audio.BYTES_PER_SECOND:  # under a second of audio
            return
        window_start = self._dropped_seconds + (
            (len(self._buffer) - len(window)) / live_audio.BYTES_PER_SECOND
        )
        # keep only what the next window can use, so a long round never grows
        # this buffer without bound
        if len(self._buffer) > window_bytes:
            self._dropped_seconds += (len(self._buffer) - window_bytes) / live_audio.BYTES_PER_SECOND
            del self._buffer[:-window_bytes]
        try:
            raw = await asyncio.to_thread(
                _whisper_window_request,
                self.endpoint,
                self.api_key,
                self.model,
                self.language,
                live_audio.wav_bytes(window),
            )
        except Exception:
            log.warning("live_stt_window_failed", recording_id=self.recording_id, exc_info=True)
            return

        committed = self._consumed_seconds
        for segment in raw.get("segments") or []:
            start = window_start + float(segment.get("start", 0.0))
            end = window_start + float(segment.get("end", 0.0))
            if end <= committed:  # already shown from an earlier window
                continue
            if float(segment.get("no_speech_prob", 0.0)) > self.MAX_NO_SPEECH_PROB:
                continue
            # a later window re-transcribes the tail with more context, so the
            # same sentence comes back improved — revise it instead of
            # printing it twice
            if (
                self._last_start is not None
                and abs(start - self._last_start) < 1.0
                and self.lines
            ):
                self._drop_provisional()
                if self.lines:
                    self.lines.pop()
            self.add_line(segment.get("text", ""), start=start, end=end)
            self._last_start = start
            committed = max(committed, end)
        if not (raw.get("segments") or []) and raw.get("text") and final:
            self.add_line(raw["text"], start=window_start)
        self._consumed_seconds = committed


def _whisper_window_request(
    base_url: str, api_key: str, model: str, language: str, wav: bytes
) -> dict:
    """Blocking call, run in a worker thread: the batch adapter's endpoint with
    a WAV window instead of the whole recording."""
    import httpx

    from citizens.providers.transcription import whisper as whisper_provider

    data = {"model": model or whisper_provider.DEFAULT_MODEL, "response_format": "verbose_json"}
    if language:
        data["language"] = language
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    endpoint = (base_url or whisper_provider.BASE_URL).rstrip("/") + "/audio/transcriptions"
    response = httpx.post(
        endpoint,
        headers=headers,
        data=data,
        files={"file": ("window.wav", wav, "audio/wav")},
        timeout=httpx.Timeout(120, connect=15),
    )
    response.raise_for_status()
    return response.json()


SESSION_TYPES = {
    "deepgram": DeepgramSession,
    "vosk": VoskSession,
    "mistral": MistralSession,
    "whisper": WhisperSession,
}
# so a persisted transcript records which engine produced it
PROVIDER_NAMES = {session: name for name, session in SESSION_TYPES.items()}


class LiveCaptionManager:
    def __init__(self):
        self._sessions: dict[str, _BaseSession] = {}
        # One ffmpeg decoder per recording, kept ALIVE across session
        # reconnects. When a provider drops the websocket (Mistral does, at
        # ~17 min), only the session is rebuilt; the decoder keeps the WebM
        # container state, so the replacement is never fed an orphaned
        # mid-stream chunk it cannot decode. Keyed by recording_id.
        self._streams: dict[str, live_audio.PcmStream] = {}
        # recordings denied a session because the provider is at its
        # concurrency cap: recording_id -> when. Only for honest status() —
        # the phone keeps recording and re-asks with every chunk.
        self._over_capacity: dict[str, float] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    async def _close_stream(self, recording_id: str) -> None:
        stream = self._streams.pop(recording_id, None)
        if stream is not None:
            await stream.close()

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    @staticmethod
    def _resolve_vosk_model(config: dict, language: str) -> str:
        """Live-caption model path for this language, matching
        provider_config.vosk_model_for(kind="live") but reading the cached
        snapshot rather than the config store — no OCS call on the upload path."""
        from citizens.services.provider_config import vosk_model_path

        models = config.get("vosk_models") or {}
        code = (language or "").strip().lower()
        entry = models.get(code) or models.get(code.split("-")[0]) or {}
        if isinstance(entry, str):  # legacy snapshot shape
            return vosk_model_path(entry)
        return vosk_model_path(entry.get("live", ""))

    def feed(
        self, recording_id: str, data: bytes, config: dict, language: str, assembly_id: str = ""
    ) -> None:
        """Called from the (threadpool) chunk-upload path. Never raises."""
        try:
            if self._loop is None or not config.get("enabled"):
                return
            provider = config.get("provider")
            if provider not in SESSION_TYPES:
                return
            # hosted engines need a key; self-hosted ones need an endpoint
            if provider in ("deepgram", "mistral") and not config.get("api_key"):
                return
            if provider in ("vosk", "whisper") and not config.get("endpoint"):
                return
            asyncio.run_coroutine_threadsafe(
                self._feed_async(recording_id, data, config, language, assembly_id), self._loop
            )
        except Exception:
            log.warning("live_stt_feed_failed", recording_id=recording_id, exc_info=True)

    def finish(self, recording_id: str) -> None:
        try:
            if self._loop is not None:
                asyncio.run_coroutine_threadsafe(self._finish_async(recording_id), self._loop)
        except Exception:
            pass

    def status(self, recording_id: str) -> dict:
        session = self._sessions.get(recording_id)
        if session is None:
            if recording_id in self._over_capacity:
                # captions are intentionally off on this phone — the provider
                # is at its concurrency cap. The phone shows an honest message
                # instead of the alarming "unavailable" one.
                return {"active": False, "lines": [], "reason": "capacity"}
            return {"active": False, "lines": []}
        # a display window, not the record: self.lines is the whole session and
        # can run to thousands of entries, which must never reach a phone that
        # polls this every couple of seconds
        result = {"active": session.active, "lines": session.lines[-MAX_LINES:]}
        if session.failed_at is not None:
            result["reason"] = "error"  # failed, in cooldown before a retry
        return result

    async def _feed_async(
        self, recording_id: str, data: bytes, config: dict, language: str, assembly_id: str = ""
    ) -> None:
        provider = config["provider"]
        wants_pcm = SESSION_TYPES[provider].wants_pcm
        session = self._sessions.get(recording_id)

        if session is not None and session.failed_at is not None:
            if time.monotonic() - session.failed_at < FAILURE_COOLDOWN:
                # Cooling down; don't reconnect-loop (brief §51). But KEEP the
                # decoder fed: it survives the reconnect, and starving it for
                # the 60 s cooldown would punch exactly the mid-stream hole this
                # whole design exists to avoid. last_fed is bumped so the phone
                # that is plainly still recording is not reaped as idle.
                session.last_fed = time.monotonic()
                stream = self._streams.get(recording_id)
                if stream is not None:
                    stream.feed(data)
                return
            # Cooldown over: tear down the dead session but LEAVE its decoder
            # running, so the replacement inherits an ffmpeg that still holds
            # the WebM container state.
            self._sessions.pop(recording_id, None)
            await self._dispose(session, keep_stream=True)
            session = None

        if session is None:
            # The capacity gate. Each session is one connection to the
            # provider; past the per-provider cap a new phone's captions wait
            # rather than pile onto a struggling backend and take everyone's
            # captions down with it. Recording is untouched, and every chunk
            # re-asks — a freed slot is picked up within one upload interval. A
            # config with no concurrency key means no cap (a hand-built config,
            # or a snapshot cached across an upgrade) — absence must never turn
            # captions off.
            lease: str | None = None
            limit = config.get("concurrency")
            if limit is not None:
                # live and batch are independent pools per provider
                if not stt_capacity.try_acquire(f"{provider}:live", int(limit)):
                    self._over_capacity[recording_id] = time.monotonic()
                    # no session means no consumer — don't keep a decoder
                    # running for captions that are switched off here
                    await self._close_stream(recording_id)
                    return
                lease = f"{provider}:live"
            self._over_capacity.pop(recording_id, None)
            session_type = SESSION_TYPES[provider]
            model = config.get("model", "")
            if provider == "vosk":
                # Vosk needs a model per language and one server can hold
                # several, so this table's language picks it. Resolved from the
                # cached snapshot — never an OCS call on the upload path.
                model = self._resolve_vosk_model(config, language) or model
            session = session_type(
                recording_id,
                config.get("api_key") or "",
                model,
                language,
                endpoint=config.get("endpoint", ""),
                assembly_id=assembly_id,
            )
            session.lease_provider = lease
            # Registered BEFORE anything can fail or await. Starting the task
            # first and storing the session last meant that a PcmStream which
            # refused to start returned with the task already running (holding
            # an open websocket) and failed_at set on an object nobody held —
            # so the cooldown above could never see it, and every subsequent
            # ten-second chunk leaked another session, task and connection.
            self._sessions[recording_id] = session
            if wants_pcm:
                stream = self._streams.get(recording_id)
                if stream is None:
                    # first session for this recording: build the decoder
                    stream = live_audio.PcmStream(recording_id)
                    if not await stream.start():
                        session.failed_at = time.monotonic()
                        session.active = False
                        log.warning("live_stt_pcm_stream_failed", recording_id=recording_id)
                        return
                    self._streams[recording_id] = stream
                else:
                    # reusing the decoder that outlived a failed session: throw
                    # away the PCM it buffered during the reconnect gap, so the
                    # replacement opens on live audio, not a minute-old backlog
                    stream.drain()
                session.pcm_stream = stream
            loop = asyncio.get_running_loop()
            session.task = loop.create_task(self._run_and_persist(session))
            if session.pcm_stream is not None:
                session.pump_task = loop.create_task(
                    self._pump_pcm(session, session.pcm_stream)
                )
        session.last_fed = time.monotonic()
        if wants_pcm:
            stream = self._streams.get(recording_id)
            if stream is not None:
                stream.feed(data)
            return
        try:
            session.queue.put_nowait(data)
        except asyncio.QueueFull:
            log.warning("live_stt_queue_full", recording_id=recording_id)

    async def _pump_pcm(self, session: "_BaseSession", stream) -> None:
        """Forward decoded PCM into the session queue until the stream ends."""
        try:
            while True:
                pcm = await stream.read()
                if pcm is None:
                    break
                # backpressure, not drop: this runs in a background task, so
                # waiting for a slow engine costs nothing, whereas dropping
                # here silently loses words from the captions. PcmStream has
                # its own bounded buffer as the real safety valve.
                await session.queue.put(pcm)
        except Exception:
            log.warning("live_stt_pcm_pump_failed", recording_id=session.recording_id,
                        exc_info=True)
        finally:
            # The decoder ended. If the session is still active, that was
            # ffmpeg dying under us, not an orderly close (dispose sets active
            # False first) — mark it failed so the session is rebuilt and
            # status() honestly reports the cooldown instead of a silent stop.
            if session.active and session.failed_at is None:
                session.failed_at = time.monotonic()
            try:
                session.queue.put_nowait(None)
            except asyncio.QueueFull:
                pass

    async def _run_and_persist(self, session: "_BaseSession") -> None:
        """Run one caption session, then write down what it heard.

        Persisting always, rather than only when final transcription is off,
        keeps this side free of configuration: the job decides whether the file
        is the transcript of record or merely a diagnostic. A session only
        exists when live captions are enabled, so this never runs uninvited.
        """
        try:
            await session.run()
        finally:
            try:
                await self._persist_transcript(session)
            except Exception:
                log.warning(
                    "live_transcript_persist_failed",
                    recording_id=session.recording_id,
                    exc_info=True,
                )

    async def _persist_transcript(self, session: "_BaseSession") -> None:
        lines = [line for line in session.lines if not line.get("provisional")]
        payload = {
            "recording_id": session.recording_id,
            "provider": PROVIDER_NAMES.get(type(session), ""),
            "model": session.model,
            "language": session.language,
            "truncated": session.truncated,
            # whether THIS write is the recording's terminal one. A partial file
            # from a session that died mid-round is indistinguishable from a
            # complete one without this, so the job used to promote whichever it
            # happened to read first.
            "final": session.final,
            "lines": lines,
        }
        path = live_caption_path(
            get_settings().app_persistent_storage, session.assembly_id, session.recording_id
        )

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            # A session that dies mid-round is replaced after the cooldown, and
            # the replacement starts with an empty buffer. Overwriting would
            # then throw away everything said before the failure — the first
            # half of a transcript, silently. Its lines are strictly later in
            # the recording, so appending is the whole of the fix.
            if path.exists():
                try:
                    earlier = json.loads(path.read_text(encoding="utf-8")).get("lines") or []
                except (OSError, ValueError):
                    earlier = []
                if earlier:
                    payload["lines"] = earlier + payload["lines"]
                    payload["resumed"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")

        # This coroutine runs on the event loop, where a blocking write stalls
        # every other request in the app (the defect fixed in b974eb5).
        await asyncio.to_thread(write)
        log.info(
            "live_transcript_persisted", recording_id=session.recording_id, lines=len(lines)
        )

    async def _finish_async(self, recording_id: str) -> None:
        self._over_capacity.pop(recording_id, None)
        session = self._sessions.pop(recording_id, None)
        if session is not None:
            # the recording is done: this dispose is terminal, so its persisted
            # transcript is the complete one the job may adopt
            session.final = True
            await self._dispose(session)
        # close the decoder even when there was no live session (captions off,
        # or over-capacity for the whole recording) so no ffmpeg is left behind
        await self._close_stream(recording_id)

    async def _dispose(self, session: "_BaseSession | None", keep_stream: bool = False) -> None:
        """End one caption session and wait for it to finish writing.

        Ending the queue (or closing the decoder, which ends it in turn) lets
        run() return normally, so _run_and_persist reaches its finally and the
        transcript is written. Cancelling outright can abort that mid-await and
        lose the lines — which, with final transcription off, is the table's
        only record. Cancellation is therefore the last resort, not the method.

        keep_stream is set when a failed session is being REPLACED: the decoder
        must outlive it (that is the whole reconnect fix), so its pump is
        cancelled but ffmpeg is left running for the replacement to inherit.
        """
        if session is None:
            return
        session.active = False
        # Every terminal path funnels through here (finish, reap, failed
        # replacement, shutdown), so this is the one place the capacity lease
        # goes back. The flag is cleared first: dispose can in principle be
        # reached twice, and a double release would free a slot someone else
        # still holds.
        if session.lease_provider is not None:
            lease, session.lease_provider = session.lease_provider, None
            stt_capacity.release(lease)
        try:
            if session.pcm_stream is not None and not keep_stream:
                # terminal: closing ffmpeg's stdin flushes the tail and ends the
                # decoder, so _pump_pcm reads None and ends the queue on its way
                # out. Drop it from the registry (same instance) and close it.
                self._streams.pop(session.recording_id, None)
                await session.pcm_stream.close()
            elif session.pcm_stream is not None and keep_stream:
                # rebuild: leave ffmpeg decoding, but detach THIS session's pump
                # (it is parked on stream.read()); its finally ends the queue so
                # run() returns and persists the first half of the transcript
                if session.pump_task is not None and not session.pump_task.done():
                    session.pump_task.cancel()
            else:
                try:
                    session.queue.put_nowait(None)
                except asyncio.QueueFull:
                    # nothing is draining it, so the sentinel cannot get in —
                    # cancelling the pump frees the slot
                    if session.pump_task and not session.pump_task.done():
                        session.pump_task.cancel()
        except Exception:
            log.warning(
                "live_stt_dispose_failed", recording_id=session.recording_id, exc_info=True
            )
        for task in (session.task, session.pump_task):
            if task is None or task.done():
                continue
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=DISPOSE_TIMEOUT_SECONDS)
            except (TimeoutError, asyncio.CancelledError):
                # it will not end on its own; cancel and WAIT for that to land,
                # so callers can rely on the session really being finished
                task.cancel()
                with contextlib.suppress(Exception, asyncio.CancelledError):
                    await task
            except Exception:
                log.warning(
                    "live_stt_session_end_failed",
                    recording_id=session.recording_id,
                    exc_info=True,
                )

    async def reap_idle(self) -> None:
        """End sessions nobody is feeding any more.

        Reaping used to happen only as a side effect of some OTHER recording's
        chunk upload. So when a phone died in the last round of the day and the
        remaining tables finished within the idle timeout, nothing ever ran
        again: the session stayed active forever, its captions were never
        written to disk (with final transcription off, that was the table's
        only transcript), and a Deepgram websocket stayed open with keepalives
        being sent to it until the container restarted — a billable connection
        held for nothing.
        """
        now = time.monotonic()
        # over-capacity markers age out on the same clock: once the phone
        # stops uploading, its "captions waiting for a slot" state is over
        for recording_id, when in list(self._over_capacity.items()):
            if now - when > SESSION_IDLE_TIMEOUT:
                self._over_capacity.pop(recording_id, None)
        stale = [
            (recording_id, session)
            for recording_id, session in list(self._sessions.items())
            if now - session.last_fed > SESSION_IDLE_TIMEOUT
        ]
        for recording_id, session in stale:
            log.info(
                "live_stt_session_reaped",
                recording_id=recording_id,
                idle_seconds=round(now - session.last_fed, 1),
                lines=len(session.lines),
            )
            self._sessions.pop(recording_id, None)
            await self._dispose(session)
        # decoders can now outlive their session; reap any left with no session
        # and no recent audio (over-capacity, or a phone gone during cooldown)
        for recording_id, stream in list(self._streams.items()):
            if recording_id not in self._sessions and now - stream.last_fed > SESSION_IDLE_TIMEOUT:
                log.info("live_stt_stream_reaped", recording_id=recording_id)
                await self._close_stream(recording_id)

    async def reap_forever(self, stop_event: asyncio.Event) -> None:
        """Drive reap_idle on its own clock, not on other tables' traffic."""
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=REAP_INTERVAL_SECONDS
                )
                return  # asked to stop
            except TimeoutError:
                pass
            try:
                await self.reap_idle()
            except Exception:
                log.error("live_stt_reap_failed", exc_info=True)

    async def shutdown(self) -> None:
        for recording_id, session in list(self._sessions.items()):
            self._sessions.pop(recording_id, None)
            await self._dispose(session)
        self._sessions.clear()
        for recording_id in list(self._streams):
            await self._close_stream(recording_id)


LIVE_CAPTIONS = LiveCaptionManager()
