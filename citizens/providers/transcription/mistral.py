# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Mistral (Voxtral) batch transcription adapter.

API verified against docs 2026-08-23: POST /v1/audio/transcriptions
(multipart), model `voxtral-mini-latest` (Voxtral Mini Transcribe 2),
`diarize=true`, `timestamp_granularities` segment/word. Segment fields are
parsed defensively (docs don't publish the exact chunk schema).
"""

from pathlib import Path

import httpx

from citizens.logging_setup import get_logger
from citizens.providers.http_detail import error_detail, retry_after_seconds
from citizens.providers.transcription.base import (
    NormalizedSegment,
    NormalizedTranscript,
    NormalizedWord,
    SpeakerLabeler,
    TranscriptionError,
)

log = get_logger(__name__)

BASE_URL = "https://api.mistral.ai/v1/audio/transcriptions"
DEFAULT_MODEL = "voxtral-mini-latest"

#: A 30-minute table took 107-313 s on 2026-09-08; a 40-minute round scales to
#: ~140-420 s, and a slow day sits on top. 600 s left no margin, and a timeout
#: is the worst failure: every retry re-uploads the whole file to time out
#: again. Must stay below the job runner's lease (RUNNING_LEASE_SECONDS,
#: 1800) or the runner reclaims a job that is still uploading.
REQUEST_TIMEOUT_SECONDS = 1500


def transcribe_file(
    api_key: str, path: Path, mime_type: str, language: str, model: str = DEFAULT_MODEL
) -> NormalizedTranscript:
    data: dict = {
        "model": model or DEFAULT_MODEL,
        "diarize": "true",
        "timestamp_granularities": "segment",
    }
    # per docs, language is incompatible with timestamp_granularities — prefer timestamps
    try:
        response = httpx.post(
            BASE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            data=data,
            files={"file": (path.name, path.read_bytes(), mime_type.split(";")[0] or "audio/webm")},
            timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS, connect=30),
        )
    except httpx.HTTPError as exc:
        raise TranscriptionError(f"Mistral request failed: {type(exc).__name__}") from exc

    status = response.status_code
    if status != 200:
        detail = error_detail(response)
        log.warning("stt_provider_refused", provider="mistral", status=status, detail=detail)
        if status in (401, 403):
            raise TranscriptionError(
                f"Mistral authentication failed ({status}): {detail}", permanent=True, status=status
            )
        if status == 422:
            raise TranscriptionError(
                f"Mistral rejected the request: {detail}", permanent=True, status=status
            )
        if status == 429:
            raise TranscriptionError(
                f"Mistral returned HTTP 429 (rate limited): {detail}",
                status=status, retry_after=retry_after_seconds(response.headers),
            )
        raise TranscriptionError(f"Mistral returned HTTP {status}: {detail}", status=status)

    try:
        raw = response.json()
    except ValueError as exc:
        # an HTML error page where JSON was expected: not our audio's fault
        raise TranscriptionError("Mistral returned a non-JSON response", status=status) from exc
    return normalize(raw, model=model or DEFAULT_MODEL, requested_language=language)


def _first(mapping: dict, *keys, default=None):
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return default


def normalize(raw: dict, model: str, requested_language: str) -> NormalizedTranscript:
    labeler = SpeakerLabeler()
    segments: list[NormalizedSegment] = []
    for chunk in raw.get("segments") or []:
        text = (_first(chunk, "text", "transcript", default="") or "").strip()
        if not text:
            continue
        segments.append(
            NormalizedSegment(
                speaker=labeler.label(_first(chunk, "speaker", "speaker_id", "speaker_label")),
                start=float(_first(chunk, "start", "start_seconds", default=0.0)),
                end=float(_first(chunk, "end", "end_seconds", default=0.0)),
                text=text,
                words=[
                    NormalizedWord(
                        text=_first(word, "text", "word", default="") or "",
                        start=float(_first(word, "start", default=0.0)),
                        end=float(_first(word, "end", default=0.0)),
                    )
                    for word in chunk.get("words") or []
                ],
            )
        )
    if not segments and (raw.get("text") or "").strip():
        segments.append(
            NormalizedSegment(speaker="", start=0.0, end=0.0, text=raw["text"].strip())
        )
    return NormalizedTranscript(
        provider="mistral",
        model=model,
        language=raw.get("language") or requested_language or "",
        segments=segments,
        raw=raw,
    )
