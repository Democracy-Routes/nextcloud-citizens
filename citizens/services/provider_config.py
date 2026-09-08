# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Provider configuration (STT + analysis) in Nextcloud AppConfig.

API keys are stored with the `sensitive` flag (encrypted by Nextcloud, brief
§28) and are never returned by any API — only `configured` + a short hint.
"""

import json
import time
from typing import Protocol

import httpx

from citizens.logging_setup import get_logger

log = get_logger(__name__)

_LIVE_SNAPSHOT_TTL = 30.0
_live_snapshot: tuple[float, dict] | None = None


def live_stt_snapshot() -> dict:
    """Cached view of the live-STT config — read on every chunk upload, so it
    must not hit Nextcloud's AppConfig OCS API each time."""
    global _live_snapshot
    now = time.monotonic()
    if _live_snapshot is not None and now - _live_snapshot[0] < _LIVE_SNAPSHOT_TTL:
        return _live_snapshot[1]
    try:
        store = default_store()
        provider = get_setting(store, "stt_provider")
        snapshot = {
            "enabled": get_setting(store, "stt_live_enabled") == "1",
            "provider": provider,
            # per-provider keys by name: a hardcoded pair silently handed any
            # newly added provider the wrong credentials
            "api_key": store.get_value(f"{provider}_api_key"),
            "model": get_setting(store, f"{provider}_live_model"),
            # the socket/endpoint each caption engine connects to
            "endpoint": get_setting(store, LIVE_ENDPOINT_KEYS.get(provider, "")),
            # Vosk only: language -> model path, carried here so the caption
            # path never has to make an OCS call per chunk
            "vosk_models": vosk_language_models(store) if provider == "vosk" else {},
            # per-provider cap on concurrent LIVE caption sessions (DEFAULTS)
            "concurrency": stt_concurrency_limit(store, provider, "live"),
        }
    except Exception:
        log.warning("live_stt_snapshot_failed", exc_info=True)
        snapshot = {"enabled": False, "provider": "", "api_key": None, "model": "",
                    "endpoint": "", "vosk_models": {}, "concurrency": 0}
    _live_snapshot = (now, snapshot)
    return snapshot


def invalidate_snapshot() -> None:
    global _live_snapshot, _analysis_enabled_cache, _data_handling_cache
    _live_snapshot = None
    _analysis_enabled_cache = None
    _data_handling_cache = None


# engines that send audio to somebody else's servers; the others are endpoints
# the operator runs, so audio never leaves their infrastructure
HOSTED_STT = {"deepgram", "mistral"}

_data_handling_cache: tuple[float, dict] | None = None


def data_handling_summary() -> dict:
    """What a participant is told before recording starts: which engine hears
    the audio, whether that engine is somebody else's service, and how long the
    recording is kept. Names and durations only — never keys or endpoints."""
    global _data_handling_cache
    now = time.monotonic()
    if _data_handling_cache is not None and now - _data_handling_cache[0] < _LIVE_SNAPSHOT_TTL:
        return _data_handling_cache[1]
    try:
        store = default_store()
        provider = get_setting(store, "stt_provider")
        analysis_on = get_setting(store, "analysis_enabled") == "1"
        base_url = get_setting(store, "analysis_base_url")
        summary = {
            "stt_provider": provider,
            "stt_configured": bool(store.get_value(f"{provider}_api_key"))
            or provider in ("vosk", "whisper"),
            "stt_hosted": stt_is_hosted(store, provider),
            "analysis_enabled": analysis_on,
            # a self-hosted analysis endpoint keeps transcripts on-premises
            "analysis_hosted": analysis_on and not _is_local_endpoint(base_url),
            "audio_retention_days": int(get_setting(store, "audio_retention_days") or 0),
        }
    except Exception:
        log.warning("data_handling_summary_failed", exc_info=True)
        # say nothing rather than something reassuring and wrong
        summary = {}
    _data_handling_cache = (now, summary)
    return summary


# where scripts/vosk-up.sh mounts the model directory inside the server
VOSK_MODEL_DIR = "/models"


def vosk_model_path(name: str) -> str:
    """Model NAME to a path the server can open.

    Settings holds a name (`vosk-model-small-it-0.22`) so switching model is
    editing one string. A value that already looks like a path is passed
    through, for a server whose models are laid out differently.
    """
    name = (name or "").strip()
    if not name:
        return ""
    return name if name.startswith("/") else f"{VOSK_MODEL_DIR}/{name}"


