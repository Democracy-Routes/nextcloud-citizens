# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Live caption message parsing (speaker-grouped provisional captions)."""

import json

from citizens.services.live_captions import DeepgramSession


def make_session() -> DeepgramSession:
    return DeepgramSession("rec-1", "key", "nova-3", "en")


def message(text: str, speaker: int | None, start: float = 1.0) -> str:
    first_word = text.split()[0] if text.split() else ""
    words = [] if speaker is None else [{"word": first_word, "speaker": speaker}]
    return json.dumps(
        {
            "type": "Results",
            "is_final": True,
            "start": start,
            "channel": {"alternatives": [{"transcript": text, "words": words}]},
        }
    )


def test_final_results_carry_speaker():
    session = make_session()
    session._handle_message(message("Hello there.", speaker=0))
    session._handle_message(message("Nice to meet you.", speaker=1))
    assert list(session.lines) == [
        {"t": 1.0, "text": "Hello there.", "speaker": 0},
        {"t": 1.0, "text": "Nice to meet you.", "speaker": 1},
    ]


def test_missing_words_yield_null_speaker():
    session = make_session()
    session._handle_message(message("No word data.", speaker=None))
    assert session.lines[0]["speaker"] is None


def test_interim_and_empty_results_ignored():
    session = make_session()
    session._handle_message(json.dumps({"type": "Results", "is_final": False}))
    session._handle_message(message("", speaker=0))
    session._handle_message("not json")
    assert len(session.lines) == 0


# --------------------------------------------------------- other engines

def test_vosk_session_keeps_finals_and_ignores_partials():
    from citizens.services.live_captions import VoskSession

    session = VoskSession("rec", "", "", "en", endpoint="ws://vosk:2700")
    # partials are shown provisionally: a table talking without pause would
    # otherwise see nothing at all until they stop
    session._handle_message(json.dumps({"partial": "the last"}))
    assert [line["text"] for line in session.lines] == ["the last"]
    assert session.lines[-1]["provisional"] is True
    session._handle_message(json.dumps({"partial": "the last bus leaves"}))
    assert [line["text"] for line in session.lines] == ["the last bus leaves"]  # replaced

    session._handle_message(json.dumps({
        "text": "the last bus leaves too early",
        "result": [{"word": "the", "start": 1.5, "end": 1.7, "conf": 1.0}],
    }))
    # the final supersedes the provisional line rather than stacking on it
    assert [line["text"] for line in session.lines] == ["the last bus leaves too early"]
    assert "provisional" not in session.lines[-1]
    assert session.lines[0]["t"] == 1.5
    assert session.lines[0]["speaker"] is None  # Vosk does not diarize


def test_vosk_session_uses_the_byte_exact_eof():
    from citizens.services import live_captions

    # the server compares this with a literal string; json.dumps differs
    assert live_captions.VOSK_EOF == '{"eof" : 1}'


def test_mistral_session_accumulates_deltas_and_commits_segments():
    from citizens.services.live_captions import MistralSession

    session = MistralSession("rec", "key", "", "en")
    session._handle_message(json.dumps({"type": "session.created", "session": {}}))
    session._handle_message(json.dumps({"type": "transcription.text.delta", "text": "the last "}))
    session._handle_message(json.dumps({"type": "transcription.text.delta", "text": "bus"}))
    # deltas show as one growing provisional line
    assert [line["text"] for line in session.lines] == ["the last bus"]
    assert session.lines[-1]["provisional"] is True
    session._handle_message(json.dumps({
        "type": "transcription.segment",
        "text": "the last bus leaves too early",
        "start": 2.0,
        "end": 6.0,
    }))
    assert [line["text"] for line in session.lines] == ["the last bus leaves too early"]
    assert session.lines[0]["t"] == 2.0
    assert "provisional" not in session.lines[-1]


def test_mistral_session_flushes_pending_text_on_done():
    from citizens.services.live_captions import MistralSession

    session = MistralSession("rec", "key", "", "en")
    session._handle_message(json.dumps({"type": "transcription.text.delta", "text": "hello there"}))
    session._handle_message(json.dumps({"type": "transcription.done", "text": "hello there"}))
    assert [line["text"] for line in session.lines] == ["hello there"]


def test_mistral_appends_match_the_documented_chunk_duration():
    from citizens.services import live_audio
    from citizens.services.live_captions import MistralSession

    # Mistral's streaming example uses chunk_duration_ms=480
    assert MistralSession.APPEND_SECONDS == 0.48
    framer = live_audio.Framer(MistralSession.APPEND_SECONDS)
    pcm = b"\x00" * (live_audio.BYTES_PER_SECOND * 30)
    slices = framer.push(pcm) + framer.flush()
    assert {len(chunk) for chunk in slices[:-1]} == {framer.size}
    assert sum(len(chunk) for chunk in slices) == len(pcm)


def test_framer_never_splits_a_sample_and_loses_nothing():
    from citizens.services import live_audio

    framer = live_audio.Framer(0.2)
    pcm = b"\x01\x02" * 8000
    chunks = framer.push(pcm) + framer.flush()
    assert all(len(chunk) % 2 == 0 for chunk in chunks)
    assert b"".join(chunks) == pcm


