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
    app_version: str = "0.9.0-alpha.1"
    app_host: str = "0.0.0.0"
    app_port: int = 23000
    app_secret: str = ""
    nextcloud_url: str = ""
    app_persistent_storage: Path = Path("persistent_storage")

    # Citizens-specific
    citizens_log_level: str = "INFO"
    citizens_dev: bool = False
    # The Nextcloud address the table phones open (QR codes). Empty means
    # "ask Nextcloud for overwrite.cli.url" — see services/public_url.py.
    citizens_public_url: str = ""
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

    # Deployment mode (0.9). "nextcloud": an ExApp behind the AppAPI proxy,
    # identity and Settings from Nextcloud — the default, and the only mode
    # that was ever inferred from anything. "standalone": the app serves its
    # own organizer page, keeps accounts and Settings in its database, and
    # the operator's reverse proxy terminates HTTPS. Never guessed from the
    # environment: a typo here is reported at startup, not papered over.
    citizens_mode: str = "nextcloud"
    # Standalone: peer addresses (comma-separated) whose X-Forwarded-For is
    # believed for rate limiting — the reverse proxy in front. Empty: the
    # direct peer address is the client.
    citizens_trusted_proxies: str = ""
    # Standalone mail: smtp://user:pass@host:587 (STARTTLS), smtps://host:465
    # (TLS), smtp://host:25 (plain, local relay only). Empty: mail is written
    # to the log instead of sent (development, tests).
    citizens_smtp_url: str = ""
    citizens_mail_from: str = ""
    # Standalone: a first administrator created at startup while the users
    # table is empty, so a compose file can bootstrap an instance without a
    # shell. Ignored once any account exists.
    citizens_bootstrap_admin_user: str = ""
    citizens_bootstrap_admin_password: str = ""
    # Standalone: how long a signed-in browser stays signed in.
    citizens_session_days: int = 14

    def is_standalone(self) -> bool:
        return self.citizens_mode.strip().lower() == "standalone"

    def mode_problem(self) -> str | None:
        """Why CITIZENS_MODE is not usable as given, or None."""
        mode = self.citizens_mode.strip().lower()
        if mode in ("nextcloud", "standalone"):
            return None
        return f"CITIZENS_MODE={self.citizens_mode!r} is not 'nextcloud' or 'standalone'"

    def auth_disabled(self) -> bool:
        """True only for the local browser-test setup: the flag is ignored
        whenever the app is wired to a non-local Nextcloud, and in standalone
        mode, which has its own sign-in."""
        if not self.citizens_insecure_no_auth or self.is_standalone():
            return False
        host = urlparse(self.nextcloud_url).hostname if self.nextcloud_url else ""
        return not self.nextcloud_url or host in LOCAL_HOSTS

    def missing_required(self) -> list[str]:
        """Environment the deployment must provide; empty values mean a broken
        deployment that would otherwise look healthy (invite links built from
        an empty URL, invite encryption keyed on an empty secret)."""
        missing = []
        if not self.app_secret:
            missing.append("APP_SECRET")
        if self.is_standalone():
            if not self.citizens_public_url:
                missing.append("CITIZENS_PUBLIC_URL")
        elif not self.nextcloud_url:
            missing.append("NEXTCLOUD_URL")
        return missing

    def trusted_proxies(self) -> set[str]:
        return {p.strip() for p in self.citizens_trusted_proxies.split(",") if p.strip()}


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
