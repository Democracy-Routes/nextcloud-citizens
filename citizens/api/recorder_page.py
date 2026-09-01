# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public recorder page (no Nextcloud chrome; loads the lean recorder bundle).

Served at /recorder.html: the AppAPI proxy injects its CSP nonce into <script>
tags ONLY for paths ending in .html — any other path gets Nextcloud's strict
CSP with no nonce and inline scripts are silently blocked. /recorder and
/recorder/ redirect here so older QR links keep working (the URL fragment
with the invite token survives redirects client-side).

The page computes its own base URL from location.pathname, so it works
through /apps/app_api/proxy/... or a /exapps/ rewrite, and propagates the
injected nonce to the dynamically loaded bundle for browsers without
'strict-dynamic' support.
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse

from citizens.config import get_settings

router = APIRouter()

RECORDER_HTML = """<!DOCTYPE html>
<html lang="">
<head>
<meta charset="utf-8">
<!-- Zoom deliberately NOT blocked: maximum-scale/user-scalable=no is a
     WCAG 1.4.4 failure, and the people most likely to need to enlarge the
     round's question are the ones least likely to work around it. -->
<meta name="viewport" content="width=device-width, initial-scale=1.0, \
viewport-fit=cover">
<meta name="theme-color" content="#f5f6f8">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<title>Citizens — Table Recorder</title>
<style>
  /* app-style shell: the page itself never scrolls or bounces */
  html, body { margin: 0; height: 100%; overflow: hidden; overscroll-behavior: none;
    position: fixed; inset: 0; width: 100%; background: #f5f6f8; color: #222;
    font-family: system-ui, -apple-system, sans-serif; }
  #boot { padding: 40px 20px; text-align: center; color: #666; }
  .boot-spinner {
    width: 28px; height: 28px; margin: 0 auto; border-radius: 50%;
    border: 3px solid #d9dce3; border-top-color: #7a8194;
    animation: boot-spin 0.9s linear infinite;
  }
  @keyframes boot-spin { to { transform: rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) { .boot-spinner { animation: none; } }
</style>
</head>
<body>
<div id="recorder-app"><div id="boot"><div class="boot-spinner"></div></div></div>
<script>
(function () {
  var current = document.currentScript;
  var path = window.location.pathname;
  var idx = path.lastIndexOf('/recorder');
  var base = idx >= 0 ? path.slice(0, idx) : path.replace(/\\/[^\\/]*$/, '');
  window.__CITIZENS_RECORDER_BASE__ = base + '/recorder';
  var s = document.createElement('script');
  if (current && current.nonce) { s.nonce = current.nonce; }
  s.src = base + '/recorder/static/citizens-recorder.js?v=__APP_VERSION__';
  s.onerror = function () {
    // The one string that cannot be translated: if the bundle did not load,
    // neither did the catalogues.
    document.getElementById('boot').textContent =
      'Failed to load the recorder application. Check the connection and reload.';
  };
  document.body.appendChild(s);
  var l = document.createElement('link');
  l.rel = 'stylesheet';
  l.href = base + '/recorder/static/citizens-recorder.css?v=__APP_VERSION__';
  document.head.appendChild(l);
})();
</script>
</body>
</html>"""


# The proxy forwards ExApp response headers, so the page ships its own CSP:
# Nextcloud's own policy for proxied responses is `default-src 'none'` with no
# script allowance whatsoever, which would block the app entirely.
RECORDER_CSP = (
    "default-src 'none'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "media-src 'self' blob:; "
    "frame-ancestors 'none'; "
    "base-uri 'none'"
)


@router.get("/recorder.html")
def recorder_page() -> HTMLResponse:
    # version query busts the proxy/browser asset cache after app updates
    html = RECORDER_HTML.replace("__APP_VERSION__", get_settings().app_version)
    return HTMLResponse(html, headers={"Content-Security-Policy": RECORDER_CSP})


@router.get("/recorder")
def recorder_redirect() -> RedirectResponse:
    # relative Location: from …/citizens/recorder → …/citizens/recorder.html
    return RedirectResponse(url="recorder.html", status_code=302)


@router.get("/recorder/")
def recorder_redirect_slash() -> RedirectResponse:
    # from …/citizens/recorder/ → …/citizens/recorder.html
    return RedirectResponse(url="../recorder.html", status_code=302)