def test_framer_carries_the_remainder_across_reads():
    """The regression that made live captions disagree with the transcript.

    ffmpeg is read in READ_SIZE blocks, which is not a whole number of frames.
    Framing each block on its own emitted a full frame then a short one — 8000
    bytes then 192, over and over — instead of a uniform stream.
    """
    from citizens.services import live_audio

    framer = live_audio.Framer(0.2)
    emitted = []
    for _ in range(20):
        emitted += framer.push(b"\x00" * live_audio.READ_SIZE)

    assert {len(frame) for frame in emitted} == {framer.size}, (
        "frames must be uniform while the stream is running"
    )
    tail = framer.flush()
    assert len(b"".join(emitted + tail)) == 20 * live_audio.READ_SIZE


def test_live_framing_matches_the_batch_provider_exactly():
    """What makes captions and the archived transcript the same text.

    Vosk is deterministic: identical model, identical audio and an identical
    frame sequence give an identical transcript. The live path only satisfies
    that last condition if its frames come out the way vosk.py slices a file.
    """
    from citizens.providers.transcription import vosk as vosk_provider
    from citizens.services import live_audio
    from citizens.services.live_captions import VoskSession

    assert live_audio.Framer(VoskSession.FRAME_SECONDS).size == vosk_provider.FRAME_BYTES

    pcm = bytes(range(256)) * 700  # 179,200 B — not a whole number of frames
    batch = [
        pcm[offset : offset + vosk_provider.FRAME_BYTES]
        for offset in range(0, len(pcm), vosk_provider.FRAME_BYTES)
    ]
    framer = live_audio.Framer(VoskSession.FRAME_SECONDS)
    live = []
    for offset in range(0, len(pcm), live_audio.READ_SIZE):
        live += framer.push(pcm[offset : offset + live_audio.READ_SIZE])
    live += framer.flush()
    assert live == batch


def test_whisper_session_commits_only_new_text_and_drops_hallucinations():
    import asyncio

    from citizens.services import live_audio
    from citizens.services.live_captions import WhisperSession

    session = WhisperSession("rec", "", "whisper-1", "en", endpoint="http://whisper/v1")
    session._buffer.extend(b"\x00" * (live_audio.BYTES_PER_SECOND * 20))

    responses = [
        {"segments": [
            {"start": 0.0, "end": 5.0, "text": "the last bus leaves too early",
             "no_speech_prob": 0.02},
            # Whisper invents fluent text over silence — must be dropped
            {"start": 5.0, "end": 10.0, "text": "Thank you.", "no_speech_prob": 0.93},
        ]},
        {"segments": [
            # already shown by the previous window
            {"start": 0.0, "end": 5.0, "text": "the last bus leaves too early",
             "no_speech_prob": 0.02},
            {"start": 10.0, "end": 14.0, "text": "we should extend the service",
             "no_speech_prob": 0.05},
        ]},
    ]

    def fake_request(*args, **kwargs):
        return responses.pop(0)

    import citizens.services.live_captions as module

    original = module._whisper_window_request
    module._whisper_window_request = fake_request
    try:
        asyncio.run(session._transcribe_window())
        asyncio.run(session._transcribe_window())
    finally:
        module._whisper_window_request = original

    texts = [line["text"] for line in session.lines]
    assert texts == ["the last bus leaves too early", "we should extend the service"]


def test_wav_wrapper_is_a_valid_riff_container():
    import io
    import wave

    from citizens.services import live_audio

    data = live_audio.wav_bytes(b"\x00\x00" * 1600)
    with wave.open(io.BytesIO(data)) as handle:
        assert handle.getnchannels() == 1
        assert handle.getframerate() == live_audio.SAMPLE_RATE
        assert handle.getsampwidth() == 2


def test_a_session_keeps_every_line_but_shows_only_a_window():
    """The record is the whole session; the phone is shown its tail.

    self.lines used to be a deque capped at MAX_LINES, which was fine while
    captions were only ever displayed and fatal once they became the assembly's
    transcript: a 30-minute round kept its last eighty lines and silently
    dropped the rest.
    """
    from citizens.services.live_captions import LIVE_CAPTIONS, MAX_LINES

    session = make_session()
    for index in range(MAX_LINES + 120):
        session.add_line(f"line {index}", start=float(index))

    assert len(session.lines) == MAX_LINES + 120, "the transcript must keep everything"

    LIVE_CAPTIONS._sessions["rec-window"] = session
    try:
        shown = LIVE_CAPTIONS.status("rec-window")["lines"]
    finally:
        LIVE_CAPTIONS._sessions.pop("rec-window", None)
    assert len(shown) == MAX_LINES, "a phone polling every couple of seconds must not get it all"
    assert shown[-1]["text"] == f"line {MAX_LINES + 119}"


