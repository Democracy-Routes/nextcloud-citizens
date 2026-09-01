# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Nextcloud Citizens ExApp entry point."""

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from nc_py_api import AsyncNextcloudApp
from nc_py_api.ex_app import AppAPIAuthMiddleware, run_app, set_handlers
from starlette.staticfiles import StaticFiles
from structlog.contextvars import bind_contextvars, clear_contextvars

from citizens.api.admin import router as admin_router
from citizens.api.assemblies import router as assemblies_router
from citizens.api.files import router as files_router
from citizens.api.findings import router as findings_router
from citizens.api.limits import BodySizeLimitMiddleware
from citizens.api.public_recorder import router as public_recorder_router
from citizens.api.recorder_page import router as recorder_page_router
from citizens.api.recorders import router as recorders_router
from citizens.api.reports import router as reports_router
from citizens.api.system import router as system_router
from citizens.api.transcripts import router as transcripts_router
from citizens.config import get_settings
from citizens.db.migrate import run_migrations
from citizens.db.session import configure_database, sqlite_url
from citizens.jobs.runner import run_forever as jobs_run_forever
from citizens.logging_setup import get_logger, setup_logging
from citizens.services.audit import record_audit_event_standalone
from citizens.services.live_captions import LIVE_CAPTIONS
from citizens.storage.paths import db_path, ensure_storage_layout

log = get_logger(__name__)


class _RevalidatedStatic(StaticFiles):
    """Static assets that the browser must revalidate.

    AppAPI's proxy stamps `Cache-Control: private, max-age=3600` on any
    non-JSON response that sets none of its own, and the organizer bundle is
    served from a URL that never changes. The result: after every deploy the
    UI could serve the PREVIOUS build for an hour, with no way for the browser
    to know. (The recorder page dodges this by versioning its asset URLs.)

    `no-cache` does not mean "do not cache": the browser keeps the file and
    revalidates, and StaticFiles already sends ETag/Last-Modified, so an
    unchanged bundle costs a 304 instead of 200 KB.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers.setdefault("Cache-Control", "no-cache")
        return response


async def enabled_handler(enabled: bool, nc: AsyncNextcloudApp) -> str:
    try:
        if enabled:
            await nc.ui.top_menu.register("citizens", "Citizens", "img/app.svg")
            await nc.ui.resources.set_script("top_menu", "citizens", "js/citizens-main")
            # NC appends .js/.css to registered resource paths — pass them without extension
            await nc.ui.resources.set_style("top_menu", "citizens", "css/citizens-main")
            record_audit_event_standalone("app_enabled")
            log.info("app_enabled")
        else:
            record_audit_event_standalone("app_disabled")
            log.info("app_disabled")
    except Exception as exc:
        log.error("enabled_handler_failed", enabled=enabled, exc_info=True)
        return str(exc)
    return ""


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    ensure_storage_layout(settings.app_persistent_storage)
    setup_logging(settings)
    # a deployment missing these starts up looking healthy while invite links
    # and at-rest invite encryption are quietly broken — say so loudly
    missing = settings.missing_required()
    if missing and not settings.auth_disabled():
        log.error("missing_required_environment", variables=missing)
    configure_database(sqlite_url(db_path(settings.app_persistent_storage)))
    run_migrations(sqlite_url(db_path(settings.app_persistent_storage)))
    # static dirs are mounted in create_app instead, with cache headers
    set_handlers(app, enabled_handler, map_app_static=False)
    stop_event = asyncio.Event()
    jobs_task = asyncio.create_task(jobs_run_forever(stop_event))
    LIVE_CAPTIONS.set_loop(asyncio.get_running_loop())
    log.info("app_started", version=settings.app_version, storage=str(settings.app_persistent_storage))
    yield
    stop_event.set()
    await LIVE_CAPTIONS.shutdown()
    await jobs_task
    log.info("app_stopping")


def create_app(with_auth: bool = True) -> FastAPI:
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    if with_auth:
        app.add_middleware(AppAPIAuthMiddleware)
    # Added after the auth middleware so it runs BEFORE it: the recorder routes
    # are public, and an over-large body must be refused without first being
    # buffered into memory to be authenticated.
    app.add_middleware(BodySizeLimitMiddleware)

    @app.middleware("http")
    async def request_logging(request: Request, call_next):
        if request.url.path == "/heartbeat":
            return await call_next(request)
        clear_contextvars()
        bind_contextvars(request_id=uuid.uuid4().hex[:12])
        started = time.monotonic()
        response = await call_next(request)
        log.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round((time.monotonic() - started) * 1000, 1),
        )
        return response

    app.include_router(system_router, prefix="/api/v1")
    app.include_router(assemblies_router, prefix="/api/v1")
    app.include_router(recorders_router, prefix="/api/v1")
    app.include_router(public_recorder_router, prefix="/api/v1")
    app.include_router(admin_router, prefix="/api/v1")
    app.include_router(transcripts_router, prefix="/api/v1")
    app.include_router(findings_router, prefix="/api/v1")
    app.include_router(reports_router, prefix="/api/v1")
    app.include_router(files_router, prefix="/api/v1")
    app.include_router(recorder_page_router)

    root = Path(__file__).resolve().parent.parent
    recorder_static = root / "recorder_static"
    if recorder_static.is_dir():
        app.mount(
            "/recorder/static", _RevalidatedStatic(directory=recorder_static),
            name="recorder-static",
        )
    # We mount these ourselves (set_handlers is told map_app_static=False) so
    # they carry a Cache-Control — see _RevalidatedStatic.
    for name in ("js", "css", "img", "l10n"):
        directory = root / name
        if directory.is_dir():
            app.mount(f"/{name}", _RevalidatedStatic(directory=directory), name=name)
    return app


_settings = get_settings()
_auth_disabled = _settings.auth_disabled()
if _settings.citizens_insecure_no_auth and not _auth_disabled:
    # a stray env var must never open up a real deployment
    log.error(
        "insecure_no_auth_ignored",
        reason="CITIZENS_INSECURE_NO_AUTH is only honored against a local Nextcloud",
        nextcloud_url=_settings.nextcloud_url,
    )
elif _auth_disabled:
    log.warning("AUTH DISABLED (CITIZENS_INSECURE_NO_AUTH) — browser-test mode only")
APP = create_app(with_auth=not _auth_disabled)


if __name__ == "__main__":
    run_app("citizens.main:APP", log_level="info")
