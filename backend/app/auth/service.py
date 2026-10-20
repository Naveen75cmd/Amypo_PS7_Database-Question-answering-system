"""Local account management: login, refresh, logout, admin user CRUD and audit.

Everything here reads and writes MySQL through the project's small SQL helpers,
so the auth layer obeys the same "MySQL is the only source of truth" rule as the
rest of the system. There is no external identity provider and no network call.

Failure modes are deliberately uniform: a wrong username and a wrong password
both produce ``invalid_credentials`` and the same message, so the login endpoint
cannot be used to enumerate accounts.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from ..core.settings import settings
from ..db import execute, executemany, query, query_one
from .principal import (
    ALL_ROLES,
    ROLE_ADMIN,
    ROLE_EVAL,
    ROLE_STAFF,
    ROLE_STUDENT,
    Principal,
)
from .security import (
    create_access_token,
    hash_password,
    hash_token,
    new_refresh_token,
    now_iso,
    seconds_until,
    verify_password,
)

log = logging.getLogger(__name__)


class AuthError(Exception):
    """A refused authentication attempt, with a stable machine-readable kind."""

    def __init__(self, kind: str, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.status_code = status_code


@dataclass
class TokenBundle:
    access_token: str
    refresh_token: str
    expires_in: int
    user: dict[str, Any]


# --------------------------------------------------------------------------
# Audit
# --------------------------------------------------------------------------


def record_audit(
    *,
    actor: Principal | None,
    action: str,
    allowed: bool,
    target: str | None = None,
    scope: str | None = None,
    ip: str | None = None,
    detail: str | None = None,
) -> None:
    """Write one audit row. Never raises: logging must not break a request."""
    try:
        execute(
            """
            INSERT INTO audit_log
                (actor_id, actor_role, action, target, scope, ip, allowed, detail, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                actor.user_id if actor else None,
                actor.role if actor else None,
                action,
                (target or "")[:191] or None,
                (scope or "")[:191] or None,
                (ip or "")[:64] or None,
                1 if allowed else 0,
                (detail or "")[:2000] or None,
                now_iso(),
            ),
        )
    except Exception as exc:  # pragma: no cover - a broken audit must not 500
        log.warning("could not write audit row for %s: %s", action, exc)


def audit_entries(
    *,
    limit: int = 100,
    allowed_only: bool | None = None,
    actor_role: str | None = None,
) -> list[dict[str, Any]]:
    """Most recent audit rows, newest first, for the admin audit page."""
    limit = max(1, min(int(limit), 500))
    where: list[str] = []
    params: list[Any] = []
    if allowed_only is not None:
        where.append("allowed = ?")
        params.append(1 if allowed_only else 0)
    if actor_role:
        where.append("actor_role = ?")
        params.append(actor_role)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    params.append(limit)
    rows = query(
        f"""
        SELECT id, actor_id, actor_role, action, target, scope, ip, allowed,
               detail, created_at
        FROM audit_log
        {clause}
        ORDER BY id DESC
        LIMIT ?
        """,
        tuple(params),
    )
    return [dict(row) for row in rows]


def audit_summary() -> dict[str, Any]:
    """Counts the dashboard can show without scanning the whole table."""
    rows = query(
        """
        SELECT action, allowed, COUNT(*) AS n
        FROM audit_log
        GROUP BY action, allowed
        """
    )
    denied = sum(int(r["n"]) for r in rows if not int(r["allowed"]))
    allowed = sum(int(r["n"]) for r in rows if int(r["allowed"]))
    return {"allowed": allowed, "denied": denied, "total": allowed + denied}


# --------------------------------------------------------------------------
# Users
# --------------------------------------------------------------------------


def _user_public(row: dict[str, Any]) -> dict[str, Any]:
    """A user row without the password hash."""
    return {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "role": row["role"],
        "student_id": row.get("student_id"),
        "department": row.get("department"),
        "cohort": row.get("cohort"),
        "is_active": bool(row.get("is_active")),
        "created_at": row.get("created_at"),
        "last_login": row.get("last_login"),
    }


def find_user(identifier: str) -> dict[str, Any] | None:
    """Look a user up by username or email, case-insensitively."""
    if not identifier:
        return None
    needle = identifier.strip().lower()
    return query_one(
        """
        SELECT * FROM users
        WHERE LOWER(username) = ? OR LOWER(email) = ?
        LIMIT 1
        """,
        (needle, needle),
    )


