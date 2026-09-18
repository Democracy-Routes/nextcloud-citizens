# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Application configuration from environment variables (provided by AppAPI)."""

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    # Provided by AppAPI / the container environment
    app_id: str = "citizens"
    app_version: str = "0.6.0-beta.11"
    app_host: str = "0.0.0.0"
    app_port: int = 23000
    app_secret: str = ""
    nextcloud_url: str = ""
    app_persistent_storage: Path = Path("persistent_storage")

    # Citizens-specific
    citizens_log_level: str = "INFO"
    citizens_dev: bool = False
    # How many jobs run at once. Ten tables end a round together; one worker
    # processed their transcriptions and analyses one after another, so the
    # report was 35-85 minutes away. Speech-to-text concurrency per provider
    # is still governed by the Settings caps (a job over the cap waits, it
    # does not fail); 1 restores the strictly sequential runner.
    citizens_job_workers: int = 10
    # ONLY for local browser tests: disables AppAPI signature auth entirely.
    # Honored solely against a local Nextcloud (see auth_disabled()), so a
    # stray environment variable cannot open up a real deployment.
    citizens_insecure_no_auth: bool = False

    def auth_disabled(self) -> bool:
        """True only for the local browser-test setup: the flag is ignored
        whenever the app is wired to a non-local Nextcloud."""
        if not self.citizens_insecure_no_auth:
            return False
        host = urlparse(self.nextcloud_url).hostname if self.nextcloud_url else ""
        return not self.nextcloud_url or host in LOCAL_HOSTS

    def missing_required(self) -> list[str]:
        """Environment AppAPI always provides; empty values mean a broken
        deployment that would otherwise look healthy (invite links built from
        an empty URL, invite encryption keyed on an empty secret)."""
        missing = []
        if not self.app_secret:
            missing.append("APP_SECRET")
        if not self.nextcloud_url:
            missing.append("NEXTCLOUD_URL")
        return missing


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
