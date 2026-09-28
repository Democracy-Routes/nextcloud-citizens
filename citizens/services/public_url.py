# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The address the table phones open: Nextcloud's public URL, not ours.

The QR codes used to be built on NEXTCLOUD_URL. On a hand-run deployment that
is whatever the operator typed, and on this project's first server it was the
public address — so it worked. When AppAPI deploys the container itself,
NEXTCLOUD_URL is the address the ADMIN gave the deploy daemon, which is what
the container uses to reach Nextcloud: often an internal name that no phone
can open. AppAPI exposes the instance's `overwrite.cli.url` to ExApps for
exactly this, and that is what is used here, with an explicit override for
installations whose `overwrite.cli.url` is wrong or unset.

Resolution order for the recorder page URL:

1. CITIZENS_PUBLIC_URL, when set: the Nextcloud base the phones must open
   (`https://cloud.example.org`, or `https://example.org/nextcloud`).
2. The last answer from Nextcloud's OCS `info/nextcloud_url/absolute`, which
   is built from `overwrite.cli.url`. Fetched by refresh() — at every sweep
   tick, never inside a request's write transaction — and cached.
3. NEXTCLOUD_URL, as before.

The path is the AppAPI PHP proxy's, which every daemon type serves (with a
HaRP daemon it forwards to /exapps/citizens/); it MUST end in .html so the
proxy injects its CSP nonce into the page.
"""

import threading
from urllib.parse import urlparse

from citizens.config import get_settings
from citizens.logging_setup import get_logger

log = get_logger(__name__)

RECORDER_PATH = "/index.php/apps/app_api/proxy/citizens/recorder.html"
OCS_ABSOLUTE_URL = "/ocs/v1.php/apps/app_api/api/v1/info/nextcloud_url/absolute"

_lock = threading.Lock()
_resolved: str | None = None
_announced: tuple[str, str] | None = None


def _override() -> str:
    """CITIZENS_PUBLIC_URL, if it is an address at all.

    AppAPI turns an empty <default/> in info.xml into the string "Array"
    (its XML-to-array conversion), and that install printed QR codes for
    "Array/index.php/…". Anything that is not an http(s) URL is ignored, and
    said so once in the log.
    """
    raw = get_settings().citizens_public_url.strip().rstrip("/")
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return raw
    _announce("override_ignored", raw[:120])
    return ""


def recorder_page_url() -> str:
    """The recorder page's public URL. Pure read: safe inside a transaction."""
    override = _override()
    if override:
        return override + RECORDER_PATH
    with _lock:
        resolved = _resolved
    if resolved:
        return resolved
    return get_settings().nextcloud_url.rstrip("/") + RECORDER_PATH


def _lookup() -> str:
    """Ask Nextcloud. Split out so tests can stand in for the OCS call."""
    from nc_py_api import NextcloudApp

    data = NextcloudApp().ocs("GET", OCS_ABSOLUTE_URL, params={"url": RECORDER_PATH})
    if isinstance(data, dict):
        return str(data.get("absolute_url") or "")
    return ""


def refresh() -> str:
    """Re-read the public address from Nextcloud and cache it.

    Called by the sweep loop (outside any transaction) and safe to call when
    Nextcloud is unreachable: a failure keeps the previous answer. Returns
    the URL now in effect.
    """
    global _resolved
    settings = get_settings()
    if _override():
        _announce("CITIZENS_PUBLIC_URL", recorder_page_url())
        return recorder_page_url()
    if settings.missing_required() or settings.auth_disabled():
        # no way to sign an OCS request, or nothing real to ask
        return recorder_page_url()
    try:
        answer = _lookup()
    except Exception as exc:
        _announce("lookup_failed", str(exc)[:200])
        return recorder_page_url()
    parsed = urlparse(answer)
    with _lock:
        if parsed.scheme in ("http", "https") and parsed.netloc:
            _resolved = answer
            source = "overwrite.cli.url"
        else:
            # overwrite.cli.url is unset: Nextcloud answered with a relative path
            _resolved = None
            source = "NEXTCLOUD_URL"
    _announce(source, recorder_page_url())
    return recorder_page_url()


def reset() -> None:
    """Forget the cached answer (tests)."""
    global _resolved, _announced
    with _lock:
        _resolved = None
        _announced = None


def _announce(source: str, value: str) -> None:
    """One log line per change, not one per minute."""
    global _announced
    if _announced == (source, value):
        return
    _announced = (source, value)
    if source == "lookup_failed":
        log.warning("public_url_lookup_failed", error=value, using=recorder_page_url())
    elif source == "override_ignored":
        log.warning("public_url_override_ignored", value=value, reason="not an http(s) URL")
    else:
        log.info("public_url_resolved", source=source, url=value)