def get_user(user_id: str) -> dict[str, Any] | None:
    return query_one("SELECT * FROM users WHERE id = ?", (user_id,))


def list_users(limit: int = 200, role: str | None = None) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 1000))
    if role:
        rows = query(
            "SELECT * FROM users WHERE role = ? ORDER BY role, username LIMIT ?",
            (role, limit),
        )
    else:
        rows = query("SELECT * FROM users ORDER BY role, username LIMIT ?", (limit,))
    return [_user_public(row) for row in rows]


def staff_assignments_for(user_id: str) -> list[dict[str, Any]]:
    rows = query(
        """
        SELECT id, scope_kind, scope_value, created_at
        FROM staff_assignments WHERE staff_id = ? ORDER BY scope_value
        """,
        (user_id,),
    )
    return [dict(row) for row in rows]


def principal_for(user_row: dict[str, Any]) -> Principal:
    """Build the Principal an authenticated user acts as."""
    departments: tuple[str, ...] = ()
    cohorts: tuple[str, ...] = ()
    if user_row.get("role") == ROLE_STAFF:
        assignments = staff_assignments_for(user_row["id"])
        departments = tuple(
            a["scope_value"] for a in assignments if a["scope_kind"] == "department"
        )
        cohorts = tuple(
            a["scope_value"] for a in assignments if a["scope_kind"] == "cohort"
        )
        if user_row.get("department") and user_row["department"] not in departments:
            departments = departments + (user_row["department"],)
        if user_row.get("cohort") and user_row["cohort"] not in cohorts:
            cohorts = cohorts + (user_row["cohort"],)
    return Principal(
        user_id=user_row["id"],
        username=user_row["username"],
        role=user_row["role"],
        student_id=user_row.get("student_id"),
        departments=departments,
        cohorts=cohorts,
        is_service=user_row.get("role") == ROLE_EVAL,
    )


# --------------------------------------------------------------------------
# Throttling
# --------------------------------------------------------------------------


