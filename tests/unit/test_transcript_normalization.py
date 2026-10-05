# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
from citizens.providers.transcription import deepgram, mistral
from citizens.providers.transcription.base import SpeakerLabeler

DEEPGRAM_RAW = {
    "results": {
        "channels": [
            {
                "alternatives": [
                    {
                        "transcript": "Hello there. General Kenobi.",
                        "words": [
                            {"word": "hello", "punctuated_word": "Hello",
                             "start": 0.1, "end": 0.4, "speaker": 0},
                            {"word": "there", "punctuated_word": "there.",
                             "start": 0.45, "end": 0.8, "speaker": 0},
                            {"word": "general", "punctuated_word": "General",
                             "start": 1.2, "end": 1.6, "speaker": 1},
                            {"word": "kenobi", "punctuated_word": "Kenobi.",
                             "start": 1.65, "end": 2.1, "speaker": 1},
                        ],
                    }
                ]
            }
        ],
        "utterances": [
            {
                "speaker": 0, "start": 0.1, "end": 0.8, "transcript": "Hello there.",
                "words": [
                    {"word": "hello", "punctuated_word": "Hello", "start": 0.1, "end": 0.4},
                    {"word": "there", "punctuated_word": "there.", "start": 0.45, "end": 0.8},
                ],
            },
            {
                "speaker": 1, "start": 1.2, "end": 2.1, "transcript": "General Kenobi.",
                "words": [
                    {"word": "general", "punctuated_word": "General", "start": 1.2, "end": 1.6},
                    {"word": "kenobi", "punctuated_word": "Kenobi.", "start": 1.65, "end": 2.1},
                ],
            },
            {"speaker": 0, "start": 2.5, "end": 2.9, "transcript": "Indeed."},
        ],
    }
}


def test_deepgram_detects_the_language_only_when_none_is_forced(monkeypatch, tmp_path):
    """Record now sends no language: Deepgram is asked to detect it. A chosen
    language is forced and detection is not requested."""
    import httpx

    captured: list[dict] = []

    class _Response:
        status_code = 200
        text = ""

        def json(self):
            return {"results": {"channels": [{"detected_language": "it", "alternatives": [{"transcript": "",
                                                                                            "words": []}]}]}}

    def fake_post(url, params=None, **kwargs):
        captured.append(dict(params or {}))
        return _Response()

    monkeypatch.setattr(httpx, "post", fake_post)
    audio = tmp_path / "a.webm"
    audio.write_bytes(b"\x1a\x45\xdf\xa3")
    detected = deepgram.transcribe_file("key", audio, "audio/webm", "")
    assert captured[-1].get("detect_language") == "true" and "language" not in captured[-1]
    assert detected.language == "it"
    deepgram.transcribe_file("key", audio, "audio/webm", "en")
    assert captured[-1].get("language") == "en" and "detect_language" not in captured[-1]


def test_deepgram_normalization_utterances_and_speakers():
    result = deepgram.normalize(DEEPGRAM_RAW, model="nova-3", requested_language="en")
    assert result.provider == "deepgram"
    assert len(result.segments) == 3
    assert [s.speaker for s in result.segments] == ["SPEAKER_01", "SPEAKER_02", "SPEAKER_01"]
    assert result.segments[0].text == "Hello there."
    assert result.segments[0].words[1].text == "there."
    assert result.segments[1].start == 1.2
    assert result.language == "en"


def test_deepgram_normalization_no_utterances_fallback():
    raw = {
        "results": {
            "channels": [
                {
                    "alternatives": [
                        {
                            "transcript": "Just one line.",
                            "words": [
                                {"word": "just", "start": 0.0, "end": 0.2},
                                {"word": "line", "start": 0.5, "end": 0.9},
                            ],
                        }
                    ]
                }
            ]
        }
    }
    result = deepgram.normalize(raw, model="nova-3", requested_language="it")
    assert len(result.segments) == 1
    assert result.segments[0].speaker == ""
    assert result.segments[0].end == 0.9


def test_deepgram_normalization_silence():
    raw = {"results": {"channels": [{"alternatives": [{"transcript": "", "words": []}]}]}}
    result = deepgram.normalize(raw, model="nova-3", requested_language="en")
    assert result.segments == []


MISTRAL_RAW = {
    "model": "voxtral-mini-latest",
    "text": "Buongiorno a tutti. Grazie mille.",
    "language": "it",
    "segments": [
        {"text": "Buongiorno a tutti.", "start": 0.2, "end": 1.4, "speaker": "spk_0"},
        {"text": "Grazie mille.", "start": 2.0, "end": 2.8, "speaker": "spk_1"},
        {"text": "  ", "start": 3.0, "end": 3.1, "speaker": "spk_0"},
    ],
}


def test_mistral_normalization():
    result = mistral.normalize(MISTRAL_RAW, model="voxtral-mini-latest", requested_language="it")
    assert result.provider == "mistral"
    assert len(result.segments) == 2  # blank segment dropped
    assert [s.speaker for s in result.segments] == ["SPEAKER_01", "SPEAKER_02"]
    assert result.language == "it"


def test_mistral_normalization_text_only():
    raw = {"text": "Solo testo.", "segments": []}
    result = mistral.normalize(raw, model="m", requested_language="")
    assert len(result.segments) == 1
    assert result.segments[0].speaker == ""


def test_speaker_labeler_orders_by_first_appearance():
    labeler = SpeakerLabeler()
    assert labeler.label(7) == "SPEAKER_01"
    assert labeler.label(2) == "SPEAKER_02"
    assert labeler.label(7) == "SPEAKER_01"
    assert labeler.label(None) == ""


