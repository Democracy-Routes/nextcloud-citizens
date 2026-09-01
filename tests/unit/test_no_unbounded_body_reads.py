# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""No route may read a request body without a size limit.

Starlette's `Request.body()` accumulates the entire stream with no cap. On a
public route that is a way to make the container allocate as much memory as the
caller cares to send, before any authentication has run — and the recorder
routes deliberately read the body before authenticating, so "the token check
will stop them" is not true here.

`_read_capped_body` is the bounded version. This test exists so that a future
route cannot quietly reintroduce the raw one.
"""

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
API_DIR = ROOT / "citizens" / "api"

# The helper that enforces MAX_CHUNK_BYTES while streaming.
SAFE_READER = "_read_capped_body"


def _unbounded_body_reads(path: pathlib.Path) -> list[str]:
    """`await request.body()` anywhere outside the capped helper itself."""
    tree = ast.parse(path.read_text())
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if node.name == SAFE_READER:
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            func = inner.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "body"
                and isinstance(func.value, ast.Name)
                and func.value.id == "request"
            ):
                found.append(f"{path.name}:{inner.lineno} in {node.name}()")
    return found


@pytest.mark.parametrize(
    "filename", sorted(p.name for p in API_DIR.glob("*.py") if p.name != "__init__.py")
)
def test_routes_do_not_read_an_unbounded_body(filename):
    offenders = _unbounded_body_reads(API_DIR / filename)
    assert not offenders, (
        "request.body() has no size limit — use _read_capped_body() so an "
        "unauthenticated caller cannot make the container buffer an arbitrary "
        "amount of memory:\n  " + "\n  ".join(offenders)
    )


def test_the_capped_reader_is_the_one_actually_used():
    """Guards against the helper existing but nothing calling it."""
    source = (API_DIR / "public_recorder.py").read_text()
    assert f"await {SAFE_READER}(request)" in source
