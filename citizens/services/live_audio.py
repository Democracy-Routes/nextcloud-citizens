# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Decode the phone's live chunk stream into PCM for caption engines.

The phone uploads fragments of ONE continuous WebM/Opus stream: only the first
chunk carries container headers, so a later chunk cannot be decoded on its own.
Deepgram accepts the container stream directly; Vosk, Mistral Voxtral Realtime
and Whisper endpoints all want raw PCM. One long-lived ffmpeg per recording
turns the former into the latter.

Everything here is best-effort by design (brief §51): if ffmpeg dies or the
audio is undecodable, captions stop and the recording is untouched.
"""

import asyncio
import time

from citizens.logging_setup import get_logger

log = get_logger(__name__)

SAMPLE_RATE = 16000
BYTES_PER_SECOND = SAMPLE_RATE * 2  # s16le mono
READ_SIZE = 8192
# a caption engine that stops draining must not grow memory without bound
MAX_QUEUED_PCM_BYTES = BYTES_PER_SECOND * 120
# dropping is the right safety valve, but it silently loses words from the
# captions, so say so — rate-limited, since it drops per 8 KB read
DROP_WARNING_SECONDS = 5.0


class PcmStream:
    """A persistent ffmpeg decoder for one recording's chunk stream."""

    def __init__(self, recording_id: str):
        self.recording_id = recording_id
        self.process: asyncio.subprocess.Process | None = None
        self.pcm: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.failed = False
        # last time a chunk was written in. The decoder now outlives the
        # caption session that consumes it (it survives a provider reconnect),
        # so the manager reaps an idle decoder on this rather than on a session.
        self.last_fed = time.monotonic()
        self._queued_bytes = 0
        self._dropped_bytes = 0
        self._last_drop_warning = 0.0
        self._reader: asyncio.Task | None = None
        self._stderr_reader: asyncio.Task | None = None

    async def start(self) -> bool:
        try:
            self.process = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-hide_banner", "-loglevel", "error",
                # without these ffmpeg buffers ~1 s before emitting anything
                "-fflags", "nobuffer", "-flags", "low_delay",
                "-i", "pipe:0",
                "-f", "s16le", "-acodec", "pcm_s16le",
                "-ac", "1", "-ar", str(SAMPLE_RATE),
                "pipe:1",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                # captured, not discarded: "Invalid data found when processing
                # input" from a decoder fed mid-stream used to vanish here, so
                # a dead ffmpeg was completely silent in the logs.
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError:
            log.warning("pcm_stream_start_failed", recording_id=self.recording_id, exc_info=True)
            self.failed = True
            return False
        self._reader = asyncio.create_task(self._read_loop())
        self._stderr_reader = asyncio.create_task(self._stderr_loop())
        return True

    async def _stderr_loop(self) -> None:
        """Surface ffmpeg's own diagnostics, rate-limited.

        Draining stderr also matters mechanically: a full stderr pipe would
        block ffmpeg. loglevel=error keeps this quiet in the normal case.
        """
        assert self.process is not None and self.process.stderr is not None
        last = 0.0
        try:
            while True:
                line = await self.process.stderr.readline()
                if not line:
                    break
                now = time.monotonic()
                if now - last >= DROP_WARNING_SECONDS:
                    last = now
                    log.warning(
                        "pcm_stream_stderr",
                        recording_id=self.recording_id,
                        detail=line.decode("utf-8", "replace").strip()[:200],
                    )
        except Exception:
            pass

    async def _read_loop(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        try:
            while True:
                data = await self.process.stdout.read(READ_SIZE)
                if not data:
                    break
                if self._queued_bytes > MAX_QUEUED_PCM_BYTES:
                    # the consumer is not keeping up; drop rather than grow.
                    # The recording is untouched — this costs caption words
                    # only — but it used to happen with nothing in the log,
                    # so a gap in the captions looked like silence in the room.
                    self._dropped_bytes += len(data)
                    now = time.monotonic()
                    if now - self._last_drop_warning >= DROP_WARNING_SECONDS:
                        self._last_drop_warning = now
                        log.warning(
                            "live_pcm_dropped",
                            recording_id=self.recording_id,
                            dropped_seconds=round(self._dropped_bytes / BYTES_PER_SECOND, 1),
                            reason="caption engine is not keeping up",
                        )
                    continue
                self._queued_bytes += len(data)
                self.pcm.put_nowait(data)
        except Exception:
            log.warning("pcm_stream_read_failed", recording_id=self.recording_id, exc_info=True)
        finally:
            code = self.process.returncode if self.process is not None else None
            if code:
                # a non-zero exit means ffmpeg gave up on the input — the exact
                # failure that used to be invisible. code is None on a clean EOF.
                log.warning("pcm_stream_ffmpeg_exited", recording_id=self.recording_id, code=code)
            self.pcm.put_nowait(None)

    def feed(self, chunk: bytes) -> None:
        """Append one uploaded chunk. Order matters: the stream is continuous."""
        if self.failed or self.process is None or self.process.stdin is None:
            return
        # asyncio's write() to a dead pipe does NOT raise — it drops the bytes
        # and logs a generic warning only after five occurrences. So the real
        # signal that ffmpeg has exited is its returncode, checked here.
        if self.process.returncode is not None:
            if not self.failed:
                log.warning("pcm_stream_write_failed", recording_id=self.recording_id)
            self.failed = True
            return
        self.last_fed = time.monotonic()
        try:
            self.process.stdin.write(chunk)
        except (BrokenPipeError, ConnectionResetError, RuntimeError):
            # ffmpeg gone: captions end here, the recording is unaffected
            log.warning("pcm_stream_write_failed", recording_id=self.recording_id)
            self.failed = True

    def drain(self) -> None:
        """Discard PCM buffered while no consumer was attached.

        A decoder that outlives a failed session keeps decoding through the
        reconnect gap. Without this, the replacement session would open by
        transcribing up to two minutes of stale audio before catching up.
        """
        discarded = 0
        while True:
            try:
                item = self.pcm.get_nowait()
            except asyncio.QueueEmpty:
                break
            if item is not None:
                discarded += len(item)
        self._queued_bytes = 0
        if discarded:
            log.info(
                "live_pcm_drained",
                recording_id=self.recording_id,
                seconds=round(discarded / BYTES_PER_SECOND, 1),
            )

    async def read(self) -> bytes | None:
        """Next decoded PCM block, or None when the stream ended."""
        data = await self.pcm.get()
        if data is not None:
            self._queued_bytes -= len(data)
        return data

    async def close(self) -> None:
        if self.process is None:
            return
        if self._dropped_bytes:
            log.warning(
                "live_pcm_dropped_total",
                recording_id=self.recording_id,
                dropped_seconds=round(self._dropped_bytes / BYTES_PER_SECOND, 1),
            )
        try:
            if self.process.stdin is not None and not self.process.stdin.is_closing():
                self.process.stdin.close()
        except Exception:
            pass
        if self._reader is not None:
            try:
                await asyncio.wait_for(self._reader, timeout=10)
            except (TimeoutError, asyncio.CancelledError):
                self._reader.cancel()
        if self._stderr_reader is not None:
            self._stderr_reader.cancel()
        try:
            self.process.kill()
        except ProcessLookupError:
            pass
        self.process = None


class Framer:
    """Fixed-size framing that carries the remainder between calls.

    The obvious version — slice each block on its own — is wrong here, because
    ffmpeg is read in READ_SIZE blocks and READ_SIZE is not a whole number of
    frames at any size we use. Vosk was therefore fed 8000 bytes then 192,
    repeatedly, instead of uniform frames; since it decides where an utterance
    ends on each frame it receives and resets its language context there, the
    ragged sequence moved those breaks and changed the words beside them. On
    800 s of real assembly audio that cost 7.7% of the words against the
    transcript the same model produced from the same audio in one pass.

    Feeding a whole 10 s block instead is equally wrong: one result comes back
    and captions behave like batch transcription.

    push() then flush() over a stream yields exactly what slicing the whole
    buffer at `size` would — uniform frames and one short tail — so the live
    path can feed an engine the same sequence the batch path does.
    """

    def __init__(self, seconds: float):
        size = int(BYTES_PER_SECOND * seconds)
        self.size = max(2, size - size % 2)  # never split a sample
        self._buffer = bytearray()

    def push(self, pcm: bytes) -> list[bytes]:
        """Whole frames available after adding `pcm`; the rest is kept."""
        self._buffer.extend(pcm)
        out = []
        while len(self._buffer) >= self.size:
            out.append(bytes(self._buffer[: self.size]))
            del self._buffer[: self.size]
        return out

    def flush(self) -> list[bytes]:
        """The short tail at end of stream, or nothing if it came out even."""
        if not self._buffer:
            return []
        tail = bytes(self._buffer)
        self._buffer.clear()
        return [tail]


def wav_bytes(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Wrap raw PCM in a WAV container for endpoints that need a real file."""
    import io
    import wave

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)
    return buffer.getvalue()