def vosk_language_models(store: "ConfigStore") -> dict[str, dict[str, str]]:
    """Language code -> {"live": name, "final": name}.

    Never raises: a corrupt value must not stop transcription, it just falls
    back to the server default. The pre-0.6.0-beta.9 format stored one string
    per language; that is still read, meaning both live and final.
    """
    raw = get_setting(store, "vosk_language_models").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        log.warning("vosk_language_models_unparsable")
        return {}
    if not isinstance(parsed, dict):
        return {}
    models: dict[str, dict[str, str]] = {}
    for key, value in parsed.items():
        code = str(key).strip().lower()
        if not code:
            continue
        if isinstance(value, str):  # legacy: one model served both
            live = final = value.strip()
        elif isinstance(value, dict):
            live = str(value.get("live", "")).strip()
            final = str(value.get("final", "")).strip()
        else:
            continue
        # a blank final reuses the live model, so a half-filled row still works
        final = final or live
        live = live or final
        if live or final:
            models[code] = {"live": live, "final": final}
    return models


def vosk_model_for(store: "ConfigStore", language: str, kind: str = "final") -> str:
    """Model path for this session's language, or "" to use the server default.

    `kind` is "live" for provisional captions and "final" for the canonical
    transcript — a fast model can serve one and an accurate one the other.
    `it-IT` and `it` are the same language here: assemblies store a plain code
    today, but a regional one must not silently miss its model.
    """
    models = vosk_language_models(store)
    if not models:
        return ""
    code = (language or "").strip().lower()
    entry = models.get(code) or models.get(code.split("-")[0]) or {}
    return vosk_model_path(entry.get(kind, ""))


def stt_is_hosted(store: "ConfigStore", provider: str) -> bool:
    """Does the audio leave this organisation's infrastructure?

    Derived from the configured *endpoint*, not the engine name: Whisper and
    Vosk are self-hosted in the usual case, but nothing stops an admin pointing
    them at a public server — and the participant-facing notice must not claim
    "stays on our server" when it does not.
    """
    if provider in HOSTED_STT:
        return True
    endpoint_key = LIVE_ENDPOINT_KEYS.get(provider, "")
    if not endpoint_key:
        return True  # unknown engine: assume the answer people should hear
    return not _is_local_endpoint(get_setting(store, endpoint_key))


def _is_local_endpoint(url: str) -> bool:
    """True for addresses that cannot leave the operator's own network."""
    import ipaddress
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    # private-use suffixes; anything else that resolves privately cannot be
    # detected without DNS, and guessing "local" wrongly would tell a table
    # their audio stays in-house when it does not — so we err the other way
    if host == "localhost" or host.endswith((".local", ".internal", ".home.arpa")):
        return True
    # a bare name with no dots is a container/LAN hostname, not a public site
    if "." not in host and ":" not in host:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local


_analysis_enabled_cache: tuple[float, bool] | None = None


def analysis_enabled_cached() -> bool:
    """Cached analysis-enabled flag for hot public endpoints (status polls
    hit this; AppConfig OCS reads are too slow for every poll)."""
    global _analysis_enabled_cache
    now = time.monotonic()
    if _analysis_enabled_cache is not None and now - _analysis_enabled_cache[0] < _LIVE_SNAPSHOT_TTL:
        return _analysis_enabled_cache[1]
    try:
        enabled = get_setting(default_store(), "analysis_enabled") == "1"
    except Exception:
        enabled = True  # assume the stricter completion gate when unreachable
    _analysis_enabled_cache = (now, enabled)
    return enabled

KEY_FIELDS = ("mistral_api_key", "deepgram_api_key", "whisper_api_key", "analysis_api_key")

# targets whose connection test sends a stored API key, so an admin-supplied
# endpoint override must be accompanied by an admin-supplied key (see
# test_connection). Vosk is absent because it authenticates with no key.
KEYED_TEST_TARGETS = ("whisper", "analysis", "mistral", "deepgram")

# where each engine's live captions connect; Deepgram's is configurable so
# servers speaking the same protocol (WhisperLiveKit) can be used instead
LIVE_ENDPOINT_KEYS = {
    "deepgram": "deepgram_live_url",
    "mistral": "mistral_live_url",
    "whisper": "whisper_base_url",
    "vosk": "vosk_url",
}