def recent_failures(username: str, ip: str) -> int:
    """Failed logins for this username or IP inside the window."""
    since = (
        datetime.now(timezone.utc) - timedelta(seconds=settings.login_window_s)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = query(
        """
        SELECT COUNT(*) AS n FROM login_attempts
        WHERE success = 0 AND attempted_at >= ? AND (username = ? OR ip = ?)
        """,
        (since, username, ip),
    )
    return int(rows[0]["n"]) if rows else 0


def _record_attempt(username: str, ip: str, success: bool) -> None:
    try:
        execute(
            """
            INSERT INTO login_attempts (username, ip, success, attempted_at)
            VALUES (?, ?, ?, ?)
            """,
            (username[:64], (ip or "")[:64], 1 if success else 0, now_iso()),
        )
    except Exception as exc:  # pragma: no cover
        log.warning("could not record login attempt: %s", exc)


# --------------------------------------------------------------------------
# Login / refresh / logout
# --------------------------------------------------------------------------


def login(
    identifier: str,
    password: str,
    *,
    ip: str = "",
    user_agent: str = "",
) -> TokenBundle:
    """Verify credentials and open a session.

    Raises :class:`AuthError` with kind ``throttled``, ``disabled`` or
    ``invalid_credentials``. The same generic message is used for a missing user
    and a wrong password.
    """
    identifier = (identifier or "").strip()
    if not identifier or not password:
        raise AuthError("invalid_credentials", "Incorrect username or password.")

    if recent_failures(identifier.lower(), ip) >= settings.login_max_attempts:
        record_audit(
            actor=None,
            action="login_throttled",
            allowed=False,
            target=identifier,
            ip=ip,
            detail=f"{settings.login_max_attempts} failures in {settings.login_window_s}s",
        )
        raise AuthError(
            "throttled",
            "Too many failed attempts. Wait a few minutes and try again.",
            status_code=429,
        )

    row = find_user(identifier)
    if row is None or not verify_password(password, row["password_hash"]):
        _record_attempt(identifier.lower(), ip, False)
        record_audit(
            actor=None,
            action="login_failed",
            allowed=False,
            target=identifier,
            ip=ip,
        )
        raise AuthError("invalid_credentials", "Incorrect username or password.")

    if not int(row.get("is_active") or 0):
        _record_attempt(identifier.lower(), ip, False)
        record_audit(
            actor=Principal(
                user_id=row["id"], username=row["username"], role=row["role"]
            ),
            action="login_disabled",
            allowed=False,
            target=identifier,
            ip=ip,
        )
        raise AuthError(
            "disabled",
            "This account is disabled. Ask an administrator to re-enable it.",
            status_code=403,
        )

    _record_attempt(identifier.lower(), ip, True)
    principal = principal_for(row)
    access, ttl = create_access_token(
        user_id=principal.user_id,
        username=principal.username,
        role=principal.role,
        student_id=principal.student_id,
        department=row.get("department"),
        departments=list(principal.departments),
        cohorts=list(principal.cohorts) or ([row["cohort"]] if row.get("cohort") else []),
    )
    raw_refresh, refresh_hash, refresh_expires = new_refresh_token()
    execute(
        """
        INSERT INTO refresh_tokens
            (token_hash, user_id, issued_at, expires_at, revoked_at, replaced_by, ip, user_agent)
        VALUES (?, ?, ?, ?, NULL, NULL, ?, ?)
        """,
        (
            refresh_hash,
            principal.user_id,
            now_iso(),
            refresh_expires,
            (ip or "")[:64] or None,
            (user_agent or "")[:255] or None,
        ),
    )
    execute("UPDATE users SET last_login = ? WHERE id = ?", (now_iso(), principal.user_id))
    record_audit(
        actor=principal,
        action="login",
        allowed=True,
        target=principal.username,
        scope=principal.cache_scope,
        ip=ip,
    )

    row = get_user(principal.user_id) or row
    return TokenBundle(
        access_token=access, refresh_token=raw_refresh, expires_in=ttl,
        user=_user_public(row),
    )


def refresh(
    raw_token: str, *, ip: str = "", user_agent: str = ""
) -> TokenBundle:
    """Rotate a refresh token.

    Reuse of an already-rotated token revokes every session for that user: the
    only way an old token can be presented is if it leaked.
    """
    if not raw_token:
        raise AuthError("invalid_refresh", "No refresh token.")
    digest = hash_token(raw_token)
    row = query_one("SELECT * FROM refresh_tokens WHERE token_hash = ?", (digest,))
    if row is None:
        raise AuthError("invalid_refresh", "Session not found.")
    if row.get("revoked_at"):
        user_id = row["user_id"]
        execute(
            "UPDATE refresh_tokens SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
            (now_iso(), user_id),
        )
        record_audit(
            actor=Principal(user_id=user_id, username="", role=""),
            action="refresh_reuse",
            allowed=False,
            target=user_id,
            ip=ip,
            detail="a rotated refresh token was presented again",
        )
        raise AuthError("invalid_refresh", "Session has already been used. Sign in again.")
    if seconds_until(row["expires_at"]) <= 0:
        raise AuthError("invalid_refresh", "Session expired. Sign in again.")

    user = get_user(row["user_id"])
    if user is None or not int(user.get("is_active") or 0):
        raise AuthError("disabled", "This account is disabled.", status_code=403)

    principal = principal_for(user)
    access, ttl = create_access_token(
        user_id=principal.user_id,
        username=principal.username,
        role=principal.role,
        student_id=principal.student_id,
        department=user.get("department"),
        departments=list(principal.departments),
        cohorts=list(principal.cohorts),
    )
    raw_new, new_hash, new_expires = new_refresh_token()
    execute(
        "UPDATE refresh_tokens SET revoked_at = ?, replaced_by = ? WHERE token_hash = ?",
        (now_iso(), new_hash, digest),
    )
    execute(
        """
        INSERT INTO refresh_tokens
            (token_hash, user_id, issued_at, expires_at, revoked_at, replaced_by, ip, user_agent)
        VALUES (?, ?, ?, ?, NULL, NULL, ?, ?)
        """,
        (new_hash, principal.user_id, now_iso(), new_expires, ip[:64], (user_agent or "")[:255] or None),
    )
    return TokenBundle(
        access_token=access, refresh_token=raw_new, expires_in=ttl,
        user=_user_public(user),
    )


def logout(raw_token: str | None, actor: Principal | None = None, ip: str = "") -> bool:
    """Revoke one refresh token (and every token for the user when asked)."""
    if not raw_token:
        return False
    digest = hash_token(raw_token)
    row = query_one("SELECT user_id, revoked_at FROM refresh_tokens WHERE token_hash = ?", (digest,))
    if row is None:
        return False
    execute("UPDATE refresh_tokens SET revoked_at = ? WHERE token_hash = ?", (now_iso(), digest))
    record_audit(
        actor=actor, action="logout", allowed=True, target=row["user_id"], ip=ip
    )
    return True


def logout_all(user_id: str, actor: Principal | None = None, ip: str = "") -> int:
    rows = query(
        "SELECT COUNT(*) AS n FROM refresh_tokens WHERE user_id = ? AND revoked_at IS NULL",
        (user_id,),
    )
    execute(
        "UPDATE refresh_tokens SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
        (now_iso(), user_id),
    )
    record_audit(actor=actor, action="logout_all", allowed=True, target=user_id, ip=ip)
    return int(rows[0]["n"]) if rows else 0


# --------------------------------------------------------------------------
# Administration
# --------------------------------------------------------------------------


def create_user(
    *,
    actor: Principal | None,
    username: str,
    email: str,
    password: str,
    role: str,
    student_id: str | None = None,
    department: str | None = None,
    cohort: str | None = None,
    assignments: list[tuple[str, str]] | None = None,
    ip: str = "",
) -> dict[str, Any]:
    """Create an account. Admin-only at the router; validation lives here."""
    role = (role or "").strip().lower()
    if role not in ALL_ROLES:
        raise AuthError("invalid_role", f"role must be one of {ALL_ROLES}", 422)
    username = (username or "").strip()
    email = (email or "").strip()
    if not username or not email:
        raise AuthError("invalid_user", "username and email are required.", 422)
    if len(password or "") < 8:
        raise AuthError("weak_password", "password must be at least 8 characters.", 422)
    if role == ROLE_STUDENT and not student_id:
        raise AuthError("invalid_user", "a student account needs a student_id.", 422)
    if find_user(username) is not None:
        raise AuthError("duplicate", f"username {username} already exists.", 409)

    user_id = uuid.uuid4().hex
    execute(
        """
        INSERT INTO users
            (id, username, email, password_hash, role, student_id, department,
             cohort, is_active, created_at, last_login)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, NULL)
        """,
        (
            user_id, username, email, hash_password(password), role,
            student_id, department, cohort, now_iso(),
        ),
    )
    if assignments:
        executemany(
            """
            INSERT IGNORE INTO staff_assignments (staff_id, scope_kind, scope_value, created_at)
            VALUES (?, ?, ?, ?)
            """,
            [(user_id, kind, value, now_iso()) for kind, value in assignments],
        )
    record_audit(
        actor=actor, action="user.create", allowed=True,
        target=f"{username} ({role})", ip=ip,
        detail=f"student_id={student_id} department={department}",
    )
    return _user_public(get_user(user_id) or {})


def set_active(
    actor: Principal | None, user_id: str, active: bool, ip: str = ""
) -> dict[str, Any]:
    user = get_user(user_id)
    if user is None:
        raise AuthError("not_found", "No such user.", 404)
    execute("UPDATE users SET is_active = ? WHERE id = ?", (1 if active else 0, user_id))
    if not active:
        # Disabling an account must also end the sessions it already holds.
        logout_all(user_id, actor=actor, ip=ip)
    record_audit(
        actor=actor, action="user.enable" if active else "user.disable", allowed=True,
        target=user["username"], ip=ip,
    )
    return _user_public(get_user(user_id) or user)


def reset_password(
    actor: Principal | None, user_id: str, new_password: str, ip: str = ""
) -> None:
    if len(new_password or "") < 8:
        raise AuthError("weak_password", "password must be at least 8 characters.", 422)
    user = get_user(user_id)
    if user is None:
        raise AuthError("not_found", "No such user.", 404)
    execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (hash_password(new_password), user_id),
    )
    logout_all(user_id, actor=actor, ip=ip)
    record_audit(
        actor=actor, action="user.reset_password", allowed=True,
        target=user["username"], ip=ip,
    )


