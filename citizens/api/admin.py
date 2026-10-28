# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Admin API. Access control is enforced twice: the AppAPI proxy registers
`^api/v1/admin/.*` as ADMIN, and `require_admin` below re-checks group
membership in the app. The proxy alone was a single point of failure for
endpoints that read and write provider API keys — see its docstring.
"""

import base64
import binascii
import time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from citizens.config import get_settings
from citizens.db.session import get_db
from citizens.logging_setup import get_logger
from citizens.security.identity import CurrentUser
from citizens.services import branding, provider_config
from citizens.services.analysis import ROUND_SYSTEM, TABLE_SYSTEM
from citizens.services.audit import record_audit_event

log = get_logger(__name__)

router = APIRouter(prefix="/admin")

DB = Annotated[Session, Depends(get_db, scope="function")]


def get_nc(request: Request):
    """The requesting user's Nextcloud client in Nextcloud mode; None in
    standalone mode, where there is no Nextcloud to talk to. A dependency so
    tests can stand in a fake for it."""
    if get_settings().is_standalone():
        return None
    from nc_py_api.ex_app import nc_app

    return nc_app(request)


NcClient = Annotated[object, Depends(get_nc)]


def get_config_store(nc: NcClient) -> provider_config.ConfigStore:
    """Nextcloud mode: this user's app-config client. Standalone: the one
    SQLite store (services/config_store.py)."""
    if nc is None:
        return provider_config.default_store()
    return provider_config.AppConfigStore(nc)


Store = Annotated[provider_config.ConfigStore, Depends(get_config_store)]


def require_admin(nc: NcClient, user: CurrentUser) -> str:
    """Defence in depth for the routes that read and write provider API keys.

    The proxy already restricts these paths to administrators, but that rests
    on a single regex in appinfo/info.xml — and on AppAPI 33+ the bare-path form
    we register matches only through a compatibility fallback upstream has
    marked for removal. If the route table ever drifts, these endpoints would
    fall through to the USER catch-all with no other guard in the way.

    Fails closed: if group membership cannot be checked, the request is
    refused rather than allowed.

    Use OCS `cloud/user` — the *current* user's own record — not the
    provisioning API. `nc.users.get_user(...)` returns 401 for an ExApp, which
    is not permitted to read arbitrary users, so a check built on it fails
    closed for everyone and silently removes Settings from real admins.
    `nc_app` already binds this client to the requesting user.
    """
    if nc is None:
        # standalone mode: the account's role, no Nextcloud involved
        from citizens.security import standalone_auth

        return standalone_auth.require_admin(user)
    if _admin_until.get(user, 0.0) > time.monotonic():
        return user
    try:
        groups = nc.ocs("GET", "/ocs/v1.php/cloud/user").get("groups") or []
    except Exception:
        log.warning("admin_check_unavailable", exc_info=True)
        raise HTTPException(
            status_code=503, detail="Could not verify administrator rights"
        ) from None
    if "admin" not in groups:
        log.warning("admin_route_refused", user=user)
        raise HTTPException(status_code=403, detail="Administrator rights are required")
    _admin_until[user] = time.monotonic() + ADMIN_CHECK_TTL_SECONDS
    return user


#: a positive admin check is remembered this long: the OCS call behind it
#: cost about a second on every Settings request. A refusal is never cached.
ADMIN_CHECK_TTL_SECONDS = 300
_admin_until: dict[str, float] = {}

AdminUser = Annotated[str, Depends(require_admin)]


@router.get("/ping")
def ping(user: AdminUser):
    return {"ok": True, "user": user}


@router.get("/providers")
def get_providers(store: Store, user: AdminUser):
    # from the snapshot: opening Settings no longer asks Nextcloud for every
    # field one call at a time (see provider_config.settings_summary)
    summary = provider_config.settings_summary(store)
    # shown read-only in Settings so admins see what their extra
    # instructions are appended to
    summary["analysis"]["default_prompts"] = {
        "table": TABLE_SYSTEM,
        "round": ROUND_SYSTEM,
    }
    summary["logo_set"] = branding.logo_path() is not None
    return summary


class ProvidersUpdate(BaseModel):
    stt_provider: Literal["mistral", "deepgram", "whisper", "vosk"] | None = None
    # "builtin": the engine runs in this container with the models Settings
    # installed; "server": the websocket server at vosk_url
    vosk_mode: Literal["builtin", "server"] | None = None
    stt_live_enabled: bool | None = None
    stt_batch_enabled: bool | None = None
    mistral_api_key: str | None = Field(default=None, max_length=500)
    mistral_live_model: str | None = Field(default=None, max_length=100)
    mistral_batch_model: str | None = Field(default=None, max_length=100)
    deepgram_api_key: str | None = Field(default=None, max_length=500)
    deepgram_live_model: str | None = Field(default=None, max_length=100)
    deepgram_batch_model: str | None = Field(default=None, max_length=100)
    deepgram_live_url: str | None = Field(default=None, max_length=500)
    whisper_api_key: str | None = Field(default=None, max_length=500)
    whisper_base_url: str | None = Field(default=None, max_length=500)
    whisper_batch_model: str | None = Field(default=None, max_length=100)
    whisper_live_model: str | None = Field(default=None, max_length=100)
    mistral_live_url: str | None = Field(default=None, max_length=500)
    vosk_url: str | None = Field(default=None, max_length=500)
    # JSON map of language code -> model path on the Vosk server
    vosk_language_models: str | None = Field(default=None, max_length=2000)
    vosk_batch_model: str | None = Field(default=None, max_length=100)
    # per-provider caps on concurrent transcription work — live captions and
    # final (batch) as independent pools, server-wide; ge=1 because 0 would
    # silently disable captions for everyone — turning them off has its own
    # switch
    stt_concurrency_deepgram_live: int | None = Field(default=None, ge=1, le=100)
    stt_concurrency_deepgram_batch: int | None = Field(default=None, ge=1, le=100)
    stt_concurrency_mistral_live: int | None = Field(default=None, ge=1, le=100)
    stt_concurrency_mistral_batch: int | None = Field(default=None, ge=1, le=100)
    stt_concurrency_vosk_live: int | None = Field(default=None, ge=1, le=100)
    stt_concurrency_vosk_batch: int | None = Field(default=None, ge=1, le=100)
    stt_concurrency_whisper_live: int | None = Field(default=None, ge=1, le=100)
    stt_concurrency_whisper_batch: int | None = Field(default=None, ge=1, le=100)
    analysis_base_url: str | None = Field(default=None, max_length=500)
    analysis_model: str | None = Field(default=None, max_length=200)
    analysis_api_key: str | None = Field(default=None, max_length=500)
    analysis_enabled: bool | None = None
    analysis_extra_instructions: str | None = Field(default=None, max_length=4000)
    # the AI facilitator: its instance default level, its own model (blank
    # falls back to the analysis model), and the thresholds behind its nudges
    facilitator_level: Literal["off", "light", "normal", "active"] | None = None
    facilitator_base_url: str | None = Field(default=None, max_length=500)
    facilitator_model: str | None = Field(default=None, max_length=200)
    facilitator_api_key: str | None = Field(default=None, max_length=500)
    facilitator_interval_minutes: int | None = Field(default=None, ge=1, le=60)
    facilitator_dominance_percent: int | None = Field(default=None, ge=40, le=95)
    facilitator_silence_seconds: int | None = Field(default=None, ge=20, le=600)
    organization_name: str | None = Field(default=None, max_length=200)
    audio_retention_days: int | None = Field(default=None, ge=0, le=3650)
    consent_controller: str | None = Field(default=None, max_length=200)
    consent_contact: str | None = Field(default=None, max_length=300)
    org_address: str | None = Field(default=None, max_length=300)
    org_dpo: str | None = Field(default=None, max_length=300)
    org_hosting: str | None = Field(default=None, max_length=300)
    org_authority: str | None = Field(default=None, max_length=300)


# provider endpoints are used for outbound requests from inside the Nextcloud
# network — and the Whisper one receives the actual recording — so restrict them
# to real transport schemes rather than accepting any string
_URL_FIELDS = {
    "whisper_base_url": ("http", "https"),
    "analysis_base_url": ("http", "https"),
    "deepgram_live_url": ("ws", "wss"),
    "mistral_live_url": ("ws", "wss"),
    "vosk_url": ("ws", "wss"),
}


def _validate_endpoints(values: dict[str, str]) -> None:
    from urllib.parse import urlparse

    for field, schemes in _URL_FIELDS.items():
        raw = values.get(field)
        if not raw:
            continue
        parsed = urlparse(raw)
        if parsed.scheme not in schemes or not parsed.hostname:
            raise HTTPException(
                status_code=422,
                detail=f"{field} must be a {' or '.join(s + '://' for s in schemes)} URL",
            )


@router.put("/providers")
def update_providers(data: ProvidersUpdate, store: Store, user: AdminUser, session: DB):
    values: dict[str, str] = {}
    for field, value in data.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        if isinstance(value, bool):
            values[field] = "1" if value else "0"
        elif isinstance(value, int):
            values[field] = str(value)
        else:
            values[field] = value.strip() if field in provider_config.KEY_FIELDS else value
    _validate_endpoints(values)
    changed = provider_config.set_settings(store, values)
    # One read pass: the snapshot refresh the phones need and the Settings
    # summary this response returns are built together — BEFORE the audit row
    # opens the write transaction, since every read is an OCS call to
    # Nextcloud and holding SQLite's single writer slot across them blocks
    # every phone uploading a chunk. Nothing changed: nothing to re-read.
    if changed:
        if id(store) == id(provider_config.default_store()):
            summary = provider_config.refresh_config_snapshot(with_summary=True).summary
        else:
            provider_config.invalidate_snapshot()
            summary = provider_config.providers_summary(store)
    else:
        summary = provider_config.settings_summary(store)
    record_audit_event(
        session, "providers_updated", actor=user, data={"fields": changed}
    )
    if "vosk_mode" in changed:
        # the engine follows the setting at once, not at the next sweep
        from citizens.services import vosk_builtin

        vosk_builtin.reconcile()
    return summary


@router.get("/about")
def about(user: AdminUser, session: DB):
    """What the About tab of Settings shows: the running version and schema,
    the transcription engine's state, storage and the job queue. Opened by
    a person, never polled — so it may do a little work."""
    import shutil

    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import func, select

    from citizens.config import get_settings
    from citizens.db.models import AppJob
    from citizens.jobs import sweep
    from citizens.services.vosk_builtin import BUILTIN
    from citizens.storage.paths import temp_dir

    settings = get_settings()
    snapshot = provider_config.config_snapshot()

    counts = {state: 0 for state in ("QUEUED", "RUNNING", "RETRY", "FAILED")}
    for state, n in session.execute(
        select(AppJob.state, func.count()).group_by(AppJob.state)
    ).all():
        if state in counts:
            counts[state] = n
    newest_failure = session.execute(
        select(AppJob).where(AppJob.state == "FAILED").order_by(AppJob.updated_at.desc()).limit(1)
    ).scalar_one_or_none()

    # on the request's own connection: a second one would wait for this
    # session's lock (SQLite) and the About tab would open with a blank
    try:
        schema_revision = MigrationContext.configure(session.connection()).get_current_revision()
    except Exception:
        log.warning("about_schema_revision_unavailable", exc_info=True)
        schema_revision = None

    try:
        disk_free_gb = round(shutil.disk_usage(settings.app_persistent_storage).free / 1024**3, 1)
    except OSError:
        disk_free_gb = None
    storage_ok = temp_dir(settings.app_persistent_storage).is_dir()

    return {
        "version": settings.app_version,
        "schema_revision": schema_revision,
        "stt_provider": snapshot.live_stt.get("provider"),
        "vosk_mode": "builtin" if snapshot.vosk_builtin else "server",
        "engine": BUILTIN.status(),
        "disk_free_gb": disk_free_gb,
        "storage_ok": storage_ok,
        "jobs": {
            "queued": counts["QUEUED"],
            "running": counts["RUNNING"],
            "retry": counts["RETRY"],
            "failed": counts["FAILED"],
            "newest_failure": None
            if newest_failure is None
            else {
                "type": newest_failure.type,
                "last_error": newest_failure.last_error,
                "updated_at": newest_failure.updated_at.isoformat()
                if newest_failure.updated_at is not None
                else None,
            },
        },
        "last_sweep_at": sweep.LAST_SWEEP_AT.isoformat() if sweep.LAST_SWEEP_AT else None,
    }


@router.get("/vosk/models")
def vosk_models_overview(user: AdminUser):
    """Installed and available speech models for the built-in engine, with
    install progress and the engine's state (services/vosk_models.py)."""
    from citizens.services import vosk_models

    return vosk_models.overview()


