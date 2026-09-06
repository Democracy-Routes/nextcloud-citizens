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

# calls that reach Nextcloud over OCS, directly or via a helper that does
CONFIG_CALLS = {
    "get_setting",
    "default_store",
    "providers_summary",
    "data_handling_summary",
    "_analysis_config",
    "build_system_prompt",
}
TRANSACTION_SCOPES = {"session_scope", "read_only_scope"}


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
    back. Any statement on an injected session opens BEGIN IMMEDIATE, so a
    function that takes a `session` parameter is in-transaction from its first
    line unless a `session.commit()` appears before the config call.
    """
    tree = ast.parse(path.read_text())
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = [a.arg for a in node.args.args]
        if "session" not in args:
            continue
        committed_line = None
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            name = _call_name(inner)
            if name == "commit" and isinstance(inner.func, ast.Attribute):
                if committed_line is None or inner.lineno < committed_line:
                    committed_line = inner.lineno
            elif name in CONFIG_CALLS:
                if committed_line is None or inner.lineno < committed_line:
                    found.append(f"{path.name}:{inner.lineno} {name}() in {node.name}()")
    return found


@pytest.mark.parametrize(
    "relative_path",
    [
        "citizens/jobs/sweep.py",
        "citizens/jobs/runner.py",
        "citizens/jobs/handlers.py",
        "citizens/api/public_recorder.py",
        "citizens/api/files.py",
        "citizens/api/reports.py",
        "citizens/api/recorders.py",
        "citizens/api/admin.py",
    ],
)
def test_background_work_never_reads_config_inside_a_transaction(relative_path):
    """The regression that 500'd a live recording: the retention sweep opened a
    session, found candidates, and only then asked Nextcloud for the retention
    default — holding the write lock across two HTTPS round-trips, every 60 s."""
    offenders = _offending_calls(ROOT / relative_path)
    assert not offenders, (
        "provider config is read inside a database transaction: "
        + ", ".join(offenders)
    )


@pytest.mark.parametrize(
    "relative_path",
    [
        "citizens/jobs/handlers.py",
        "citizens/jobs/sweep.py",
    ],
)
def test_injected_session_functions_commit_before_reading_config(relative_path):
    """The vacuous-guard fix: handlers receive their session from the runner,
    so the with-block scan above never saw them — and the OCS-under-writer-slot
    regression returned through exactly that gap."""
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