def change_role(
    actor: Principal | None,
    user_id: str,
    role: str,
    student_id: str | None = None,
    ip: str = "",
) -> dict[str, Any]:
    role = (role or "").strip().lower()
    if role not in ALL_ROLES:
        raise AuthError("invalid_role", f"role must be one of {ALL_ROLES}", 422)
    user = get_user(user_id)
    if user is None:
        raise AuthError("not_found", "No such user.", 404)
    execute(
        "UPDATE users SET role = ?, student_id = COALESCE(?, student_id) WHERE id = ?",
        (role, student_id, user_id),
    )
    # A role change invalidates existing sessions: a token that still says
    # "student" must not keep staff access after the promotion.
    logout_all(user_id, actor=actor, ip=ip)
    record_audit(
        actor=actor, action="user.role_change", allowed=True,
        target=user["username"], ip=ip, detail=f"{user['role']} -> {role}",
    )
    return _user_public(get_user(user_id) or user)


def set_assignments(
    actor: Principal | None,
    user_id: str,
    assignments: list[tuple[str, str]],
    ip: str = "",
) -> list[dict[str, Any]]:
    execute("DELETE FROM staff_assignments WHERE staff_id = ?", (user_id,))
    if assignments:
        executemany(
            """
            INSERT IGNORE INTO staff_assignments (staff_id, scope_kind, scope_value, created_at)
            VALUES (?, ?, ?, ?)
            """,
            [(user_id, kind, value, now_iso()) for kind, value in assignments],
        )
    record_audit(
        actor=actor, action="staff.assignments", allowed=True, target=user_id, ip=ip,
        detail=str(assignments)[:500],
    )
    return staff_assignments_for(user_id)


