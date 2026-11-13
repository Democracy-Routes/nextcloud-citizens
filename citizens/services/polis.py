# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The bridge to a Polis instance: the approved statements of an assembly
become the seed comments of a Polis conversation.

One call, `POST /api/v3/citizens/import` on the Polis side (the fork at
Citizens-Polis, see its docs/citizens-integration.md), takes the very file
the export writes plus a topic and a description, creates the conversation
the first time and returns its ids and links. It is idempotent on the
assembly name: sending again adds only the statements whose text is new.

Only statement text leaves Citizens: no evidence, no names, no table
numbers, no participant data. Polis refuses the whole call when a statement
looks like it carries personal data, and says which positions.

Network work runs in the PUSH_POLIS job (jobs/handlers.py), never under a
request or inside a database transaction.
"""

import json
import re
from datetime import datetime

import httpx
from sqlalchemy.orm import Session

from citizens.db.models import Assembly
from citizens.db.models.base import utcnow
from citizens.logging_setup import get_logger
from citizens.providers.http_detail import error_detail, retry_after_seconds
from citizens.services import provider_config
from citizens.services import seeds as seeds_svc

log = get_logger(__name__)

IMPORT_PATH = "/api/v3/citizens/import"
PING_PATH = "/api/v3/citizens/ping"
TIMEOUT = httpx.Timeout(120, connect=30)


class PolisError(Exception):
    """`permanent`: retrying would not help (bad key, refused content).
    `positions`: the export positions Polis refused for personal data."""

    def __init__(
        self,
        message: str,
        permanent: bool = False,
        status: int | None = None,
        retry_after: float | None = None,
        positions: list[int] | None = None,
    ):
        super().__init__(message)
        self.permanent = permanent
        self.status = status
        self.retry_after = retry_after
        self.positions = positions or []


def _headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}", "Accept": "application/json"}


def ping(base_url: str, key: str) -> dict:
    """The Settings test: {ok, message}, never the key."""
    try:
        response = httpx.get(f"{base_url.rstrip('/')}{PING_PATH}", headers=_headers(key), timeout=15)
    except httpx.HTTPError as exc:
        log.warning("polis_ping_failed", error=type(exc).__name__)
        return {"ok": False, "message": f"Could not reach the Polis instance: {type(exc).__name__}"}
    if response.status_code == 200:
        try:
            owner = response.json().get("owner_email") or ""
        except ValueError:
            owner = ""
        return {"ok": True, "message": f"Connected — key of {owner}" if owner else "Connected"}
    if response.status_code in (401, 403):
        return {"ok": False, "message": f"Polis rejected the API key (HTTP {response.status_code})"}
    if response.status_code == 404:
        return {
            "ok": False,
            "message": "This Polis instance has no Citizens endpoint (HTTP 404) — "
                       "it needs the Citizens-Polis fork",
        }
    return {"ok": False, "message": f"Polis returned HTTP {response.status_code}: {error_detail(response)}"}


def _positions(details) -> list[int]:
    found: list[int] = []
    for item in details if isinstance(details, list) else []:
        value = item.get("position") if isinstance(item, dict) else item
        try:
            found.append(int(value))
        except (TypeError, ValueError):
            continue
    return sorted(set(found))


def _refusal(response: httpx.Response) -> PolisError:
    status = response.status_code
    try:
        body = response.json()
    except ValueError:
        body = {}
    code = body.get("error") if isinstance(body, dict) else ""
    details = body.get("details") if isinstance(body, dict) else None
    if status == 400 and code == "polis_err_citizens_import_personal_data":
        positions = _positions(details)
        listed = ", ".join(str(p) for p in positions) or "unknown"
        return PolisError(
            f"Polis refused {len(positions) or 'some'} statement(s) that look like personal data "
            f"(positions {listed}) — edit them and send again",
            permanent=True, status=status, positions=positions,
        )
    if status == 400:
        reasons = "; ".join(
            f"{d.get('field')}: {d.get('reason')}" for d in (details or []) if isinstance(d, dict)
        )[:300]
        return PolisError(f"Polis rejected the statements ({code or 'HTTP 400'}): {reasons}",
                          permanent=True, status=status)
    detail = error_detail(response)
    if status in (401, 403):
        return PolisError(
            f"Polis rejected the API key (HTTP {status}): {detail}", permanent=True, status=status
        )
    if status == 404:
        return PolisError(
            "This Polis instance has no Citizens endpoint (HTTP 404)", permanent=True, status=status
        )
    if status == 429:
        return PolisError(f"Polis is rate limiting imports (HTTP 429): {detail}", status=status,
                          retry_after=retry_after_seconds(response.headers))
    return PolisError(f"Polis returned HTTP {status}: {detail}", status=status)


def push(session: Session, store: provider_config.ConfigStore, assembly: Assembly) -> dict:
    """Send the approved statements; record the conversation and each
    statement's Polis id. The caller commits before this runs (the config
    read and the network call must not hold the writer slot)."""
    base, key = provider_config.polis_config(store)
    if not base or not key:
        raise PolisError("Polis is not configured — add the instance URL and API key in Settings",
                         permanent=True)
    rows = seeds_svc.list_seeds(session, assembly.id)
    chosen = seeds_svc.exportable(rows)
    if not chosen:
        raise PolisError("No approved statements to send", permanent=True)
    # commit before the network call: the rows above were only read
    session.commit()
    now = utcnow()
    body = json.loads(seeds_svc.render_json(assembly, chosen, now))
    body["topic"] = assembly.name
    body["description"] = (assembly.description or "")[:2000]
    log.info("polis_push_started", assembly_id=assembly.id, statements=len(chosen))
    try:
        response = httpx.post(f"{base}{IMPORT_PATH}", headers=_headers(key), json=body, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        raise PolisError(f"Could not reach the Polis instance: {type(exc).__name__}") from exc
    if response.status_code != 200:
        raise _refusal(response)
    try:
        data = response.json()
        conversation_id = str(data["conversation_id"])
    except (ValueError, KeyError, TypeError) as exc:
        raise PolisError("Polis returned an unexpected payload", permanent=True) from exc

    assembly.polis_conversation_id = conversation_id
    assembly.polis_url = str(data.get("url") or "")[:500] or None
    assembly.polis_moderation_url = str(data.get("moderation_url") or "")[:500] or None
    assembly.polis_report_url = str(data.get("report_url") or "")[:500] or None
    assembly.polis_pushed_at = now
    by_position = {number: seed for number, seed in enumerate(chosen, start=1)}
    results = (data.get("statements") or {}).get("results") or []
    for item in results:
        if not isinstance(item, dict):
            continue
        seed = by_position.get(item.get("position"))
        if seed is None:
            continue
        seed.polis_conversation_id = conversation_id
        if item.get("status") == "success" and item.get("tid") is not None:
            seed.polis_tid = int(item["tid"])
    seeds_svc.mark_exported(chosen, now)
    counts = data.get("statements") or {}
    summary = {
        "conversation_id": conversation_id,
        "created": bool(data.get("created")),
        "added": int(counts.get("added") or 0),
        "skipped_duplicate": int(counts.get("skipped_duplicate") or 0),
        "failed": int(counts.get("failed") or 0),
    }
    log.info("polis_push_completed", assembly_id=assembly.id, **summary)
    return summary


_POSITIONS_IN_MESSAGE = re.compile(r"positions ([0-9, ]+)")


def refused_positions(failure_detail: str | None) -> list[int]:
    """The positions named by a personal-data refusal, back out of the job's
    failure text (the job row is the only place the refusal is kept)."""
    if not failure_detail or "personal data" not in failure_detail:
        return []
    match = _POSITIONS_IN_MESSAGE.search(failure_detail)
    if not match:
        return []
    return [int(p) for p in match.group(1).replace(" ", "").split(",") if p.isdigit()]


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