DEFAULTS = {
    "stt_provider": "mistral",
    "stt_live_enabled": "1",
    "stt_batch_enabled": "1",
    # model IDs verified against provider docs 2026-08-23; live and final
    # (batch) transcription models are configured separately per provider
    "deepgram_live_model": "nova-3",
    "deepgram_batch_model": "nova-3",
    # any server speaking Deepgram's streaming protocol works here
    "deepgram_live_url": "wss://api.deepgram.com/v1/listen",
    "mistral_live_model": "voxtral-mini-transcribe-realtime-2602",
    "mistral_live_url": "wss://api.mistral.ai/v1/audio/transcriptions/realtime",
    "mistral_batch_model": "voxtral-mini-latest",
    # Whisper through any OpenAI-compatible endpoint: hosted OpenAI by default,
    # or a self-hosted server (Speaches, whisper.cpp, LocalAI, vLLM, WhisperX)
    "whisper_base_url": "https://api.openai.com/v1",
    "whisper_batch_model": "whisper-1",
    # captions come from the ordinary endpoint over a sliding window, so the
    # batch model works unless a faster one is set here
    "whisper_live_model": "",
    # Vosk: fully offline, WebSocket protocol, no key
    "vosk_url": "ws://localhost:2700",
    # Vosk needs a separate model per language, but one server can hold several:
    # a JSON map of language code -> model path ON THE SERVER, e.g.
    # {"it": "/models/it", "en": "/models/en"}. A language with no entry uses
    # whichever model the server was started with, so it still transcribes.
    "vosk_language_models": "",
    "vosk_batch_model": "",  # legacy: superseded by vosk_language_models
    "vosk_live_model": "",
    # Server-wide caps on concurrent transcription work, per provider and per
    # kind. Live: every recording phone opens its own caption session, so an
    # uncapped plenary room can saturate a self-hosted Vosk server (or a
    # hosted provider's rate limit), drop every session, and put the whole
    # room into failure cooldown — over-cap phones keep recording and their
    # captions wait for a slot. Batch (final) is a separate pool: the job
    # runner is single-worker today, so these mostly bound what a future
    # concurrent runner could open at once.
    "stt_concurrency_deepgram_live": "10",
    "stt_concurrency_deepgram_batch": "5",
    "stt_concurrency_mistral_live": "15",
    "stt_concurrency_mistral_batch": "5",
    "stt_concurrency_vosk_live": "5",
    "stt_concurrency_vosk_batch": "2",
    "stt_concurrency_whisper_live": "2",
    "stt_concurrency_whisper_batch": "1",
    "analysis_base_url": "https://api.mistral.ai/v1",
    "analysis_model": "mistral-large-latest",
    "analysis_enabled": "1",
    # appended to the built-in analysis prompts (tone, focus areas, glossary);
    # the JSON output contract and evidence rules stay protected
    "analysis_extra_instructions": "",
    # shown with the logo on PDF report headers/footers
    "organization_name": "",
    # days to keep raw audio after an assembly is CLOSED; 0 keeps it
    # indefinitely. Transcripts, findings and reports are never affected — only
    # the recordings. Individual assemblies can override this.
    "audio_retention_days": "0",
}

# reads of the new split keys fall back to the pre-split stored values
LEGACY_KEYS = {
    "deepgram_live_model": "deepgram_model",
    "deepgram_batch_model": "deepgram_model",
    "mistral_batch_model": "mistral_stt_model",
}


class ConfigStore(Protocol):
    def get_value(self, key: str) -> str | None: ...

    def set_value(self, key: str, value: str, sensitive: bool = False) -> None: ...

    def delete_value(self, key: str) -> None: ...


_background_store: "AppConfigStore | None" = None


def default_store() -> "AppConfigStore":
    """Store for non-request contexts (background jobs).

    The client is built once and reused: nc_py_api fetches
    /cloud/capabilities on each new instance, so constructing one per call
    doubled the round-trips on the sweep's hot path.
    """
    global _background_store
    if _background_store is None:
        from nc_py_api import NextcloudApp

        _background_store = AppConfigStore(NextcloudApp())
    return _background_store


