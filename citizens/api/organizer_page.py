# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The organizer page of standalone mode: served at `/`.

In Nextcloud mode there is no page of ours — the bundle is registered with
Nextcloud and runs inside its page. Standalone has nobody else to host it,
so this is the shell: a mount point, the stylesheet and the bundle with the
running version in the query (the same cache-busting the recorder page
does), and a content security policy of its own. Never cached: the version
query inside it is what changes at every deploy.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from citizens.config import get_settings

router = APIRouter()

SUPPORTED = ("en", "it", "de", "fr", "es")

ORGANIZER_HTML = """<!doctype html>
<html lang="__LANG__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="same-origin">
<title>Citizens</title>
<link rel="icon" href="/img/app.svg" type="image/svg+xml">
<link rel="stylesheet" href="/css/citizens-main.css?v=__APP_VERSION__">
<style>
  html, body { margin: 0; min-height: 100%; background: #f5f6f8; color: #222;
    font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
  #content { min-height: 100vh; }
</style>
</head>
<body>
<div id="content"></div>
<script src="/js/citizens-main.bundle.js?v=__APP_VERSION__"></script>
</body>
</html>"""

ORGANIZER_CSP = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "media-src 'self' blob:; "
    "frame-ancestors 'none'; "
    "base-uri 'none'; "
    "form-action 'self'"
)


def page_language(accept_language: str) -> str:
    """The first language of the browser's list we have a catalogue for;
    the account's own language takes over after sign-in (main.ts)."""
    for part in (accept_language or "").split(","):
        base = part.split(";")[0].strip().lower().split("-")[0]
        if base in SUPPORTED:
            return base
    return "en"


@router.get("/", include_in_schema=False)
@router.get("/index.html", include_in_schema=False)
def organizer_page(request: Request) -> HTMLResponse:
    html = ORGANIZER_HTML.replace("__APP_VERSION__", get_settings().app_version).replace(
        "__LANG__", page_language(request.headers.get("accept-language", ""))
    )
    return HTMLResponse(
        html,
        headers={
            "Content-Security-Policy": ORGANIZER_CSP,
            "Cache-Control": "no-store",
            "Referrer-Policy": "same-origin",
            "X-Content-Type-Options": "nosniff",
        },
    )
