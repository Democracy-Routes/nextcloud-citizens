# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Final (batch) transcription: dispatch to the configured provider and store
the normalized transcript (brief §30–§33)."""

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from citizens.config import get_settings
from citizens.db.models import Assembly, Recording, Transcript, TranscriptSegment, TranscriptWord
from citizens.logging_setup import get_logger
from citizens.providers.transcription import deepgram as deepgram_provider
from citizens.providers.transcription import mistral as mistral_provider
from citizens.providers.transcription import vosk as vosk_provider
from citizens.providers.transcription import whisper as whisper_provider
from citizens.providers.transcription.base import (
    NormalizedSegment,
    NormalizedTranscript,
    NormalizedWord,
    SpeakerLabeler,
    TranscriptionError,
)
from citizens.services import provider_config
from citizens.services.audit import record_audit_event

log = get_logger(__name__)

# hosted providers authenticate with a key; self-hostable ones are reachable
# at a URL instead (a Whisper server may or may not require a key)
KEYED_PROVIDERS = ("deepgram", "mistral")
URL_PROVIDERS = {"whisper": "whisper_base_url", "vosk": "vosk_url"}


def batch_transcription_ready(store: provider_config.ConfigStore) -> bool:
    if provider_config.get_setting(store, "stt_batch_enabled") != "1":
        return False
    provider = provider_config.get_setting(store, "stt_provider")
    if provider in URL_PROVIDERS:
        return bool(provider_config.get_setting(store, URL_PROVIDERS[provider]))
    if provider in KEYED_PROVIDERS:
        return bool(store.get_value(f"{provider}_api_key"))
    return False


def live_transcription_ready(store: provider_config.ConfigStore) -> bool:
    """Whether live captions are configured — the same shape as
    batch_transcription_ready, because either can be the transcript of record."""
    if provider_config.get_setting(store, "stt_live_enabled") != "1":
        return False
    provider = provider_config.get_setting(store, "stt_provider")
    if provider in URL_PROVIDERS:
        return bool(provider_config.get_setting(store, URL_PROVIDERS[provider]))
    if provider in KEYED_PROVIDERS:
        return bool(store.get_value(f"{provider}_api_key"))
    return False


# what a caption line gets when its engine reported no end time and there is no
# following line to run up to
TRAILING_SEGMENT_SECONDS = 2.0


def transcript_from_live_captions(data: dict) -> NormalizedTranscript:
    """Turn a finished caption session into the same structure a provider
    adapter returns, so store_transcript can treat it identically.

    Caption engines are looser than batch ones about timings: Vosk and Whisper
    give an end per line, Deepgram a duration, Mistral often neither. A segment
    with no end is run up to the start of the next line, which is what actually
    happened in the room.
    """
    labeler = SpeakerLabeler()
    lines = [line for line in (data.get("lines") or []) if (line.get("text") or "").strip()]
    segments: list[NormalizedSegment] = []
    for index, line in enumerate(lines):
        start = float(line.get("t") or 0.0)
        end = line.get("end")
        end = float(end) if end is not None else None
        if end is None or end <= start:
            following = float(lines[index + 1].get("t") or 0.0) if index + 1 < len(lines) else None
            end = following if following is not None and following > start else None
        if end is None:
            end = start + TRAILING_SEGMENT_SECONDS
        segments.append(
            NormalizedSegment(
                speaker=labeler.label(line.get("speaker")),
                start=start,
                end=end,
                text=(line.get("text") or "").strip(),
                words=[
                    NormalizedWord(
                        text=(word.get("text") or "")[:200],
                        start=float(word.get("start") or 0.0),
                        end=float(word.get("end") or 0.0),
                    )
                    for word in (line.get("words") or [])
                ],
            )
        )
    return NormalizedTranscript(
        provider=data.get("provider") or "",
        model=data.get("model") or "",
        language=data.get("language") or "",
        segments=segments,
        raw=data,
    )


def transcribe_recording(
    session: Session, store: provider_config.ConfigStore, recording: Recording
) -> Transcript:
    settings = get_settings()
    audio_path = settings.app_persistent_storage / recording.canonical_audio_path
    if not recording.canonical_audio_path or not audio_path.exists():
        raise TranscriptionError("Canonical audio file is missing", permanent=True)

    assembly = session.get(Assembly, recording.assembly_id)
    language = assembly.language if assembly else ""
    # release the DB write lock BEFORE reading provider config — those reads
    # are OCS calls to Nextcloud, and a held job transaction 500s every API
    # request after busy_timeout (expire_on_commit=False keeps `recording` and
    # `assembly` usable afterwards)
    session.commit()
    provider = provider_config.get_setting(store, "stt_provider")
    # Record now never asked which language the table speaks: let an engine
    # that can detect it do so, and keep the guess only for Vosk, which must
    # pick a model up front
    detect = bool(assembly and assembly.language_auto) and provider in DETECTING_PROVIDERS
    if detect:
        language = ""

    log.info(
        "stt_started",
        recording_id=recording.id,
        provider=provider,
        size_bytes=audio_path.stat().st_size,
    )
    if provider == "deepgram":
        key = store.get_value("deepgram_api_key")
        if not key:
            raise TranscriptionError("No Deepgram API key configured", permanent=True)
        normalized = deepgram_provider.transcribe_file(
            key, audio_path, recording.mime_type, language,
            model=provider_config.get_setting(store, "deepgram_batch_model"),
        )
    elif provider == "mistral":
        key = store.get_value("mistral_api_key")
        if not key:
            raise TranscriptionError("No Mistral API key configured", permanent=True)
        normalized = mistral_provider.transcribe_file(
            key, audio_path, recording.mime_type, language,
            model=provider_config.get_setting(store, "mistral_batch_model"),
        )
    elif provider == "whisper":
        base_url = provider_config.get_setting(store, "whisper_base_url")
        if not base_url:
            raise TranscriptionError("No Whisper endpoint configured", permanent=True)
        normalized = whisper_provider.transcribe_file(
            # self-hosted servers usually need no key; hosted OpenAI does
            store.get_value("whisper_api_key") or "",
            audio_path, recording.mime_type, language,
            model=provider_config.get_setting(store, "whisper_batch_model"),
            base_url=base_url,
        )
    elif provider == "vosk":
        url = provider_config.get_setting(store, "vosk_url")
        if not url:
            raise TranscriptionError("No Vosk server URL configured", permanent=True)
        # one server can hold a model per language; pick this assembly's
        # canonical-transcript model (captions may use a different one)
        model = provider_config.vosk_model_for(
            store, language, "final"
        ) or provider_config.vosk_model_path(
            provider_config.get_setting(store, "vosk_batch_model")
        )
        log.info("vosk_model_selected", language=language, model=model or "(server default)")
        normalized = vosk_provider.transcribe_file(
            "", audio_path, recording.mime_type, language, model=model, base_url=url,
        )
    else:
        raise TranscriptionError(f"Unknown STT provider {provider}", permanent=True)

    if assembly is not None and assembly.language_auto:
        adopt_detected_language(session, assembly, normalized.language, recording)
    transcript = store_transcript(session, recording, normalized)
    log.info(
        "stt_completed",
        recording_id=recording.id,
        provider=provider,
        segments=len(normalized.segments),
    )
    return transcript


#: engines that return the language they heard when none is forced
DETECTING_PROVIDERS = ("deepgram", "mistral", "whisper")


def adopt_detected_language(
    session: Session, assembly: Assembly, detected: str | None, recording: Recording
) -> bool:
    """The first final transcript of a Record-now session decides its language.

    Only a language the app knows (schemas.Language), only when it differs,
    and only while the assembly has no transcript yet — later tables never
    flip it back, so the report stays in one language. Analysis prompts and
    report wording read `assembly.language`, so everything downstream follows.
    """
    from citizens.domain.schemas import Language

    code = (detected or "").strip().lower().replace("_", "-").split("-")[0]
    if not code or code == assembly.language or code not in Language.__args__:
        return False
    already = session.execute(
        select(func.count())
        .select_from(Transcript)
        .join(Recording, Transcript.recording_id == Recording.id)
        .where(Recording.assembly_id == assembly.id)
    ).scalar_one()
    if already:
        return False
    previous = assembly.language
    assembly.language = code
    record_audit_event(
        session, "language_detected", "assembly", assembly.id,
        data={"from": previous, "to": code, "recording_id": recording.id},
    )
    log.info("language_detected", assembly_id=assembly.id, previous=previous, detected=code)
    return True


def store_transcript(
    session: Session,
    recording: Recording,
    normalized: NormalizedTranscript,
    source: str = "final",
) -> Transcript:
    """Replace any existing transcript for this recording (retranscription)."""
    existing = session.query(Transcript).filter_by(recording_id=recording.id).one_or_none()
    if existing is not None:
        # the old segments cascade away, taking every finding's evidence links
        # with them (the new segments have new ids) — flag those findings so
        # reports do not silently show them without quotes
        from citizens.services.files import mark_evidence_removed

        mark_evidence_removed(session, existing)
        session.delete(existing)
        session.flush()

    settings = get_settings()
    raw_dir = settings.app_persistent_storage / "transcripts" / recording.assembly_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{recording.id}.raw.json"
    raw_path.write_text(json.dumps(normalized.raw))

    transcript = Transcript(
        recording_id=recording.id,
        provider=normalized.provider,
        model=normalized.model,
        language=normalized.language,
        source=source,
        raw_response_path=str(raw_path.relative_to(settings.app_persistent_storage)),
    )
    for index, segment in enumerate(normalized.segments):
        row = TranscriptSegment(
            sequence=index,
            speaker_label=segment.speaker,
            start_seconds=segment.start,
            end_seconds=segment.end,
            text=segment.text,
        )
        for word_index, word in enumerate(segment.words):
            row.words.append(
                TranscriptWord(
                    sequence=word_index,
                    text=word.text[:200],
                    start_seconds=word.start,
                    end_seconds=word.end,
                )
            )
        transcript.segments.append(row)
    session.add(transcript)
    session.flush()
    return transcript


def transcript_provenance(transcript: Transcript) -> dict:
    """Where this transcript came from, stated explicitly.

    `source_type` is "final" (the finished audio, transcribed by a batch
    provider) or "live" (the round's live captions, adopted when final
    transcription is off). The Transcript row IS the canonical record of its
    recording — one per recording, and `store_transcript` replaces it when a
    final transcription lands over a live one — so `canonical` is always true
    here; it exists so a reader never has to infer the rule. A live-caption
    file may also exist beside a final transcript (see the API), as the
    provisional record it was.
    """
    return {
        "source_type": transcript.source,
        "provider": transcript.provider,
        "model": transcript.model,
        "language": transcript.language,
        "recording_id": transcript.recording_id,
        # ISO text, not a datetime: this payload is also written into exports
        "created_at": transcript.created_at.isoformat() if transcript.created_at else None,
        "canonical": True,
    }


def transcript_payload(transcript: Transcript) -> dict:
    return {
        "transcript_id": transcript.id,
        "recording_id": transcript.recording_id,
        "provider": transcript.provider,
        "model": transcript.model,
        "language": transcript.language,
        "source": transcript.source,
        "provenance": transcript_provenance(transcript),
        "segments": [
            {
                "id": segment.id,
                "speaker": segment.speaker_label,
                "start": segment.start_seconds,
                "end": segment.end_seconds,
                "text": segment.text,
            }
            for segment in transcript.segments
        ],
    }
