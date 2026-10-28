# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Signed session cookies for standalone mode.

A cookie carries the account id and the time it was issued, signed with a
key derived from APP_SECRET; nothing is stored server-side, so a restart
keeps everyone signed in and a changed secret signs everyone out. The
account is still looked up on every request (disabled accounts stop at
once), which is one indexed read.

Cross-site request forgery: the cookie is SameSite=Lax and, on top of that,
every unsafe request must carry the `X-Citizens-Client` header. A browser
sends a custom header cross-origin only after a CORS preflight, and this
app answers no preflight, so a form or script on another site cannot ride
the cookie. The organizer app sends the header in both modes (api.ts).
"""

import base64
import hashlib
import hmac
import json
import time
from urllib.parse import urlparse

from fastapi import Request, Response

from citizens.config import get_settings

COOKIE_NAME = "citizens_session"
CLIENT_HEADER = "x-citizens-client"
CLIENT_HEADER_VALUE = "organizer"
_VERSION = 1


def _key() -> bytes:
    secret = get_settings().app_secret
    if not secret:
        raise RuntimeError("APP_SECRET is empty: sessions cannot be signed")
    return hashlib.sha256(b"citizens-session:" + secret.encode("utf-8")).digest()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue(user_id: str, *, now: float | None = None) -> str:
    payload = json.dumps(
        {"v": _VERSION, "u": user_id, "t": int(now if now is not None else time.time())},
        separators=(",", ":"),
    ).encode("utf-8")
    signature = hmac.new(_key(), payload, hashlib.sha256).digest()
    return f"{_b64(payload)}.{_b64(signature)}"


def read(value: str | None, *, now: float | None = None) -> str | None:
    """The account id a cookie names, or None when missing, forged, or
    older than the session lifetime."""
    if not value or "." not in value:
        return None
    try:
        payload_b64, signature_b64 = value.split(".", 1)
        payload = _unb64(payload_b64)
        expected = hmac.new(_key(), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(signature_b64)):
            return None
        data = json.loads(payload)
    except (ValueError, TypeError, RuntimeError):
        return None
    if data.get("v") != _VERSION or not isinstance(data.get("u"), str):
        return None
    issued = data.get("t")
    if not isinstance(issued, int):
        return None
    age = (now if now is not None else time.time()) - issued
    if age < 0 or age > get_settings().citizens_session_days * 86400:
        return None
    return data["u"]


def _secure() -> bool:
    return urlparse(get_settings().citizens_public_url).scheme == "https"


def set_cookie(response: Response, user_id: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        issue(user_id),
        max_age=get_settings().citizens_session_days * 86400,
        httponly=True,
        secure=_secure(),
        samesite="lax",
        path="/",
    )


def clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, secure=_secure(), samesite="lax")


def user_id_from(request: Request) -> str | None:
    return read(request.cookies.get(COOKIE_NAME))


def has_client_header(request: Request) -> bool:
    return request.headers.get(CLIENT_HEADER, "").strip().lower() == CLIENT_HEADER_VALUE
