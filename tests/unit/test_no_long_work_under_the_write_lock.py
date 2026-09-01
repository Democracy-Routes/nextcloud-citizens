# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""No endpoint may do slow work while holding SQLite's single writer slot.

`_begin_immediate` claims that slot at transaction start, so a handler that
takes the write session (`DB`) and then copies a gigabyte of audio into a zip,
renders a PDF, or asks Nextcloud for a setting over OCS blocks every other
writer — including the phones uploading chunks, which fail with "database is
locked" after `busy_timeout`.

`tests/unit/test_no_config_reads_in_transaction.py` already guards the job
runner against the config half of this. That test's own docstring records that
the same mistake was made three times there. It was made a fourth time, in the
API layer, which that test does not scan — so this is the API-layer version.

The fix is always the same: take `ReadDB` instead, and if the endpoint also
needs to write (an audit row), do that in its own short `session_scope()`.
"""

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
API_DIR = ROOT / "citizens" / "api"

# Work that must never happen while the writer slot is held: whole-archive
# builds, PDF rendering, and anything that reaches Nextcloud over OCS.
SLOW_CALLS = {
    "build_audio_zip",
    "build_session_export",
    "render_pdf",
    "render_qr_sheet",
    "data_handling_summary",
    "analysis_enabled_cached",
    "organization_name",
    "providers_summary",
}

# Endpoints that legitimately write AND need one of the above. Each entry is a
# deliberate decision, not an oversight: these are one-off organizer actions
# outside the recording window, never on a path a phone can be waiting behind.
ALLOWED = {
    # freezes the report into the assembly at close/refresh time
    ("reports.py", "close_session"),
    ("reports.py", "refresh_final_report"),
    ("reports.py", "publish_report"),
}


def _write_session_params(node: ast.FunctionDef) -> bool:
    """True if the handler takes the WRITE session dependency (annotated DB)."""
    args = node.args
    for arg in list(args.args) + list(args.kwonlyargs) + list(args.posonlyargs):
        annotation = arg.annotation
        if isinstance(annotation, ast.Name) and annotation.id == "DB":
            return True
    return False


def _touches_session(call: ast.Call) -> bool:
    """A call that queries: `session.get(...)`, or anything taking `session`."""
    func = call.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        if func.value.id == "session":
            return True
    for arg in list(call.args) + [kw.value for kw in call.keywords]:
        if isinstance(arg, ast.Name) and arg.id == "session":
            return True
    return False


def _first_query_line(node: ast.AST) -> int:
    """Where the write transaction actually begins.

    BEGIN IMMEDIATE fires on the first statement, not when the handler is
    entered — so slow work BEFORE any query holds no lock and is the shape we
    WANT (see public_recorder.join, which reads its config up front for exactly
    this reason).
    """
    lines = [c.lineno for c in ast.walk(node) if isinstance(c, ast.Call) and _touches_session(c)]
    return min(lines) if lines else 10**9


def _called_names(node: ast.AST) -> list[tuple[str, int]]:
    after = _first_query_line(node)
    found = []
    for inner in ast.walk(node):
        if not isinstance(inner, ast.Call):
            continue
        func = inner.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name in SLOW_CALLS and inner.lineno > after:
            found.append((name, inner.lineno))
    return found


API_FILES = sorted(p.name for p in API_DIR.glob("*.py") if p.name != "__init__.py")


@pytest.mark.parametrize("filename", API_FILES)
def test_write_session_endpoints_do_no_slow_work(filename):
    tree = ast.parse((API_DIR / filename).read_text())
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not _write_session_params(node):
            continue
        if (filename, node.name) in ALLOWED:
            continue
        for name, lineno in _called_names(node):
            offenders.append(f"{filename}:{lineno} {node.name}() calls {name}()")
    assert not offenders, (
        "these endpoints hold SQLite's write lock across slow work — take "
        "ReadDB instead, and put any audit write in its own session_scope():\n  "
        + "\n  ".join(offenders)
    )
