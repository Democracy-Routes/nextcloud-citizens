# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deepgram batch transcription adapter.

API verified 2026-08-23: POST https://api.deepgram.com/v1/listen with raw
audio body; `diarize_model=latest` is the current diarization parameter
(diarize=true is deprecated/v1-only); `utterances=true` groups words into
speaker turns which map directly onto our normalized segments.
"""

from pathlib import Path

import httpx

from citizens.logging_setup import get_logger
from citizens.providers.transcription.base import (
    NormalizedSegment,
    NormalizedTranscript,
    NormalizedWord,
    SpeakerLabeler,
    TranscriptionError,
)

log = get_logger(__name__)

BASE_URL = "https://api.deepgram.com/v1/listen"
DEFAULT_MODEL = "nova-3"


def transcribe_file(
    api_key: str, path: Path, mime_type: str, language: str, model: str = DEFAULT_MODEL
) -> NormalizedTranscript:
    params = {
        "model": model or DEFAULT_MODEL,
        "diarize_model": "latest",
        "utterances": "true",
        "smart_format": "true",
        "punctuate": "true",
    }
    if language:
        params["language"] = language
    else:
        # no language forced (Record now): let Deepgram say what it heard;
        # normalize() keeps `detected_language` as the transcript's language
        params["detect_language"] = "true"
    content_type = (mime_type or "audio/webm").split(";")[0].strip()

    try:
        response = httpx.post(
            BASE_URL,
            params=params,
            headers={"Authorization": f"Token {api_key}", "Content-Type": content_type},
            content=path.read_bytes(),
            timeout=httpx.Timeout(600, connect=30),
        )
    except httpx.HTTPError as exc:
        raise TranscriptionError(f"Deepgram request failed: {type(exc).__name__}") from exc

    if response.status_code in (401, 403):
        raise TranscriptionError(f"Deepgram authentication failed ({response.status_code})", permanent=True)
    if response.status_code == 400:
        raise TranscriptionError(f"Deepgram rejected the audio: {response.text[:300]}", permanent=True)
    if response.status_code != 200:
        raise TranscriptionError(f"Deepgram returned HTTP {response.status_code}")

    raw = response.json()
    return normalize(raw, model=model or DEFAULT_MODEL, requested_language=language)


def normalize(raw: dict, model: str, requested_language: str) -> NormalizedTranscript:
    results = raw.get("results", {})
    labeler = SpeakerLabeler()
    segments: list[NormalizedSegment] = []

    utterances = results.get("utterances") or []
    if utterances:
        for utterance in utterances:
            segments.append(
                NormalizedSegment(
                    speaker=labeler.label(utterance.get("speaker")),
                    start=float(utterance.get("start", 0.0)),
                    end=float(utterance.get("end", 0.0)),
                    text=(utterance.get("transcript") or "").strip(),
                    words=[
                        NormalizedWord(
                            text=word.get("punctuated_word") or word.get("word") or "",
                            start=float(word.get("start", 0.0)),
                            end=float(word.get("end", 0.0)),
                        )
                        for word in utterance.get("words") or []
                    ],
                )
            )
    else:
        # no utterances (e.g. silence): fall back to the channel transcript
        channels = results.get("channels") or []
        alternatives = (channels[0].get("alternatives") if channels else None) or []
        if alternatives and (alternatives[0].get("transcript") or "").strip():
            words = alternatives[0].get("words") or []
            segments.append(
                NormalizedSegment(
                    speaker="",
                    start=float(words[0]["start"]) if words else 0.0,
                    end=float(words[-1]["end"]) if words else 0.0,
                    text=alternatives[0]["transcript"].strip(),
                    words=[
                        NormalizedWord(
                            text=w.get("punctuated_word") or w.get("word") or "",
                            start=float(w.get("start", 0.0)),
                            end=float(w.get("end", 0.0)),
                        )
                        for w in words
                    ],
                )
            )

    detected = ""
    channels = results.get("channels") or []
    if channels:
        detected = channels[0].get("detected_language") or ""
    return NormalizedTranscript(
        provider="deepgram",
        model=model,
        language=detected or requested_language,
        segments=[s for s in segments if s.text],
        raw=raw,
    )