# ---------------------------------------------------------------- Whisper

WHISPER_VERBOSE = {
    "task": "transcribe",
    "language": "english",
    "duration": 12.5,
    "text": "The last bus leaves too early. I cycle instead.",
    "segments": [
        {"id": 0, "seek": 0, "start": 0.0, "end": 6.0,
         "text": " The last bus leaves too early.", "no_speech_prob": 0.01},
        {"id": 1, "seek": 0, "start": 6.2, "end": 12.5,
         "text": " I cycle instead.", "no_speech_prob": 0.02},
    ],
    # verbose_json puts every word in ONE flat list, not inside the segments
    "words": [
        {"word": "The", "start": 0.0, "end": 0.3},
        {"word": "last", "start": 0.3, "end": 0.7},
        {"word": "bus", "start": 0.7, "end": 1.1},
        {"word": "I", "start": 6.2, "end": 6.4},
        {"word": "cycle", "start": 6.4, "end": 6.9},
    ],
}

WHISPER_DIARIZED = {
    "task": "transcribe",
    "duration": 9.0,
    "text": "Good morning. Nice to meet you.",
    "segments": [
        {"type": "transcript.text.segment", "id": "seg_0", "start": 0.0, "end": 4.0,
         "text": "Good morning.", "speaker": "A"},
        {"type": "transcript.text.segment", "id": "seg_1", "start": 4.2, "end": 9.0,
         "text": "Nice to meet you.", "speaker": "B"},
    ],
}


def test_whisper_verbose_json_segments_and_flat_words():
    from citizens.providers.transcription import whisper

    result = whisper.normalize(WHISPER_VERBOSE, model="whisper-1", requested_language="en")
    assert result.provider == "whisper"
    assert result.language == "english"
    assert len(result.segments) == 2
    # plain Whisper has no speakers at all
    assert [s.speaker for s in result.segments] == ["", ""]
    # the flat word list is split across segments by time
    assert [w.text for w in result.segments[0].words] == ["The", "last", "bus"]
    assert [w.text for w in result.segments[1].words] == ["I", "cycle"]


def test_whisper_diarized_json_gets_speaker_labels():
    from citizens.providers.transcription import whisper

    result = whisper.normalize(WHISPER_DIARIZED, model="gpt-4o-transcribe-diarize",
                               requested_language="en")
    assert [s.speaker for s in result.segments] == ["SPEAKER_01", "SPEAKER_02"]
    assert result.segments[0].words == []  # the diarizing model returns no word timings


def test_whisper_server_injected_speaker_is_used():
    from citizens.providers.transcription import whisper

    raw = {
        "text": "hello there",
        "segments": [
            {"start": 0.0, "end": 2.0, "text": "hello", "speaker": "SPEAKER_00"},
            {"start": 2.0, "end": 4.0, "text": "there", "speaker": "SPEAKER_01"},
        ],
    }
    result = whisper.normalize(raw, model="whisper-1", requested_language="it")
    assert [s.speaker for s in result.segments] == ["SPEAKER_01", "SPEAKER_02"]
    assert result.language == "it"  # no language in the response → requested one


def test_whisper_plain_json_without_segments():
    from citizens.providers.transcription import whisper

    result = whisper.normalize(
        {"text": "one block of text", "duration": 5.0}, model="whisper-1", requested_language="en"
    )
    assert len(result.segments) == 1
    assert result.segments[0].speaker == ""
    assert result.segments[0].end == 5.0


def test_whisper_silence_yields_no_segments():
    from citizens.providers.transcription import whisper

    assert whisper.normalize({"text": "  ", "segments": []}, model="whisper-1",
                             requested_language="en").segments == []


# ------------------------------------------------------------------- Vosk

VOSK_RAW = {
    "results": [
        {"text": "the last bus leaves too early",
         "result": [
             {"conf": 1.0, "start": 0.9, "end": 1.2, "word": "the"},
             {"conf": 0.99, "start": 1.2, "end": 1.6, "word": "last"},
             {"conf": 0.98, "start": 1.6, "end": 2.0, "word": "bus"},
         ]},
        {"text": "i cycle instead",
         "result": [
             {"conf": 1.0, "start": 3.0, "end": 3.2, "word": "i"},
             {"conf": 0.97, "start": 3.2, "end": 3.8, "word": "cycle"},
         ]},
    ]
}


def test_vosk_normalization_words_and_no_speakers():
    from citizens.providers.transcription import vosk

    result = vosk.normalize(VOSK_RAW, model="", requested_language="en")
    assert result.provider == "vosk"
    assert result.model == "vosk-server"
    assert len(result.segments) == 2
    # Vosk does not diarize — the base class documents "" for that case
    assert [s.speaker for s in result.segments] == ["", ""]
    assert result.segments[0].start == 0.9 and result.segments[0].end == 2.0
    assert [w.text for w in result.segments[1].words] == ["i", "cycle"]


def test_vosk_empty_and_textless_results():
    from citizens.providers.transcription import vosk

    assert vosk.normalize({"results": []}, model="", requested_language="en").segments == []
    # a final with words but no text field still produces text
    raw = {"results": [{"result": [{"start": 0.0, "end": 0.5, "word": "ciao"}]}]}
    result = vosk.normalize(raw, model="", requested_language="it")
    assert result.segments[0].text == "ciao"


def test_vosk_eof_message_is_byte_exact():
    from citizens.providers.transcription import vosk

    # the server compares this with a literal string; json.dumps would differ
    assert vosk.EOF_MESSAGE == '{"eof" : 1}'
