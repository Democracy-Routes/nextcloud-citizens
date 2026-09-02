# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Development/test helpers.

    python -m citizens.devtools seed-recorder-test      one assembly, table-1 invite
    python -m citizens.devtools seed-load-test [N]      one assembly, N tables, N invites
    python -m citizens.devtools api METHOD PATH [JSON]  call an organizer route

The first is for browser tests. The second backs tests/load/load_g_single_assembly.py:
every table lives in the SAME assembly, which is what a real room looks like and
what calling seed-recorder-test N times does not produce.

`api` exists because organizer routes cannot be reached over HTTP from a browser
test. Disabling the AppAPI middleware does not make them open: nc_py_api falls
back to checking the request signature inline, so every organizer call needs a
real Nextcloud signature. Rather than weaken that, a browser test asks the
container to make the call for it — through the real router, with the identity
stubbed exactly as tests/conftest.py does.
"""

import json
import sys

from citizens.config import get_settings
from citizens.db.migrate import run_migrations
from citizens.db.models import Assembly, RecorderInvite, Round, Table
from citizens.db.session import configure_database, session_scope, sqlite_url
from citizens.security.recorder_tokens import generate_token, hash_token
from citizens.storage.paths import db_path, ensure_storage_layout


def seed_recorder_test() -> dict:
    settings = get_settings()
    ensure_storage_layout(settings.app_persistent_storage)
    url = sqlite_url(db_path(settings.app_persistent_storage))
    configure_database(url)
    run_migrations(url)

    with session_scope() as session:
        assembly = Assembly(
            name="TEST Browser Assembly",
            created_by="browser-test",
            expected_participants=10,
            default_table_count=2,
        )
        round_ = Round(position=1, title="TEST Round", question="Browser test?",
                       duration_minutes=30, status="ACTIVE")
        round_.tables = [Table(number=1), Table(number=2)]
        assembly.rounds.append(round_)
        token = generate_token()
        assembly.invites.append(RecorderInvite(table_number=1, token_hash=hash_token(token)))
        session.add(assembly)
        session.flush()
        return {"assembly_id": assembly.id, "round_id": round_.id, "token": token}


def seed_load_test(tables: int = 10) -> dict:
    """One assembly, one round, `tables` tables, one invite each.

    Ten devices in ten assemblies contend for nothing: separate rows, separate
    aggregation, separate everything. Ten devices in ONE assembly is the case a
    venue actually produces, and the only one that puts the writer lock, the
    per-assembly aggregation and the completion burst under simultaneous load.
    """
    settings = get_settings()
    ensure_storage_layout(settings.app_persistent_storage)
    url = sqlite_url(db_path(settings.app_persistent_storage))
    configure_database(url)
    run_migrations(url)

    with session_scope() as session:
        assembly = Assembly(
            name=f"TEST Load {tables} tables",
            created_by="load-test",
            expected_participants=tables * 6,
            default_table_count=tables,
        )
        round_ = Round(position=1, title="TEST Round", question="Load test?",
                       duration_minutes=30, status="ACTIVE")
        round_.tables = [Table(number=n) for n in range(1, tables + 1)]
        assembly.rounds.append(round_)
        seeds = []
        for number in range(1, tables + 1):
            token = generate_token()
            assembly.invites.append(
                RecorderInvite(table_number=number, token_hash=hash_token(token))
            )
            seeds.append({"table_number": number, "token": token})
        session.add(assembly)
        session.flush()
        return {"assembly_id": assembly.id, "round_id": round_.id, "tables": seeds}


#: marks the one line of `api` output that is the result
API_RESULT_PREFIX = "CITIZENS_API_RESULT:"


def call_api(
    method: str, path: str, body: str | None = None, user: str = "browser-test"
) -> dict:
    """Make an organizer API call from inside the container.

    Goes through the real FastAPI app — real routing, real handlers, real
    database — with only the Nextcloud identity replaced.

    The user defaults to the one seed_recorder_test() owns its assembly as;
    organizer routes 404 rather than 403 for somebody else's assembly, so a
    mismatch here looks like a missing round.
    """
    from fastapi import Request
    from fastapi.testclient import TestClient

    from citizens.main import create_app
    from citizens.security.identity import get_current_user_id

    app = create_app(with_auth=False)

    # annotated, not a lambda: FastAPI reads the signature, and an unannotated
    # parameter becomes a required query parameter rather than the request
    def fake_user(request: Request) -> str:
        return request.headers.get("x-test-user", user)

    app.dependency_overrides[get_current_user_id] = fake_user
    with TestClient(app) as client:
        response = client.request(
            method.upper(), path, json=json.loads(body) if body else None
        )
    try:
        payload = response.json()
    except ValueError:
        payload = {"text": response.text}
    return {"status": response.status_code, "body": payload}


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "seed-recorder-test":
        print(json.dumps(seed_recorder_test()))
    elif command == "seed-load-test":
        print(json.dumps(seed_load_test(int(sys.argv[2]) if len(sys.argv) > 2 else 10)))
    elif command == "api":
        # Prefixed: creating the app configures structlog, which also writes
        # JSON to stdout, so the caller needs an unambiguous line to parse.
        result = call_api(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None)
        print(API_RESULT_PREFIX + json.dumps(result))
    else:
        print(
            "Usage: python -m citizens.devtools seed-recorder-test|seed-load-test [N]|api METHOD PATH [JSON]",
            file=sys.stderr,
        )
        sys.exit(2)
