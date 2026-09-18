# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a provider said when it refused — the parts a person can act on.

`retry_after_seconds` reads the standard header a rate-limiting provider sends
with a 429; `error_detail` pulls the human-readable message out of a JSON error
body (Mistral, Ollama and OpenAI-style endpoints all put one there) or, failing
that, the first line of whatever came back, tags stripped. Neither ever returns
the request that was sent, so no key can leak through them.
"""

import json
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

DETAIL_LIMIT = 300

_MESSAGE_PATHS = (("message",), ("error", "message"), ("detail",), ("error",))


def retry_after_seconds(headers) -> float | None:
    value = headers.get("retry-after") if headers is not None else None
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def error_detail(response, limit: int = DETAIL_LIMIT) -> str:
    try:
        data = response.json()
    except ValueError:
        text = re.sub(r"<[^>]+>", " ", response.text or "")
        return " ".join(text.split())[:limit]
    if isinstance(data, dict):
        for path in _MESSAGE_PATHS:
            value = data
            for key in path:
                value = value.get(key) if isinstance(value, dict) else None
            if isinstance(value, str) and value.strip():
                return value.strip()[:limit]
    try:
        return json.dumps(data)[:limit]
    except (TypeError, ValueError):
        return str(data)[:limit]
