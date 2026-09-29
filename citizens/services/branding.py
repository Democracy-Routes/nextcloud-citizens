# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Organization branding assets (logo used on PDF report headers)."""

from pathlib import Path

from citizens.config import get_settings

MAX_LOGO_BYTES = 1_000_000
# magic-number sniffing — fpdf2 supports exactly these two formats natively
_SIGNATURES = {b"\x89PNG\r\n\x1a\n": "png", b"\xff\xd8\xff": "jpg"}


def _branding_dir() -> Path:
    return Path(get_settings().app_persistent_storage) / "branding"


def detect_image_type(data: bytes) -> str | None:
    for signature, ext in _SIGNATURES.items():
        if data.startswith(signature):
            return ext
    return None


def logo_path() -> Path | None:
    for ext in ("png", "jpg"):
        candidate = _branding_dir() / f"logo.{ext}"
        if candidate.is_file():
            return candidate
    return None


def save_logo(data: bytes) -> Path:
    ext = detect_image_type(data)
    if ext is None:
        raise ValueError("Only PNG or JPEG images are supported")
    if len(data) > MAX_LOGO_BYTES:
        raise ValueError("Logo must be 1 MB or smaller")
    delete_logo()
    directory = _branding_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"logo.{ext}"
    target.write_bytes(data)
    return target


def delete_logo() -> bool:
    existing = logo_path()
    if existing is None:
        return False
    existing.unlink(missing_ok=True)
    return True


def organization_name() -> str:
    """Admin-configured organization name for report branding ('' when the
    config store is unreachable — branding must never break a report).

    Read from the config snapshot: the report and QR-sheet handlers hold a
    database connection while they render, and an OCS round-trip there is
    the pattern that exhausted the pool."""
    try:
        from citizens.services import provider_config

        return provider_config.organization_name_cached()
    except Exception:
        return ""