class AppConfigStore:
    """Nextcloud AppConfigEx-backed store (values scoped to this ExApp)."""

    def __init__(self, nc):
        self._nc = nc

    def get_value(self, key: str) -> str | None:
        return self._nc.appconfig_ex.get_value(key)

    def set_value(self, key: str, value: str, sensitive: bool = False) -> None:
        self._nc.appconfig_ex.set_value(key, value, sensitive=sensitive)

    def delete_value(self, key: str) -> None:
        self._nc.appconfig_ex.delete(key)


def get_setting(store: ConfigStore, key: str) -> str:
    value = store.get_value(key)
    if (value is None or value == "") and key in LEGACY_KEYS:
        value = store.get_value(LEGACY_KEYS[key])
    if value is None or value == "":
        return DEFAULTS.get(key, "")
    return value


def stt_concurrency_limit(store: "ConfigStore", provider: str, kind: str) -> int:
    """The provider's concurrent-transcription cap for `kind` ("live" or
    "batch"), tolerant of bad input.

    A typo in Settings must degrade to the shipped default, never to zero —
    zero would silently turn captions off for everyone.
    """
    key = f"stt_concurrency_{provider}_{kind}"
    if key not in DEFAULTS:
        return 0  # unknown provider or kind: no cap to speak of
    try:
        value = int(get_setting(store, key))
    except (TypeError, ValueError):
        value = int(DEFAULTS[key])
    return value if value > 0 else int(DEFAULTS[key])


def set_settings(store: ConfigStore, values: dict[str, str]) -> list[str]:
    """Store the provided fields; empty string clears a key field. Returns the
    list of field names changed (for audit — never the values)."""
    changed = []
    for key, value in values.items():
        sensitive = key in KEY_FIELDS
        if sensitive and value == "":
            store.delete_value(key)
        else:
            store.set_value(key, value, sensitive=sensitive)
        changed.append(key)
    return changed


def key_hint(store: ConfigStore, key: str) -> str:
    value = store.get_value(key)
    if not value:
        return ""
    return f"…{value[-4:]}" if len(value) >= 8 else "…"


def providers_summary(store: ConfigStore) -> dict:
    return {
        "organization_name": get_setting(store, "organization_name"),
        "audio_retention_days": int(get_setting(store, "audio_retention_days") or 0),
        "stt": {
            "provider": get_setting(store, "stt_provider"),
            "live_enabled": get_setting(store, "stt_live_enabled") == "1",
            "batch_enabled": get_setting(store, "stt_batch_enabled") == "1",
            "mistral_configured": bool(store.get_value("mistral_api_key")),
            "mistral_key_hint": key_hint(store, "mistral_api_key"),
            "mistral_live_model": get_setting(store, "mistral_live_model"),
            "mistral_batch_model": get_setting(store, "mistral_batch_model"),
            "deepgram_configured": bool(store.get_value("deepgram_api_key")),
            "deepgram_key_hint": key_hint(store, "deepgram_api_key"),
            "deepgram_live_model": get_setting(store, "deepgram_live_model"),
            "deepgram_batch_model": get_setting(store, "deepgram_batch_model"),
            "deepgram_live_url": get_setting(store, "deepgram_live_url"),
            "whisper_configured": bool(store.get_value("whisper_api_key")),
            "whisper_key_hint": key_hint(store, "whisper_api_key"),
            "whisper_base_url": get_setting(store, "whisper_base_url"),
            "whisper_batch_model": get_setting(store, "whisper_batch_model"),
            "whisper_live_model": get_setting(store, "whisper_live_model"),
            "mistral_live_url": get_setting(store, "mistral_live_url"),
            "vosk_url": get_setting(store, "vosk_url"),
            "vosk_language_models": vosk_language_models(store),
            "vosk_batch_model": get_setting(store, "vosk_batch_model"),
            # per-provider caps on concurrent transcription work, live and
            # final (batch) as independent pools, server-wide
            "stt_concurrency_deepgram_live": stt_concurrency_limit(store, "deepgram", "live"),
            "stt_concurrency_deepgram_batch": stt_concurrency_limit(store, "deepgram", "batch"),
            "stt_concurrency_mistral_live": stt_concurrency_limit(store, "mistral", "live"),
            "stt_concurrency_mistral_batch": stt_concurrency_limit(store, "mistral", "batch"),
            "stt_concurrency_vosk_live": stt_concurrency_limit(store, "vosk", "live"),
            "stt_concurrency_vosk_batch": stt_concurrency_limit(store, "vosk", "batch"),
            "stt_concurrency_whisper_live": stt_concurrency_limit(store, "whisper", "live"),
            "stt_concurrency_whisper_batch": stt_concurrency_limit(store, "whisper", "batch"),
        },
        "analysis": {
            "base_url": get_setting(store, "analysis_base_url"),
            "model": get_setting(store, "analysis_model"),
            "configured": bool(store.get_value("analysis_api_key")),
            "key_hint": key_hint(store, "analysis_api_key"),
            "enabled": get_setting(store, "analysis_enabled") == "1",
            "extra_instructions": get_setting(store, "analysis_extra_instructions"),
        },
    }


