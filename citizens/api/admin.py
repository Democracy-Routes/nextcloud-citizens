# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Admin API. Access control is enforced twice: the AppAPI proxy registers
`^api/v1/admin/.*` as ADMIN, and `require_admin` below re-checks group
membership in the app. The proxy alone was a single point of failure for
endpoints that read and write provider API keys — see its docstring.
"""

import base64
import binascii
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from nc_py_api import NextcloudApp
from nc_py_api.ex_app import nc_app
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from citizens.db.session import get_db
from citizens.logging_setup import get_logger
from citizens.security.identity import CurrentUser
from citizens.services import branding, provider_config
from citizens.services.analysis import ROUND_SYSTEM, TABLE_SYSTEM
from citizens.services.audit import record_audit_event

log = get_logger(__name__)

router = APIRouter(prefix="/admin")

DB = Annotated[Session, Depends(get_db)]


def get_config_store(nc: Annotated[NextcloudApp, Depends(nc_app)]) -> provider_config.ConfigStore:
    return provider_config.AppConfigStore(nc)


Store = Annotated[provider_config.ConfigStore, Depends(get_config_store)]


def require_admin(
    nc: Annotated[NextcloudApp, Depends(nc_app)],
    user: CurrentUser,
) -> str:
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
    return user


AdminUser = Annotated[str, Depends(require_admin)]


@router.get("/ping")
def ping(user: AdminUser):
    return {"ok": True, "user": user}


@router.get("/providers")
def get_providers(store: Store, user: AdminUser):
    summary = provider_config.providers_summary(store)
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
    organization_name: str | None = Field(default=None, max_length=200)
    audio_retention_days: int | None = Field(default=None, ge=0, le=3650)


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
    provider_config.invalidate_snapshot()
    # Read the summary back BEFORE the audit row opens the write transaction:
    # providers_summary() is an OCS call to Nextcloud, and holding SQLite's
    # single writer slot across it blocks every phone uploading a chunk.
    summary = provider_config.providers_summary(store)
    record_audit_event(
        session, "providers_updated", actor=user, data={"fields": changed}
    )
    return summary


class TestIn(BaseModel):
    target: Literal["mistral", "deepgram", "whisper", "vosk", "analysis"]
    # lets the admin test what's typed in the form before saving it
    api_key: str | None = Field(default=None, max_length=500)
    base_url: str | None = Field(default=None, max_length=500)


@router.post("/providers/test")
def test_provider(data: TestIn, store: Store, user: AdminUser):
    return provider_config.test_connection(
        store,
        data.target,
        override_key=(data.api_key or "").strip() or None,
        override_base_url=(data.base_url or "").strip() or None,
    )


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
