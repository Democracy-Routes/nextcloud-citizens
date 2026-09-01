# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A ceiling on request bodies, applied before any route sees them.

The recorder routes are public: anyone who can reach the instance can post to
them, with or without a valid bearer token. Starlette accumulates a request
body with no limit of its own, and pydantic validation only runs once the whole
body is already in memory — so a route whose schema caps a list at 200 entries
still buffers however many megabytes were sent first.

This is the outer bound. Individual routes keep their own tighter limits (a
chunk is capped at MAX_CHUNK_BYTES where it is read); this only exists so that
no route, present or future, can be made to buffer an unbounded body.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from citizens.logging_setup import get_logger

log = get_logger(__name__)

# One audio chunk is 5 MB; the branding logo upload arrives base64-encoded at
# roughly 1.4 MB. 6 MB clears both with room to spare and still bounds memory.
MAX_REQUEST_BYTES = 6 * 1024 * 1024


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject an over-large request by its declared Content-Length.

    A client that lies about (or omits) Content-Length is not stopped here —
    that is the job of the streaming cap on the route that reads the body.
    Refusing it at the door costs nothing and handles the honest majority.
    """

    async def dispatch(self, request, call_next):
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_REQUEST_BYTES:
            log.warning(
                "request_body_too_large",
                path=request.url.path,
                declared_bytes=int(declared),
            )
            return JSONResponse({"detail": "Request body too large"}, status_code=413)
        return await call_next(request)
