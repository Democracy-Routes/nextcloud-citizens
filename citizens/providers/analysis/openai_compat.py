# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""OpenAI-compatible chat adapter for AI analysis.

Works against any /v1/chat/completions endpoint — Mistral (default), Ollama
(local or cloud), vLLM… Strict JSON is enforced by prompt + Pydantic
validation with correction-retry (brief §37); malformed output is never
accepted.
"""

import json
from typing import TypeVar
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ValidationError

from citizens.logging_setup import get_logger
from citizens.providers.http_detail import error_detail, retry_after_seconds

log = get_logger(__name__)

MAX_CORRECTION_RETRIES = 2


class AnalysisError(Exception):
    def __init__(
        self,
        message: str,
        permanent: bool = False,
        status: int | None = None,
        retry_after: float | None = None,
    ):
        super().__init__(message)
        self.permanent = permanent
        self.status = status
        self.retry_after = retry_after


def _wants_json_mode(base_url: str) -> bool:
    # Mistral supports response_format json_object and refuses far fewer
    # replies with it (the prompts already contain the word "JSON", which it
    # requires). Not sent elsewhere: Ollama and vLLM builds differ in support,
    # and an unknown field is a 400 on some of them.
    return (urlparse(base_url).hostname or "").lower() == "api.mistral.ai"


def _extract_json(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        # strip a ```json … ``` fence
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object found in response")
    return json.loads(text[start : end + 1])


def _chat(base_url: str, api_key: str, model: str, messages: list[dict]) -> str:
    body: dict = {"model": model, "messages": messages, "temperature": 0.2}
    if _wants_json_mode(base_url):
        body["response_format"] = {"type": "json_object"}
    try:
        response = httpx.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=body,
            timeout=httpx.Timeout(300, connect=30),
        )
    except httpx.HTTPError as exc:
        raise AnalysisError(f"Analysis request failed: {type(exc).__name__}") from exc
    status = response.status_code
    if status == 200:
        try:
            return response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise AnalysisError(
                "Analysis endpoint returned an unexpected payload", permanent=True, status=status
            ) from exc
    # The provider's own words reach the job row and, from there, the
    # organizer: "Inactive subscription" is actionable, "HTTP 403" is not. At
    # the 2026-09-18 rehearsal a 403 was re-run five times blind.
    detail = error_detail(response)
    log.warning("analysis_provider_refused", status=status, detail=detail)
    if status in (401, 403):
        raise AnalysisError(
            f"Analysis authentication failed ({status}): {detail}", permanent=True, status=status
        )
    if status in (404, 422):
        raise AnalysisError(
            f"Analysis endpoint rejected the request ({status}): {detail}",
            permanent=True, status=status,
        )
    if status == 429:
        raise AnalysisError(
            f"Analysis endpoint returned HTTP 429 (rate limited): {detail}",
            status=status, retry_after=retry_after_seconds(response.headers),
        )
    raise AnalysisError(f"Analysis endpoint returned HTTP {status}: {detail}", status=status)


T = TypeVar("T", bound=BaseModel)


def chat_json(
    base_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    schema: type[T],
) -> T:
    """Run a chat completion and validate the response against `schema`,
    retrying with a correction prompt on malformed output."""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    last_error = ""
    for attempt in range(1 + MAX_CORRECTION_RETRIES):
        content = _chat(base_url, api_key, model, messages)
        try:
            return schema.model_validate(_extract_json(content))
        except (ValueError, ValidationError) as exc:
            last_error = str(exc)[:800]
            log.warning("analysis_output_invalid", attempt=attempt + 1, error=last_error[:200])
            messages.append({"role": "assistant", "content": content[:8000]})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Your previous answer was not valid. "
                        f"Validation error: {last_error}\n"
                        "Respond again with ONLY a valid JSON object matching the required "
                        "schema — no prose, no code fences, no explanations."
                    ),
                }
            )
    raise AnalysisError(f"Model output failed validation after retries: {last_error}", permanent=True)
