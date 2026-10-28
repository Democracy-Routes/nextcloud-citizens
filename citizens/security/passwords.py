# SPDX-FileCopyrightText: 2026 Philip <philip@decentsoftwa.re>
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Password hashing for standalone accounts: scrypt from the standard
library, so the image needs no extra dependency, with parameters and a
versioned format so they can be raised later without invalidating anyone.

Format: ``scrypt$<log2 n>$<r>$<p>$<salt b64>$<hash b64>``.
"""

import base64
import hashlib
import hmac
import secrets

_LOG2_N = 14  # 16 MiB of memory per hash, ~50 ms: fine for a login, costly for a brute force
_R = 8
_P = 1
_DKLEN = 32
_MAXMEM = 64 * 1024 * 1024

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 200


def _derive(password: str, salt: bytes, log2_n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=1 << log2_n, r=r, p=p,
        maxmem=_MAXMEM, dklen=_DKLEN,
    )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _derive(password, salt, _LOG2_N, _R, _P)
    return "$".join([
        "scrypt", str(_LOG2_N), str(_R), str(_P),
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    ])


def verify_password(password: str, stored: str | None) -> bool:
    """False for an account with no password yet, a malformed row, or a
    wrong password — never an exception on a login attempt."""
    if not stored or not password:
        return False
    try:
        scheme, log2_n, r, p, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(hash_b64)
        actual = _derive(password, base64.b64decode(salt_b64), int(log2_n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(expected, actual)


def password_problem(password: str) -> str | None:
    """Why a chosen password is refused, or None. Length only: composition
    rules push people to Passw0rd!, length does not."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"The password must be at least {MIN_PASSWORD_LENGTH} characters long"
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"The password must be at most {MAX_PASSWORD_LENGTH} characters long"
    return None
