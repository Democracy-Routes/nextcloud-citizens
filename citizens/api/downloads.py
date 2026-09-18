# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Headers for file downloads.

Every download MUST send Cache-Control, because AppAPI's proxy adds its own
otherwise (ExAppProxyController::buildProxyResponse):

    if ($cache && !$isHTML && empty($response->getHeader('cache-control'))
        && Content-Type is not application/json ...) {
        $proxyResponse->cacheFor(3600);
    }

`cacheFor(3600)` sets `Cache-Control: private, max-age=3600`, so for an hour the
browser serves the file from its own cache without contacting the server. That
is wrong for every download here, and actively dangerous for one:
`/api/v1/public/recorder/report.pdf` is the same URL for every assembly — only
the bearer token distinguishes them, and no cache looks at headers — so a phone
used in two assemblies downloaded the first one's report for the next hour.

JSON is excluded from the proxy's rule, which is why the report *screen* was
right while the PDF was wrong.
"""

import unicodedata
from urllib.parse import quote

NO_STORE = "no-store, no-cache, must-revalidate"


def download_headers(filename: str) -> dict[str, str]:
    """Content-Disposition plus the Cache-Control that stops the proxy caching."""
    clean = "".join(c for c in filename if ord(c) >= 32 and ord(c) != 127)
    clean = clean.replace("/", "_").replace("\\", "_")
    fallback = unicodedata.normalize("NFKD", clean).encode("ascii", "ignore").decode()
    fallback = fallback.replace('"', "_") or "download"
    return {
        "Content-Disposition": (
            f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{quote(clean, safe="")}'
        ),
        "Cache-Control": NO_STORE,
    }
