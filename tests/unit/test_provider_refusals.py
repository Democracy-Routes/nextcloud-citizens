# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What a provider's refusal turns into, end to end.

At the 2026-09-18 rehearsal Mistral answered 403 to every analysis call and
Ollama answered 429; the organizer saw "did not complete" and "already
running". The provider's own words now travel with the error, a 429's
Retry-After outranks the runner's exponential guess, Mistral gets JSON mode,
and the free text is classified into reasons the UI can explain.
"""

from datetime import timedelta

import pytest

from citizens.db.models import AppJob
from citizens.db.models.base import utcnow
from citizens.db.session import session_scope
from citizens.jobs import runner
from citizens.providers import http_detail
from citizens.providers.analysis import openai_compat
from citizens.providers.transcription import mistral
from citizens.providers.transcription.base import TranscriptionError
from citizens.services import job_failures
from citizens.services.jobs import enqueue_job


class FakeResponse:
    def __init__(self, status_code, body=None, text="", headers=None):
        self.status_code = status_code
        self._body = body
        self.text = text if body is None else __import__("json").dumps(body)
        self.headers = headers or {}

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


# ------------------------------------------------------------ http_detail


def test_retry_after_accepts_seconds_and_dates_and_nothing():
    assert http_detail.retry_after_seconds({"retry-after": "7"}) == 7.0
    soon = (utcnow() + timedelta(seconds=90)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    assert 80 <= http_detail.retry_after_seconds({"retry-after": soon}) <= 90
    assert http_detail.retry_after_seconds({"retry-after": "garbage"}) is None
    assert http_detail.retry_after_seconds({}) is None


def test_error_detail_finds_the_message_in_the_usual_places():
    assert http_detail.error_detail(FakeResponse(403, {"message": "Inactive subscription"})) == \
        "Inactive subscription"
    assert http_detail.error_detail(FakeResponse(429, {"error": {"message": "slow down"}})) == \
        "slow down"
    assert http_detail.error_detail(FakeResponse(404, {"detail": "no such model"})) == "no such model"
    html = FakeResponse(502, text="<html><body><h1>502 Bad Gateway</h1>\n<p>nginx</p></body></html>")
    assert http_detail.error_detail(html) == "502 Bad Gateway nginx"
    assert len(http_detail.error_detail(FakeResponse(500, {"message": "x" * 1000}))) == 300


# --------------------------------------------------------- analysis adapter


def _capture_post(monkeypatch, response):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return response

    monkeypatch.setattr(openai_compat.httpx, "post", fake_post)
    return captured


def test_json_mode_is_sent_to_mistral_only(monkeypatch):
    ok = FakeResponse(200, {"choices": [{"message": {"content": "{}"}}]})
    captured = _capture_post(monkeypatch, ok)
    openai_compat._chat("https://api.mistral.ai/v1", "k", "mistral-large-latest", [])
    assert captured["json"]["response_format"] == {"type": "json_object"}

    captured = _capture_post(monkeypatch, ok)
    openai_compat._chat("https://ollama.com/v1", "k", "deepseek-v4-flash", [])
    assert "response_format" not in captured["json"]


def test_a_refusal_carries_the_providers_words_and_is_permanent(monkeypatch):
    _capture_post(monkeypatch, FakeResponse(403, {"message": "Inactive subscription"}))
    with pytest.raises(openai_compat.AnalysisError) as raised:
        openai_compat._chat("https://api.mistral.ai/v1", "k", "m", [])
    assert raised.value.permanent is True
    assert raised.value.status == 403
    assert "Inactive subscription" in str(raised.value)


def test_a_rate_limit_is_temporary_and_says_how_long_to_wait(monkeypatch):
    _capture_post(monkeypatch, FakeResponse(429, {"message": "slow down"}, headers={"retry-after": "12"}))
    with pytest.raises(openai_compat.AnalysisError) as raised:
        openai_compat._chat("https://ollama.com/v1", "k", "m", [])
    assert raised.value.permanent is False
    assert raised.value.status == 429
    assert raised.value.retry_after == 12.0


# ----------------------------------------------------- transcription adapter


def _fake_mistral_post(monkeypatch, response):
    monkeypatch.setattr(
        mistral.httpx, "post", lambda url, headers=None, data=None, files=None, timeout=None: response
    )


def test_mistral_rate_limit_carries_retry_after(monkeypatch, tmp_path):
    audio = tmp_path / "t.webm"
    audio.write_bytes(b"x")
    _fake_mistral_post(
        monkeypatch, FakeResponse(429, text="Too many requests", headers={"retry-after": "30"})
    )
    with pytest.raises(TranscriptionError) as raised:
        mistral.transcribe_file("k", audio, "audio/webm", "it")
    assert raised.value.permanent is False
    assert raised.value.status == 429 and raised.value.retry_after == 30.0
    assert "Too many requests" in str(raised.value)


def test_mistral_refusal_is_permanent_with_the_reason(monkeypatch, tmp_path):
    audio = tmp_path / "t.webm"
    audio.write_bytes(b"x")
    _fake_mistral_post(monkeypatch, FakeResponse(403, {"message": "Forbidden for this workspace"}))
    with pytest.raises(TranscriptionError) as raised:
        mistral.transcribe_file("k", audio, "audio/webm", "it")
    assert raised.value.permanent is True and "Forbidden for this workspace" in str(raised.value)


def test_mistral_non_json_success_body_is_a_transcription_error(monkeypatch, tmp_path):
    # an HTML page with a 200 used to escape as ValueError and strand the
    # recording in TRANSCRIBING
    audio = tmp_path / "t.webm"
    audio.write_bytes(b"x")
    _fake_mistral_post(monkeypatch, FakeResponse(200, text="<html>maintenance</html>"))
    with pytest.raises(TranscriptionError):
        mistral.transcribe_file("k", audio, "audio/webm", "it")


def test_the_batch_timeout_fits_a_forty_minute_round_and_the_job_lease():
    # 30 min took up to 313 s; 40 min scales to ~420 s and a slow day sits on
    # top of that. And the runner must not reclaim a job still uploading.
    assert mistral.REQUEST_TIMEOUT_SECONDS >= 1200
    assert mistral.REQUEST_TIMEOUT_SECONDS < runner.RUNNING_LEASE_SECONDS


# --------------------------------------------------------------- classifier


@pytest.mark.parametrize("message, reason", [
    ("Analysis authentication failed (403): Inactive subscription", "PROVIDER_AUTH"),
    ("Mistral authentication failed (401)", "PROVIDER_AUTH"),
    ("Analysis endpoint returned HTTP 429 (rate limited): slow down", "PROVIDER_RATE_LIMIT"),
    ("Mistral returned HTTP 429", "PROVIDER_RATE_LIMIT"),
    ("Analysis request failed: ConnectTimeout", "PROVIDER_TIMEOUT"),
    ("Mistral request failed: ReadTimeout", "PROVIDER_TIMEOUT"),
    ("Analysis endpoint returned HTTP 502: Bad Gateway", "PROVIDER_HTTP"),
    ("Analysis endpoint rejected the request (422): bad model", "PROVIDER_HTTP"),
    ("Vosk server unreachable at ws://x: ConnectionRefusedError", "PROVIDER_HTTP"),
    ("Model output failed validation after retries: findings.0.title", "SCHEMA_INVALID"),
    ("Analysis endpoint returned an unexpected payload", "SCHEMA_INVALID"),
    ("No analysis API key configured", "NOT_CONFIGURED"),
    ("No Mistral API key configured", "NOT_CONFIGURED"),
    ("No transcript for this table", "NO_TRANSCRIPT"),
    ("The caption session never wrote a transcript", "NO_TRANSCRIPT"),
    ("Canonical audio file is missing", "AUDIO_MISSING"),
    ("cancelled by organizer", "CANCELLED"),
    ("", "UNKNOWN"),
    ("something nobody anticipated", "UNKNOWN"),
])
def test_every_provider_message_maps_to_a_reason(message, reason):
    assert job_failures.classify(message) == reason
    assert reason in job_failures.FAILURE_REASONS


def test_latest_jobs_returns_the_newest_per_id(database):
    with session_scope() as session:
        older = enqueue_job(session, "ANALYZE_TABLE", {"recording_id": "r1"})
        older.state = "FAILED"
        older.last_error = "Analysis authentication failed (403): nope"
        older.created_at = utcnow() - timedelta(minutes=5)
        newer = enqueue_job(session, "ANALYZE_TABLE", {"recording_id": "r1"})
        newer.state = "RETRY"
        newer.attempts = 2
        newer.last_error = "Analysis endpoint returned HTTP 429 (rate limited): slow"
        newer.next_attempt_at = utcnow() + timedelta(seconds=60)
        enqueue_job(session, "ANALYZE_TABLE", {"recording_id": "r2"})
        session.flush()

        found = job_failures.latest_jobs(session, "ANALYZE_TABLE", "recording_id", {"r1", "r2"})
        assert found["r1"].id == newer.id
        described = job_failures.describe(found["r1"])
        assert described["state"] == "RETRY"
        assert described["failure_reason"] == "PROVIDER_RATE_LIMIT"
        assert described["next_attempt_at"] is not None
        assert described["attempts"] == 2 and described["max_attempts"] == 5
        assert job_failures.describe(found["r2"])["failure_reason"] is None
        assert job_failures.latest_job_failure(session, "ANALYZE_TABLE", "recording_id", "r9") is None


# ------------------------------------------------------------------ runner


def test_the_runner_waits_as_long_as_the_provider_asked(database, monkeypatch):
    class Throttled(Exception):
        retry_after = 600

    def handler(session, payload):
        raise Throttled("429")

    monkeypatch.setitem(runner.HANDLERS, "TEST_THROTTLED", handler)
    with session_scope() as session:
        job = enqueue_job(session, "TEST_THROTTLED", {"x": 1})
        job.state = "RUNNING"
        job.locked_at = utcnow()
        job.attempts = 1
        job_id = job.id
    before = utcnow()
    runner._run_job(job_id)
    with session_scope() as session:
        job = session.get(AppJob, job_id)
        assert job.state == "RETRY"
        # the exponential guess would have been 30 s; the provider said 600
        assert job.next_attempt_at >= before + timedelta(seconds=599)
        assert job.next_attempt_at <= before + timedelta(seconds=runner.BACKOFF_MAX_SECONDS + 1)
