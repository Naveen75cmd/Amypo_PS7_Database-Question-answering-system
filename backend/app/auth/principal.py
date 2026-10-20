"""Who is calling, and what that identity is allowed to see.

A :class:`Principal` is built once per request from a verified token and then
passed down as an ordinary argument. Nothing downstream re-reads the headers,
and nothing downstream accepts a role from the caller: the retrieval filter, the
SQL templates, the cache key and the query log all read the role and the student
id off this object.

Visibility levels stored on ``documents``/``chunks`` are ``public``, ``staff``,
``admin`` and ``student:<id>``. A principal's readable set is derived here, once
per request, and cached for the department lookup so the derivation stays cheap.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

ROLE_ADMIN = "admin"
ROLE_STAFF = "staff"
ROLE_STUDENT = "student"
# Read-only machine account for the organisers' evaluation harness.
ROLE_EVAL = "eval"

ALL_ROLES = (ROLE_ADMIN, ROLE_STAFF, ROLE_STUDENT, ROLE_EVAL)

_DEPT_CACHE_TTL_S = 60.0
_dept_lock = threading.Lock()
_dept_cache: dict[str, tuple[float, frozenset[str]]] = {}


def invalidate_department_cache() -> None:
    """Test hook: forget the department -> student-id mapping."""
    with _dept_lock:
        _dept_cache.clear()


@dataclass(frozen=True)
class Principal:
    """A verified caller. Constructed from a token, never from a request body."""

    user_id: str
    username: str
    role: str
    student_id: str | None = None
    departments: tuple[str, ...] = ()
    cohorts: tuple[str, ...] = ()
    # The harness account: read-only, public scope only, no personal records.
    is_service: bool = False

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def is_staff(self) -> bool:
        """Staff *or* admin: the roles that may run cohort queries."""
        return self.role in (ROLE_STAFF, ROLE_ADMIN)

    @property
    def is_student(self) -> bool:
        return self.role == ROLE_STUDENT

    def has_role(self, *roles: str) -> bool:
        return self.role in roles

    @property
    def display_name(self) -> str:
        if self.is_service:
            return "evaluation harness"
        return self.username or self.user_id

    @property
    def cache_scope(self) -> str:
        """The scope a cached answer belongs to.

        Never shared across roles: an admin answer may cite an admin-only
        document, so admin and staff do not share a key even though staff is a
        subset of admin's visibility.
        """
        if self.role == ROLE_ADMIN:
            return "admin"
        if self.role == ROLE_STAFF:
            return "staff"
        if self.role == ROLE_STUDENT and self.student_id:
            return f"student:{self.student_id}"
        return "public"

    def describe(self) -> dict[str, Any]:
        """Searchable/auditable description, with no secrets in it."""
        return {
            "user_id": self.user_id,
            "username": self.username,
            "role": self.role,
            "student_id": self.student_id,
            "departments": list(self.departments),
        }


def _students_in_departments(departments: tuple[str, ...]) -> frozenset[str]:
    """Student ids in the given departments, cached for ``_DEPT_CACHE_TTL_S``."""
    key = "|".join(sorted(departments))
    now = time.monotonic()
    with _dept_lock:
        cached = _dept_cache.get(key)
        if cached and now - cached[0] < _DEPT_CACHE_TTL_S:
            return cached[1]

    from ..db import query

    placeholders = ", ".join("?" for _ in departments)
    rows = query(
        f"SELECT student_id FROM students WHERE department IN ({placeholders})",
        tuple(departments),
    )
    ids = frozenset(row["student_id"] for row in rows)

    with _dept_lock:
        _dept_cache[key] = (now, ids)
    return ids


def allowed_student_ids(principal: Principal) -> frozenset[str] | None:
    """The student records this principal may read, or ``None`` for all of them.

    Admin: every record (access is still written to the audit log when a row
    rather than an aggregate is read). Staff: only students in the departments
    the account is assigned to; a staff account with no assignment sees none of
    them, which fails closed rather than open. Student: only their own. The
    service account: none, it reads public documents only.
    """
    if principal.is_admin:
        return None
    if principal.is_service or principal.role == ROLE_EVAL:
        return frozenset()
    if principal.role == ROLE_STAFF:
        if not principal.departments:
            return frozenset()
        return _students_in_departments(principal.departments)
    if principal.student_id:
        return frozenset({principal.student_id})
    return frozenset()


def allowed_visibility(principal: Principal) -> frozenset[str] | None:
    """Document visibility levels this principal may retrieve, or ``None`` = all."""
    if principal.is_admin:
        return None
    if principal.role == ROLE_STAFF:
        return frozenset({"public", "staff"})
    if principal.role == ROLE_STUDENT or principal.student_id:
        return frozenset({"public"})
    return frozenset({"public"})


def may_read_student(principal: Principal, student_id: str | None) -> bool:
    """Whether this principal may read a specific student's records."""
    if not student_id:
        return True
    if principal.is_admin:
        return True
    if principal.is_staff:
        allowed = allowed_student_ids(principal)
        return allowed is None or student_id in allowed
    if principal.is_service:
        return False
    return principal.student_id == student_id


def permissions_for(principal: Principal) -> dict[str, bool]:
    """Capability map for the UI, derived from the role.

    This is presentation only -- every one of these is also enforced by a route
    dependency, so hiding a button is a convenience, never the control.
    """
    admin = principal.is_admin
    staff = principal.is_staff
    student = principal.is_student and bool(principal.student_id)
    service = principal.is_service
    return {
        "chat": True,
        "own_records": student,
        "staff_docs": staff,
        "admin_docs": admin,
        "placement_own": student,
        "placement_cohort": staff,
        "placement_weights": admin,
        "criteria_edit": staff,
        "ingest": staff,
        "ingest_approve": admin,
        "user_admin": admin,
        "router_config": admin,
        "monitoring_full": admin,
        "monitoring_read": staff,
        "audit_log": admin,
        "eval_run": admin,
        "eval_view": staff,
        "simulator": admin,
        "service_account": service,
    }


def visibility_for_path(relative_parts: tuple[str, ...]) -> str:
    """Document visibility from its location under ``data/raw``.

    ``data/raw/staff/...`` is staff-only, ``data/raw/admin/...`` is admin-only,
    everything else is public. Kept as a path rule rather than front-matter so a
    document cannot be made private by a typo in its header: the directory is
    the access decision, and it is visible in the tree.
    """
    lowered = {part.lower() for part in relative_parts}
    if "admin" in lowered:
        return "admin"
    if "staff" in lowered:
        return "staff"
    return "public"