# --------------------------------------------------------------------------
# Seeding
# --------------------------------------------------------------------------

_HASH_CACHE: dict[str, str] = {}


def _demo_hash(password: str) -> str:
    """Hash a demo password once per process.

    All seeded demo accounts share one password, so re-hashing it 300 times at
    every fresh schema would cost ~25 s for no benefit. Real accounts created
    through the admin endpoint are hashed individually.
    """
    if password not in _HASH_CACHE:
        _HASH_CACHE[password] = hash_password(password)
    return _HASH_CACHE[password]


DEMO_STAFF: tuple[tuple[str, str], ...] = (
    ("staff.cse", "Computer Science"),
    ("staff.ece", "Electronics and Communication"),
    ("staff.mech", "Mechanical"),
)


def seed_accounts(force: bool = False) -> dict[str, int]:
    """Create the demo accounts, idempotently and in bulk.

    One admin, three department staff, one login per student and the read-only
    harness account. Safe to call on every startup: existing usernames are read
    in one query and skipped, the rest are inserted with a single executemany.
    That matters because the test suite runs migrations and this seeding against
    a fresh schema for every database test, and a per-student lookup loop made
    that cost seconds instead of milliseconds.
    """
    if not (settings.demo_mode or force):
        return {"created": 0, "skipped": 0}

    digest = _demo_hash(settings.demo_password)
    existing = {row["username"] for row in query("SELECT username FROM users")}
    stamp = now_iso()
    wanted: list[tuple] = []
    assignments: list[tuple] = []

    def _add(
        username: str,
        email: str,
        role: str,
        *,
        student_id: str | None = None,
        department: str | None = None,
    ) -> str | None:
        if username in existing:
            return None
        existing.add(username)
        user_id = uuid.uuid4().hex
        wanted.append(
            (user_id, username, email, digest, role, student_id, department, None, 1, stamp)
        )
        return user_id

    _add("admin", "admin@amypo.local", ROLE_ADMIN)
    _add("harness", "harness@amypo.local", ROLE_EVAL)
    for username, department in DEMO_STAFF:
        staff_id = _add(
            username, f"{username}@amypo.local", ROLE_STAFF, department=department
        )
        if staff_id:
            assignments.append((staff_id, "department", department, stamp))

    # One login per student. Username is the student id, lowercased, so the
    # demo script can say "sign in as s102" without a lookup table.
    students = query("SELECT student_id, department, email FROM students")
    for row in students:
        sid = row["student_id"]
        _add(
            sid.lower(),
            row.get("email") or f"{sid.lower()}@amypo.local",
            ROLE_STUDENT,
            student_id=sid,
            department=row["department"],
        )

    if wanted:
        executemany(
            """
            INSERT IGNORE INTO users
                (id, username, email, password_hash, role, student_id, department,
                 cohort, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            wanted,
        )
    if assignments:
        executemany(
            """
            INSERT IGNORE INTO staff_assignments
                (staff_id, scope_kind, scope_value, created_at)
            VALUES (?, ?, ?, ?)
            """,
            assignments,
        )

    created = len(wanted)
    if created:
        log.info("seeded %d demo accounts", created)
    return {"created": created, "skipped": max(0, len(students) + 4 - created)}
