-- --------------------------------------------------------------------------
-- Local authentication and role-based access control.
--
-- Everything here is local: passwords are bcrypt hashes, sessions are
-- short-lived JWTs plus a revocable refresh token, and every denied action is
-- written to audit_log. No external identity provider is consulted.
--
-- The role lives on the user row and is copied into the token at login. A
-- request never gets to name its own role: route dependencies, retriever
-- filters and SQL templates all read it from the verified token.
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS users (
    id            VARCHAR(32)  NOT NULL PRIMARY KEY,
    username      VARCHAR(64)  NOT NULL,
    email         VARCHAR(191) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    -- admin | staff | student | eval (the last one is the machine account the
    -- organisers' evaluation harness authenticates as: read-only, public only).
    role          VARCHAR(16)  NOT NULL,
    student_id    VARCHAR(32)  NULL,
    department    VARCHAR(64)  NULL,
    cohort        VARCHAR(64)  NULL,
    is_active     TINYINT(1)   NOT NULL DEFAULT 1,
    created_at    VARCHAR(40)  NOT NULL,
    last_login    VARCHAR(40)  NULL,
    UNIQUE KEY uniq_users_username (username),
    UNIQUE KEY uniq_users_email (email),
    KEY idx_users_role (role),
    KEY idx_users_student (student_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- What a staff account is allowed to look at: whole departments, a cohort
-- label, or a specific company's placement criteria. Enforced in the route
-- dependencies and handed to the SQL templates as a parameterised scope.
CREATE TABLE IF NOT EXISTS staff_assignments (
    id          BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    staff_id    VARCHAR(32)  NOT NULL,
    scope_kind  VARCHAR(16)  NOT NULL,
    scope_value VARCHAR(191) NOT NULL,
    created_at  VARCHAR(40)  NOT NULL,
    UNIQUE KEY uniq_staff_scope (staff_id, scope_kind, scope_value),
    KEY idx_staff_assignments_staff (staff_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Opaque refresh tokens. Only the SHA-256 hash is stored, so a database read
-- cannot mint a session. Rotation keeps ``replaced_by`` pointing at the
-- successor, which is what makes reuse detection possible.
CREATE TABLE IF NOT EXISTS refresh_tokens (
    token_hash  VARCHAR(64)  NOT NULL PRIMARY KEY,
    user_id     VARCHAR(32)  NOT NULL,
    issued_at   VARCHAR(40)  NOT NULL,
    expires_at  VARCHAR(40)  NOT NULL,
    revoked_at  VARCHAR(40)  NULL,
    replaced_by VARCHAR(64)  NULL,
    ip          VARCHAR(64)  NULL,
    user_agent  VARCHAR(255) NULL,
    KEY idx_refresh_user (user_id),
    KEY idx_refresh_expiry (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- The control that makes the other controls auditable: who tried what, whether
-- it was allowed, and over which scope. A denied request is logged before the
-- 403 is raised.
CREATE TABLE IF NOT EXISTS audit_log (
    id         BIGINT       NOT NULL AUTO_INCREMENT PRIMARY KEY,
    actor_id   VARCHAR(32)  NULL,
    actor_role VARCHAR(16)  NULL,
    action     VARCHAR(64)  NOT NULL,
    target     VARCHAR(191) NULL,
    scope      VARCHAR(191) NULL,
    ip         VARCHAR(64)  NULL,
    allowed    TINYINT(1)   NOT NULL,
    detail     TEXT         NULL,
    created_at VARCHAR(40)  NOT NULL,
    KEY idx_audit_action (action),
    KEY idx_audit_actor (actor_id),
    KEY idx_audit_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Login throttling. A window query over this table is the rate limiter, so the
-- limit survives a process restart and needs no in-memory state.
CREATE TABLE IF NOT EXISTS login_attempts (
    id           BIGINT      NOT NULL AUTO_INCREMENT PRIMARY KEY,
    username     VARCHAR(64) NOT NULL,
    ip           VARCHAR(64) NULL,
    success      TINYINT(1)  NOT NULL,
    attempted_at VARCHAR(40) NOT NULL,
    KEY idx_attempts_user_time (username, attempted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
