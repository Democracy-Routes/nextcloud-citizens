# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The database commit must happen before the response leaves the server.

FastAPI 0.118+ runs a yield dependency's exit code after the response is
sent unless the dependency is declared with scope="function". get_db commits
in its exit code, so without the scope a client reading right after a write
could miss its own row — which is what the dev instance showed: a record-now
container 404 a hundred milliseconds after its 201. This keeps every
declaration scoped; a new router must follow suit."""

import re
from pathlib import Path

API = Path(__file__).resolve().parents[2] / "citizens" / "api"


def test_every_db_dependency_is_function_scoped():
    offenders = []
    for path in sorted(API.glob("*.py")):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r"Depends\(get_(read_)?db\s*\)", line):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert offenders == [], "declare with Depends(get_db, scope=\"function\"):\n" + "\n".join(offenders)


def test_the_guard_sees_the_routers():
    assert sum(1 for p in API.glob("*.py") if "scope=\"function\"" in p.read_text()) >= 8