def test_connection(
    store: ConfigStore,
    target: str,
    override_key: str | None = None,
    override_base_url: str | None = None,
) -> dict:
    """Verify credentials against the provider. `override_key` lets the admin
    test a key typed into the form BEFORE saving it. Never logs or returns
    key material."""
    # A typed-in URL must come with a typed-in key. Otherwise the saved key is
    # sent as a Bearer token to whatever host was named in the request, which
    # would turn this endpoint into a way to read back a key that no API is
    # ever supposed to return.
    if override_base_url and not override_key and target in KEYED_TEST_TARGETS:
        return {
            "ok": False,
            "message": "Enter the API key as well when testing a different endpoint — "
                       "the saved key is never sent to a URL typed into this form",
        }
    try:
        if target == "mistral":
            key = override_key or store.get_value("mistral_api_key")
            if not key:
                return {"ok": False, "message": "No Mistral API key — paste one or save it first"}
            response = httpx.get(
                "https://api.mistral.ai/v1/models",
                headers={"Authorization": f"Bearer {key}"},
                timeout=15,
            )
        elif target == "deepgram":
            key = override_key or store.get_value("deepgram_api_key")
            if not key:
                return {"ok": False, "message": "No Deepgram API key — paste one or save it first"}
            response = httpx.get(
                "https://api.deepgram.com/v1/auth/token",
                headers={"Authorization": f"Token {key}"},
                timeout=15,
            )
        elif target == "whisper":
            from citizens.providers.transcription import whisper as whisper_provider

            base = (override_base_url or get_setting(store, "whisper_base_url")).rstrip("/")
            if not base:
                return {"ok": False, "message": "No Whisper endpoint URL configured"}
            key = override_key or store.get_value("whisper_api_key") or ""
            response = whisper_provider.probe_models(base, key)
            # servers that omit /models (whisper.cpp) still transcribe fine
            if response.status_code == 404:
                return {
                    "ok": True,
                    "message": "Endpoint reachable (no /models listing — that is normal for some servers)",
                }
        elif target == "vosk":
            import asyncio

            from citizens.providers.transcription import vosk as vosk_provider

            url = override_base_url or get_setting(store, "vosk_url")
            if not url:
                return {"ok": False, "message": "No Vosk server URL configured"}
            try:
                asyncio.run(vosk_provider.probe(url))
            except Exception as exc:
                log.warning("provider_test_failed", target=target, error=type(exc).__name__)
                return {"ok": False, "message": f"Could not reach {url}: {type(exc).__name__}"}
            return {"ok": True, "message": "Connected"}
        elif target == "analysis":
            key = override_key or store.get_value("analysis_api_key")
            if not key:
                return {"ok": False, "message": "No analysis API key — paste one or save it first"}
            base = (override_base_url or get_setting(store, "analysis_base_url")).rstrip("/")
            response = httpx.get(
                f"{base}/models", headers={"Authorization": f"Bearer {key}"}, timeout=15
            )
        else:
            return {"ok": False, "message": f"Unknown target {target}"}
    except httpx.HTTPError as exc:
        log.warning("provider_test_failed", target=target, error=type(exc).__name__)
        return {"ok": False, "message": f"Connection failed: {type(exc).__name__}"}

    ok = response.status_code == 200
    log.info("provider_test", target=target, status=response.status_code, ok=ok)
    if ok:
        return {"ok": True, "message": "Connected"}
    if response.status_code in (401, 403):
        return {"ok": False, "message": f"Authentication failed (HTTP {response.status_code})"}
    return {"ok": False, "message": f"Provider returned HTTP {response.status_code}"}