@router.post("/vosk/models/{name}/install", status_code=202)
def vosk_model_install(name: str, user: AdminUser, session: DB):
    from citizens.services import vosk_models

    return vosk_models.request_install(session, name, actor=user)


@router.post("/vosk/models/{name}/cancel")
def vosk_model_cancel(name: str, user: AdminUser):
    from citizens.services import vosk_models

    return vosk_models.cancel_install(name)


@router.delete("/vosk/models/{name}")
def vosk_model_remove(name: str, user: AdminUser, session: DB):
    from citizens.services import vosk_models

    return vosk_models.remove(session, name, actor=user)


class TestIn(BaseModel):
    target: Literal["mistral", "deepgram", "whisper", "vosk", "analysis", "facilitator"]
    # lets the admin test what's typed in the form before saving it
    api_key: str | None = Field(default=None, max_length=500)
    base_url: str | None = Field(default=None, max_length=500)
    # the analysis model typed into the form — the test asked the saved one
    model: str | None = Field(default=None, max_length=200)


@router.post("/providers/test")
def test_provider(data: TestIn, store: Store, user: AdminUser):
    return provider_config.test_connection(
        store,
        data.target,
        override_key=(data.api_key or "").strip() or None,
        override_base_url=(data.base_url or "").strip() or None,
        override_model=(data.model or "").strip() or None,
    )


@router.post("/facilitator/tick")
def facilitator_tick(user: AdminUser):
    """Run the AI facilitator's minute now (it runs by itself from the sweep):
    for a rehearsal or a smoke test that cannot wait for the clock."""
    from citizens.services import facilitator

    return {"delivered": facilitator.tick()}


class LogoIn(BaseModel):
    # base64 rather than multipart: small payload, simpler through the proxy
    data: str = Field(max_length=1_400_000)


@router.put("/logo", status_code=204)
def upload_logo(data: LogoIn, user: AdminUser, session: DB):
    try:
        raw = base64.b64decode(data.data, validate=True)
        branding.save_logo(raw)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record_audit_event(session, "logo_updated", actor=user, data={"bytes": len(raw)})


@router.get("/logo")
def get_logo(user: AdminUser):
    path = branding.logo_path()
    if path is None:
        raise HTTPException(status_code=404, detail="No logo uploaded")
    media = "image/png" if path.suffix == ".png" else "image/jpeg"
    return Response(path.read_bytes(), media_type=media)


@router.delete("/logo", status_code=204)
def delete_logo(user: AdminUser, session: DB):
    if branding.delete_logo():
        record_audit_event(session, "logo_deleted", actor=user, data={})