def test_a_runaway_session_stops_rather_than_rewriting_its_start():
    from citizens.services import live_captions

    session = make_session()
    original = live_captions.MAX_TRANSCRIPT_LINES
    live_captions.MAX_TRANSCRIPT_LINES = 5
    try:
        for index in range(12):
            session.add_line(f"line {index}", start=float(index))
    finally:
        live_captions.MAX_TRANSCRIPT_LINES = original

    assert len(session.lines) == 5
    assert session.truncated is True
    # the beginning survives: dropping the oldest lines would quietly change
    # what the transcript says happened first
    assert session.lines[0]["text"] == "line 0"


def test_provisional_lines_are_still_replaced_in_place():
    """set_provisional/_drop_provisional worked on a deque; they must behave
    identically now that lines is a list, or captions would stutter."""
    session = make_session()
    session.add_line("committed", start=0.0)
    session.set_provisional("part", start=1.0)
    session.set_provisional("partial text", start=1.0)
    assert [line["text"] for line in session.lines] == ["committed", "partial text"]
    session.add_line("final text", start=1.0)
    assert [line["text"] for line in session.lines] == ["committed", "final text"]


def test_a_restarted_session_does_not_erase_what_came_before(settings_env):
    """A caption session that dies mid-round is replaced after the cooldown,
    and the replacement starts with an empty buffer. Writing that over the file
    would discard everything said before the failure — with final transcription
    off, that is half a transcript gone and nothing to say it went."""
    import asyncio
    import json

    from citizens.services.live_captions import LIVE_CAPTIONS
    from citizens.storage.paths import live_caption_path

    first = make_session()
    first.recording_id, first.assembly_id = "rec-resume", "asm-1"
    first.add_line("before the failure", start=1.0)
    asyncio.run(LIVE_CAPTIONS._persist_transcript(first))

    second = make_session()
    second.recording_id, second.assembly_id = "rec-resume", "asm-1"
    second.add_line("after reconnecting", start=90.0)
    asyncio.run(LIVE_CAPTIONS._persist_transcript(second))

    written = json.loads(
        live_caption_path(settings_env.app_persistent_storage, "asm-1", "rec-resume").read_text()
    )
    assert [line["text"] for line in written["lines"]] == [
        "before the failure",
        "after reconnecting",
    ]
    assert written["resumed"] is True


# --------------------------------------------------- silence keepalive

def test_a_quiet_phone_gets_real_time_silence_sent_in_its_place():
    """Mistral closes a socket that receives no audio for about half a minute
    (every drop in the 2026-10-11 log followed a hole in the upload stream).
    After SILENCE_AFTER_SECONDS without a chunk the session sends a second of
    silence per second until audio returns, and remembers how much."""
    import asyncio

    from citizens.services import live_audio
    from citizens.services.live_captions import MistralSession

    async def scenario():
        session = MistralSession("rec", "key", "", "en")
        first = await session.next_audio(idle_seconds=0.01, frame_seconds=1.0)
        assert first == bytes(live_audio.BYTES_PER_SECOND), "one second of PCM silence"
        assert session.injected_seconds == 1.0
        # still idle: the next wait is one frame, not the long idle wait
        second = await session.next_audio(idle_seconds=10.0, frame_seconds=0.01)
        assert second == bytes(int(live_audio.BYTES_PER_SECOND * 0.01))
        # audio returns: it is handed over as is, and the idle state ends
        session.queue.put_nowait(b"speech")
        assert await session.next_audio(idle_seconds=0.01, frame_seconds=1.0) == b"speech"
        assert session._idle is False
        session.queue.put_nowait(None)
        assert await session.next_audio(idle_seconds=0.01) is None

    asyncio.run(scenario())


def test_injected_silence_is_subtracted_from_the_engines_clock():
    """The engine's timeline runs ahead of the recording by the silence the
    session made up; with final transcription off these lines ARE the
    transcript, so they must keep the recording's own clock."""
    import json

    from citizens.services.live_captions import MistralSession, VoskSession

    mistral = MistralSession("rec", "key", "", "en")
    mistral.injected_seconds = 60.0
    mistral._handle_message(json.dumps(
        {"type": "transcription.segment", "text": "after the gap", "start": 70.5, "end": 72.0}
    ))
    assert mistral.lines[-1]["t"] == 10.5 and mistral.lines[-1]["end"] == 12.0
    # never before the start of the recording, whatever the arithmetic says
    mistral._handle_message(json.dumps(
        {"type": "transcription.segment", "text": "odd", "start": 59.0, "end": 59.5}
    ))
    assert mistral.lines[-1]["t"] == 0.0

    vosk = VoskSession("rec", "", "", "en", endpoint="ws://vosk:2700")
    vosk.injected_seconds = 30.0
    vosk._handle_message(json.dumps({
        "text": "hello there",
        "result": [
            {"word": "hello", "start": 40.0, "end": 40.4},
            {"word": "there", "start": 40.5, "end": 41.0},
        ],
    }))
    line = vosk.lines[-1]
    assert line["t"] == 10.0 and line["end"] == 11.0
    assert [w["start"] for w in line["words"]] == [10.0, 10.5]
