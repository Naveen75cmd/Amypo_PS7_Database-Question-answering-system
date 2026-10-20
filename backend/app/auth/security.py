"""Password hashing and token minting for local authentication.

Two primitives, both local and dependency-audited:

* **passwords** -- bcrypt at ``settings.bcrypt_rounds``. bcrypt truncates its
  input at 72 bytes, so the byte string is capped explicitly instead of
  silently ignoring everything after the 72nd byte.
* **sessions** -- a short-lived HS256 JWT carrying identity and role, plus an
  opaque refresh token whose SHA-256 hash is the only thing stored. A database
  read therefore cannot mint a session.

The signing key is never committed: ``settings.jwt_secret`` wins if set, and an
unset value produces a random per-process key. That is the safe default (a
restart invalidates every session) and it is why ``.env.example`` documents
``AMYPO_JWT_SECRET`` as the way to keep sessions across restarts.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from ..core.settings import settings

log = logging.getLogger(__name__)

# bcrypt hashes at most 72 bytes; anything longer is truncated by the library.
_BCRYPT_MAX_BYTES = 72

_secret_lock = threading.Lock()
_secret: str | None = None


class TokenError(Exception):
    """A token was missing, malformed, expired or signed with another key."""


def _resolve_secret() -> str:
    """The signing key, generated once per process when none is configured."""
    global _secret
    if _secret is None:
        with _secret_lock:
            if _secret is None:
                configured = settings.jwt_secret.strip()
                if configured:
                    _secret = configured
                else:
                    _secret = secrets.token_urlsafe(48)
                    log.warning(
                        "AMYPO_JWT_SECRET is unset: using a random signing key for "
                        "this process, so sessions end when the backend restarts."
                    )
    return _secret


def reset_secret_cache() -> None:
    """Test hook: forget the cached key so a new ``settings.jwt_secret`` applies."""
    global _secret
    with _secret_lock:
        _secret = None


# --------------------------------------------------------------------------
# Passwords
# --------------------------------------------------------------------------


def hash_password(plain: str) -> str:
    """Hash a password with bcrypt. The only place a password is transformed."""
    raw = plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=settings.bcrypt_rounds)).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time bcrypt check. A bad hash is a failed login, never a 500."""
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(
            plain.encode("utf-8")[:_BCRYPT_MAX_BYTES], hashed.encode("ascii")
        )
    except (ValueError, TypeError):
        return False


# --------------------------------------------------------------------------
# Access tokens (JWT)
# --------------------------------------------------------------------------


def create_access_token(
    *,
    user_id: str,
    username: str,
    role: str,
    student_id: str | None = None,
    department: str | None = None,
    departments: list[str] | None = None,
    cohorts: list[str] | None = None,
    ttl_s: int | None = None,
) -> tuple[str, int]:
    """Mint an access token. Returns ``(token, ttl_seconds)``.

    The role and the student id are *inside* the signed claims. That is the
    whole point: a request cannot choose its own role, and a student token
    carries the only student id it is allowed to read.
    """
    ttl = int(ttl_s if ttl_s is not None else settings.access_token_ttl_s)
    issued = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": user_id,
        "username": username,
        "role": role,
        "typ": "access",
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(seconds=ttl)).timestamp()),
        "jti": secrets.token_hex(8),
    }
    if student_id:
        payload["student_id"] = student_id
    if department:
        payload["department"] = department
    if departments:
        payload["departments"] = list(departments)
    if cohorts:
        payload["cohorts"] = list(cohorts)
    token = jwt.encode(payload, _resolve_secret(), algorithm=settings.jwt_algorithm)
    return token, ttl


def decode_access_token(token: str) -> dict[str, Any]:
    """Verify signature and expiry, then return the claims."""
    if not token:
        raise TokenError("empty token")
    try:
        claims = jwt.decode(
            token,
            _resolve_secret(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub", "role"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("invalid token") from exc
    if claims.get("typ") not in (None, "access"):
        raise TokenError("wrong token type")
    return claims


# --------------------------------------------------------------------------
# Refresh tokens (opaque, stored as a hash)
# --------------------------------------------------------------------------


def new_refresh_token() -> tuple[str, str, str]:
    """A fresh refresh token: ``(raw, sha256_hash, expires_at_iso)``.

    The raw value goes to the client once and is never stored; the hash is the
    primary key of ``refresh_tokens``. Revocation is a row update, so logout
    works even though the access token itself is stateless.
    """
    raw = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(seconds=settings.refresh_token_ttl_s)
    return raw, hash_token(raw), _iso(expires)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def seconds_until(iso_ts: str) -> int:
    """Seconds between now and an ISO-8601 ``...Z`` timestamp (clamped at 0)."""
    try:
        when = datetime.strptime(iso_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return 0
    return max(0, int((when - datetime.now(timezone.utc)).total_seconds()))


def now_iso() -> str:
    return _iso(datetime.now(timezone.utc))


def monotonic_ms() -> float:
    return time.monotonic() * 1000
