"""Local authentication and role-based access control.

The public surface is deliberately small: a request becomes a
:class:`~app.auth.principal.Principal` (through ``app.auth.deps``), and every
route, retriever filter, SQL template and cache key reads its authority from
that object rather than from the request body.
"""

from .deps import get_principal, optional_principal, require
from .principal import (
    ALL_ROLES,
    ROLE_ADMIN,
    ROLE_EVAL,
    ROLE_STAFF,
    ROLE_STUDENT,
    Principal,
    allowed_student_ids,
    allowed_visibility,
    may_read_student,
    permissions_for,
)
from .security import TokenError, decode_access_token

__all__ = [
    "ALL_ROLES",
    "ROLE_ADMIN",
    "ROLE_EVAL",
    "ROLE_STAFF",
    "ROLE_STUDENT",
    "Principal",
    "TokenError",
    "allowed_student_ids",
    "allowed_visibility",
    "decode_access_token",
    "get_principal",
    "may_read_student",
    "optional_principal",
    "permissions_for",
    "require",
]
