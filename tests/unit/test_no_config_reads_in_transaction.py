# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Provider config must never be read while a write transaction is open.

Reading provider config means an OCS HTTP call to Nextcloud. SQLite has one
writer, and `BEGIN IMMEDIATE` claims it at transaction start, so a config read
inside a transaction holds that slot across a network round-trip. Every request
that wants to write then queues on `busy_timeout` (10 s) and fails with
"database is locked" — a 500 to a phone mid-recording.

This has now happened three times: in the job handlers, then again in the
retention sweep, then on the chunk-upload path. Each time it was fixed with a
comment. This test is the version that cannot be forgotten.
"""

import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

# calls that reach Nextcloud over OCS, directly or via a helper that does.
# The snapshot readers (data_handling_summary, live_stt_snapshot,
# analysis_enabled_cached, analysis_ready_cached, organization_name_cached)
# are deliberately absent: since 0.6.2 they read memory that
# refresh_config_snapshot() fills in the background, which is the whole
# point — the request path never waits on Nextcloud.
CONFIG_CALLS = {
    "get_setting",
    "default_store",
    "providers_summary",
    "refresh_config_snapshot",
    "invalidate_snapshot",
    "set_settings",
    "analysis_ready",
    "_analysis_config",
    "build_system_prompt",
}
TRANSACTION_SCOPES = {"session_scope", "read_only_scope"}

# every module of the app: the first version of this file listed the eight
# files somebody thought of, and the defect that froze the server under five
# phones lived in one of them, in a function the with-block scan could not
# see (public_recorder._assembly_state, whose session is injected)
ALL_SOURCES = sorted(
    str(path.relative_to(ROOT))
    for path in (ROOT / "citizens").rglob("*.py")
    if "migrations" not in path.parts
)


def _call_name(node: ast.AST) -> str:
    func = getattr(node, "func", None)
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _offending_calls(path: pathlib.Path) -> list[str]:
    """Config reads lexically nested inside a `with session_scope()` block."""
    tree = ast.parse(path.read_text())
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.With):
            continue
        if not any(_call_name(item.context_expr) in TRANSACTION_SCOPES for item in node.items):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call) and _call_name(inner) in CONFIG_CALLS:
                found.append(f"{path.name}:{inner.lineno} {_call_name(inner)}()")
    return found


def _offending_session_functions(path: pathlib.Path) -> list[str]:
    """Config reads in a function that HOLDS an injected session, with no
    commit first.

    The check above was vacuous for citizens/jobs/handlers.py: the runner
    injects the session, so the file never contains `with session_scope()` and
    the walk scanned zero nodes — which is exactly where the regression came
    back. Any statement on an injected session opens a transaction (BEGIN
    IMMEDIATE on a write session, a checked-out pool connection on a read
    one), so from the first use of `session` a function is in-transaction
    until a `session.commit()`. A config read BEFORE the session is first
    used is fine — that is how join() and update_providers() are written.
    """
    tree = ast.parse(path.read_text())
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = [a.arg for a in node.args.args + node.args.kwonlyargs]
        if "session" not in args:
            continue
        first_use = None
        for inner in ast.walk(node):
            if isinstance(inner, ast.Name) and inner.id == "session":
                if first_use is None or inner.lineno < first_use:
                    first_use = inner.lineno
        committed_line = None
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            name = _call_name(inner)
            if name == "commit" and isinstance(inner.func, ast.Attribute):
                if committed_line is None or inner.lineno < committed_line:
                    committed_line = inner.lineno
            elif name in CONFIG_CALLS:
                if first_use is None or inner.lineno <= first_use:
                    continue  # read before the session is touched
                if committed_line is None or inner.lineno < committed_line:
                    found.append(f"{path.name}:{inner.lineno} {name}() in {node.name}()")
    return found


@pytest.mark.parametrize("relative_path", ALL_SOURCES)
def test_background_work_never_reads_config_inside_a_transaction(relative_path):
    """The regression that 500'd a live recording: the retention sweep opened a
    session, found candidates, and only then asked Nextcloud for the retention
    default — holding the write lock across two HTTPS round-trips, every 60 s."""
    offenders = _offending_calls(ROOT / relative_path)
    assert not offenders, (
        "provider config is read inside a database transaction: "
        + ", ".join(offenders)
    )


@pytest.mark.parametrize("relative_path", ALL_SOURCES)
def test_injected_session_functions_commit_before_reading_config(relative_path):
    """The vacuous-guard fix: handlers receive their session from the runner,
    so the with-block scan above never saw them — and the OCS-under-writer-slot
    regression returned through exactly that gap. Then it returned once more
    through the same gap in citizens/api/public_recorder.py, which this
    parametrization used to leave out: the status poll read six settings
    over OCS with a pool connection checked out, and five phones were enough
    to exhaust the pool."""
    offenders = _offending_session_functions(ROOT / relative_path)
    assert not offenders, (
        "config read on an injected session with no commit released first: "
        + ", ".join(offenders)
    )


def test_upload_path_reads_caption_config_before_touching_the_database():
    """live_stt_snapshot() must be read before the first query in upload_chunk,
    so its 30-second cache refresh cannot block writers."""
    import inspect

    from citizens.api import public_recorder

    source = inspect.getsource(public_recorder.upload_chunk)
    snapshot_at = source.index("live_stt_snapshot()")
    auth_at = source.index("_session_from_authorization")
    assert snapshot_at < auth_at, (
        "live_stt_snapshot() must be called before authentication opens a "
        "transaction — otherwise its OCS refresh holds the write lock"
    )


@pytest.mark.parametrize(
    "module_name, function_name",
    [
        ("citizens.services.transcription", "transcribe_recording"),
        ("citizens.services.analysis", "analyze_table"),
        ("citizens.services.analysis", "analyze_round"),
    ],
)
def test_handlers_commit_before_reading_provider_config(module_name, function_name):
    """Each of these releases the write lock before its provider call; the
    config reads that precede that call must be after the commit too."""
    import importlib
    import inspect

    module = importlib.import_module(module_name)
    source = inspect.getsource(getattr(module, function_name))
    commit_at = source.index("session.commit()")
    for marker in ("get_setting(", "_analysis_config(", "build_system_prompt("):
        at = source.find(marker)
        if at == -1:
            continue
        assert at > commit_at, (
            f"{function_name} reads provider config ({marker}) before "
            "session.commit() — that read is an OCS call holding the write lock"
        )
