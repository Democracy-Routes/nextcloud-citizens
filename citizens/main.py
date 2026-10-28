# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Nextcloud Citizens ExApp entry point."""

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from nc_py_api import AsyncNextcloudApp
from nc_py_api.ex_app import AppAPIAuthMiddleware, run_app, set_handlers
from starlette.staticfiles import StaticFiles
from structlog.contextvars import bind_contextvars, clear_contextvars

from citizens.api.admin import router as admin_router
from citizens.api.assemblies import router as assemblies_router
from citizens.api.auth import router as auth_router
from citizens.api.files import router as files_router
from citizens.api.findings import router as findings_router
from citizens.api.limits import BodySizeLimitMiddleware
from citizens.api.organizer_page import router as organizer_page_router
from citizens.api.public_facilitator import router as public_facilitator_router
from citizens.api.public_recorder import router as public_recorder_router
from citizens.api.recorder_page import router as recorder_page_router
from citizens.api.recorders import router as recorders_router
from citizens.api.reports import router as reports_router
from citizens.api.sessions import router as sessions_router
from citizens.api.system import router as system_router
from citizens.api.transcripts import router as transcripts_router
from citizens.api.users import router as users_router
from citizens.config import get_settings
from citizens.db.migrate import run_migrations
from citizens.db.session import configure_database, session_scope, sqlite_url
from citizens.jobs.runner import run_forever as jobs_run_forever
from citizens.logging_setup import get_logger, setup_logging
from citizens.services import accounts, mail, provider_config, vosk_builtin
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


BUNDLE_LOADER = """(function () {
  var me = document.currentScript;
  var base = me && me.src ? me.src.replace(/\\/js\\/citizens-main\\.js(\\?.*)?$/, "") : "";
  var v = encodeURIComponent("__APP_VERSION__");
  var css = document.createElement("link");
  css.rel = "stylesheet";
  css.href = base + "/css/citizens-main.bundle.css?v=" + v;
  document.head.appendChild(css);
  var js = document.createElement("script");
  js.src = base + "/js/citizens-main.bundle.js?v=" + v;
  document.head.appendChild(js);
})();
"""


def _bundle_loader_router() -> APIRouter:
    from fastapi.responses import Response

    router = APIRouter()
    no_cache = {"Cache-Control": "no-cache, no-store, must-revalidate"}

    @router.get("/js/citizens-main.js")
    def organizer_loader() -> Response:
        body = BUNDLE_LOADER.replace("__APP_VERSION__", get_settings().app_version)
        return Response(body, media_type="application/javascript", headers=no_cache)

    @router.get("/css/citizens-main.css")
    def organizer_style_stub() -> Response:
        # the registered stylesheet: the loader injects the real one
        return Response("/* loaded by js/citizens-main.js */\n", media_type="text/css", headers=no_cache)

    return router


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
    mode_problem = settings.mode_problem()
    if mode_problem:
        # not inferred, not corrected: the deployment runs as Nextcloud mode
        # and this line says why nothing works
        log.error("mode_invalid", problem=mode_problem)
    configure_database(sqlite_url(db_path(settings.app_persistent_storage)))
    run_migrations(sqlite_url(db_path(settings.app_persistent_storage)))
    if settings.is_standalone():
        # the first administrator, from the environment, while nobody exists
        try:
            with session_scope() as session:
                accounts.bootstrap_admin(session)
        except Exception:
            log.error("bootstrap_admin_failed", exc_info=True)
        log.info("standalone_mode", public_url=settings.citizens_public_url, mail=mail.configured())
    else:
        # static dirs are mounted in create_app instead, with cache headers
        set_handlers(app, enabled_handler, map_app_static=False)
    # Settings, read once before the first request so no request ever asks
    # Nextcloud for them. Best effort and bounded: a Nextcloud that is not
    # answering yet must not keep the container from becoming healthy — the
    # sweep reads again a minute later.
    if not settings.auth_disabled():
        try:
            await asyncio.wait_for(
                asyncio.to_thread(provider_config.refresh_config_snapshot), timeout=15
            )
        except TimeoutError:
            log.warning("config_snapshot_startup_timeout")
        except Exception:
            log.warning("config_snapshot_startup_failed", exc_info=True)
    # the built-in Vosk engine, when Settings asks for it (memory only; the
    # snapshot above already read the setting)
    try:
        await asyncio.to_thread(vosk_builtin.reconcile)
    except Exception:
        log.warning("vosk_builtin_startup_failed", exc_info=True)
    stop_event = asyncio.Event()
    jobs_task = asyncio.create_task(jobs_run_forever(stop_event))
    LIVE_CAPTIONS.set_loop(asyncio.get_running_loop())
    # Caption sessions used to be reaped only as a side effect of some other
    # table's chunk upload, so a phone that died in the last round of the day
    # was never cleaned up at all: its captions were never written to disk and
    # its provider websocket stayed open until the container restarted.
    reaper_task = asyncio.create_task(LIVE_CAPTIONS.reap_forever(stop_event))
    log.info("app_started", version=settings.app_version, storage=str(settings.app_persistent_storage))
    yield
    stop_event.set()
    await LIVE_CAPTIONS.shutdown()
    vosk_builtin.BUILTIN.stop()
    await jobs_task
    await reaper_task
    log.info("app_stopping")


def create_app(with_auth: bool = True) -> FastAPI:
    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    standalone = get_settings().is_standalone()
    if with_auth and not standalone:
        # standalone mode authenticates per route (security/identity.py):
        # the session cookie, and bearer tokens on the public routes
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
    app.include_router(sessions_router, prefix="/api/v1")
    app.include_router(recorders_router, prefix="/api/v1")
    app.include_router(public_recorder_router, prefix="/api/v1")
    app.include_router(public_facilitator_router, prefix="/api/v1")
    app.include_router(admin_router, prefix="/api/v1")
    app.include_router(transcripts_router, prefix="/api/v1")
    app.include_router(findings_router, prefix="/api/v1")
    app.include_router(reports_router, prefix="/api/v1")
    app.include_router(files_router, prefix="/api/v1")
    # /auth/config and /auth/me answer in both modes; the password routes
    # only in standalone (they 404 otherwise)
    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(recorder_page_router)
    if standalone:
        app.include_router(users_router, prefix="/api/v1")
        app.include_router(organizer_page_router)

        @app.get("/heartbeat", include_in_schema=False)
        def heartbeat() -> dict:
            # what healthcheck.sh asks for; nc_py_api's set_handlers adds
            # the same route in Nextcloud mode
            return {"status": "ok"}

    # The organizer bundle's registered URLs never change (set_script above),
    # and the AppAPI proxy caches non-JSON responses for an hour: after a
    # deploy the browser kept the previous build, and Settings opened blank or
    # old. So the registered paths answer a 300-byte loader that injects the
    # real bundle with the running version in its query — the same trick the
    # recorder page plays — and never ask the browser to keep it.
    app.include_router(_bundle_loader_router())

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
