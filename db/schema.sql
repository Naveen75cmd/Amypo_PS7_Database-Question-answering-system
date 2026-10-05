-- AMYPO Campus Assistant schema (MySQL 8, InnoDB, utf8mb4).
-- Applied in filename order by app.db.migrate and, on first container start, by
-- MySQL's /docker-entrypoint-initdb.d. Every statement is idempotent, so running
-- the migration set again is safe.
--
-- Type notes:
--   * Identifiers (student_id, course_id, record_id, ...) are VARCHAR, not TEXT,
--     because MySQL cannot index a TEXT primary key without a prefix length.
--   * Timestamps are stored as ISO-8601 VARCHAR rather than DATETIME. The whole
--     application writes and compares UTC strings, and DATETIME would silently
--     drop the timezone offset. An index on the VARCHAR still orders correctly
--     because ISO-8601 is lexicographically sortable.
--   * Embeddings live in FAISS, not here. This schema holds chunk text, metadata
--     and access_scope; a FAISS vector id maps back to chunks.record_id.

SET NAMES utf8mb4;

-- --------------------------------------------------------------------------
-- Structured campus data
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS students (
    student_id          VARCHAR(32)  NOT NULL PRIMARY KEY,
    name                VARCHAR(191) NOT NULL,
    department          VARCHAR(64)  NOT NULL,
    year                INT          NOT NULL,
    cgpa                DOUBLE       NOT NULL,
    backlogs            INT          NOT NULL DEFAULT 0,
    attendance_pct      DOUBLE       NOT NULL,
    communication_score DOUBLE       NOT NULL DEFAULT 0,
    project_count       INT          NOT NULL DEFAULT 0,
    email               VARCHAR(191),
    updated_at          VARCHAR(40)  NOT NULL,
    KEY idx_students_department (department),
    KEY idx_students_updated (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS courses (
    course_id   VARCHAR(32)  NOT NULL PRIMARY KEY,
    title       VARCHAR(191) NOT NULL,
    department  VARCHAR(64)  NOT NULL,
    credits     INT          NOT NULL DEFAULT 3,
    semester    INT          NOT NULL DEFAULT 1,
    updated_at  VARCHAR(40)  NOT NULL,
    KEY idx_courses_department (department)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS enrollments (
    id            BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    student_id    VARCHAR(32) NOT NULL,
    course_id     VARCHAR(32) NOT NULL,
    semester      INT NOT NULL,
    score         DOUBLE,
    grade         VARCHAR(8),
    project_grade DOUBLE,
    coding_score  DOUBLE,
    updated_at    VARCHAR(40) NOT NULL,
    UNIQUE KEY uq_enrollment (student_id, course_id, semester),
    KEY idx_enrollments_student (student_id),
    KEY idx_enrollments_course (course_id),
    CONSTRAINT fk_enrollments_student FOREIGN KEY (student_id) REFERENCES students(student_id),
    CONSTRAINT fk_enrollments_course FOREIGN KEY (course_id) REFERENCES courses(course_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS grades (
    id          BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    student_id  VARCHAR(32) NOT NULL,
    course_id   VARCHAR(32) NOT NULL,
    assessment  VARCHAR(64) NOT NULL,
    score       DOUBLE NOT NULL,
    max_score   DOUBLE NOT NULL DEFAULT 100,
    weight      DOUBLE NOT NULL DEFAULT 1,
    recorded_at VARCHAR(40) NOT NULL,
    KEY idx_grades_student (student_id),
    KEY idx_grades_course (course_id),
    CONSTRAINT fk_grades_student FOREIGN KEY (student_id) REFERENCES students(student_id),
    CONSTRAINT fk_grades_course FOREIGN KEY (course_id) REFERENCES courses(course_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS attendance (
    id         BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    student_id VARCHAR(32) NOT NULL,
    course_id  VARCHAR(32) NOT NULL,
    attended   INT NOT NULL,
    held       INT NOT NULL,
    percent    DOUBLE NOT NULL,
    as_of      VARCHAR(40) NOT NULL,
    KEY idx_attendance_student (student_id),
    KEY idx_attendance_course (course_id),
    CONSTRAINT fk_attendance_student FOREIGN KEY (student_id) REFERENCES students(student_id),
    CONSTRAINT fk_attendance_course FOREIGN KEY (course_id) REFERENCES courses(course_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS schedules (
    id          BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    course_id   VARCHAR(32) NOT NULL,
    day_of_week VARCHAR(16) NOT NULL,
    start_time  VARCHAR(8) NOT NULL,
    end_time    VARCHAR(8) NOT NULL,
    room        VARCHAR(64),
    faculty     VARCHAR(191),
    updated_at  VARCHAR(40) NOT NULL,
    KEY idx_schedules_course (course_id),
    CONSTRAINT fk_schedules_course FOREIGN KEY (course_id) REFERENCES courses(course_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- --------------------------------------------------------------------------
-- Skills
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS skills (
    skill_id    VARCHAR(64)  NOT NULL PRIMARY KEY,
    name        VARCHAR(191) NOT NULL,
    category    VARCHAR(32)  NOT NULL,  -- language | framework | tool | soft | database | cloud
    description TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS student_skills (
    id              BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    student_id      VARCHAR(32) NOT NULL,
    skill_id        VARCHAR(64) NOT NULL,
    level           INT NOT NULL,                 -- 0..5
    evidence_source VARCHAR(32) NOT NULL,         -- module | project | coding_test | self
    evidence_ref    VARCHAR(64),
    updated_at      VARCHAR(40) NOT NULL,
    UNIQUE KEY uq_student_skill (student_id, skill_id),
    KEY idx_student_skills_student (student_id),
    KEY idx_student_skills_skill (skill_id),
    CONSTRAINT fk_student_skills_student FOREIGN KEY (student_id) REFERENCES students(student_id),
    CONSTRAINT fk_student_skills_skill FOREIGN KEY (skill_id) REFERENCES skills(skill_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- --------------------------------------------------------------------------
-- Placement
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS companies (
    company_id  BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(191) NOT NULL UNIQUE,
    sector      VARCHAR(64),
    tier        VARCHAR(8),
    website     VARCHAR(191),
    description TEXT,
    updated_at  VARCHAR(40) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS company_roles (
    role_id             BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    company_id          BIGINT NOT NULL,
    title               VARCHAR(191) NOT NULL,
    location            VARCHAR(191),
    package_lpa         DOUBLE,
    min_cgpa            DOUBLE NOT NULL DEFAULT 0,
    max_backlogs        INT NOT NULL DEFAULT 0,
    min_attendance_pct  DOUBLE NOT NULL DEFAULT 0,
    min_project_count   INT NOT NULL DEFAULT 0,
    min_communication   DOUBLE NOT NULL DEFAULT 0,
    allowed_departments JSON NOT NULL,             -- JSON array
    weights             JSON NOT NULL,             -- suitability weights
    updated_at          VARCHAR(40) NOT NULL,
    UNIQUE KEY uq_company_role (company_id, title),
    KEY idx_company_roles_company (company_id),
    CONSTRAINT fk_company_roles_company FOREIGN KEY (company_id) REFERENCES companies(company_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS role_requirements (
    id          BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    role_id     BIGINT NOT NULL,
    skill_id    VARCHAR(64) NOT NULL,
    min_level   INT NOT NULL,
    importance  DOUBLE NOT NULL DEFAULT 1.0,
    is_required TINYINT(1) NOT NULL DEFAULT 1,
    UNIQUE KEY uq_role_requirement (role_id, skill_id),
    KEY idx_role_requirements_role (role_id),
    CONSTRAINT fk_role_requirements_role FOREIGN KEY (role_id) REFERENCES company_roles(role_id),
    CONSTRAINT fk_role_requirements_skill FOREIGN KEY (skill_id) REFERENCES skills(skill_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- --------------------------------------------------------------------------
-- Documents and chunks (retrieval). Vector embeddings live in FAISS; a FAISS
-- vector id maps back to chunks.record_id, and all text/metadata is read here.
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS documents (
    doc_id       VARCHAR(191) NOT NULL PRIMARY KEY,
    title        VARCHAR(255) NOT NULL,
    source_path  VARCHAR(512) NOT NULL,
    doc_type     VARCHAR(16)  NOT NULL,       -- md | txt | pdf | docx | csv | record_card
    content_hash VARCHAR(64)  NOT NULL,
    access_scope VARCHAR(64)  NOT NULL DEFAULT 'public',
    version      INT NOT NULL DEFAULT 1,
    updated_at   VARCHAR(40) NOT NULL,
    indexed_at   VARCHAR(40),
    KEY idx_documents_updated (updated_at),
    KEY idx_documents_scope (access_scope)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS chunks (
    record_id    VARCHAR(191) NOT NULL PRIMARY KEY,  -- doc:<doc_id>#<n> | db:<table>:<pk>
    doc_id       VARCHAR(191) NOT NULL,
    chunk_no     INT NOT NULL,
    title        VARCHAR(255) NOT NULL,
    section      VARCHAR(255),
    page         INT,
    text         MEDIUMTEXT NOT NULL,
    token_count  INT NOT NULL,
    access_scope VARCHAR(64) NOT NULL DEFAULT 'public',
    content_hash VARCHAR(64) NOT NULL,
    updated_at   VARCHAR(40) NOT NULL,
    KEY idx_chunks_doc (doc_id),
    KEY idx_chunks_scope (access_scope),
    KEY idx_chunks_updated (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- --------------------------------------------------------------------------
-- Runtime: queries, traces, cache, routing, resources, evals
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS query_log (
    request_id     VARCHAR(64) NOT NULL PRIMARY KEY,
    question       MEDIUMTEXT NOT NULL,
    user_id        VARCHAR(32),
    `role`         VARCHAR(16) NOT NULL DEFAULT 'student',
    intent         VARCHAR(32),
    route          VARCHAR(32),
    answer         MEDIUMTEXT,
    confidence     DOUBLE,
    groundedness   DOUBLE,
    abstained      TINYINT(1) NOT NULL DEFAULT 0,
    degraded       TINYINT(1) NOT NULL DEFAULT 0,
    latency_ms     DOUBLE,
    estimated_cost DOUBLE,
    feedback       INT,                     -- +1 / -1 thumbs
    trace_json     JSON,
    created_at     VARCHAR(40) NOT NULL,
    KEY idx_query_log_created (created_at),
    KEY idx_query_log_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS cache_entries (
    cache_key     VARCHAR(128) NOT NULL PRIMARY KEY,
    question      MEDIUMTEXT NOT NULL,
    normalized    MEDIUMTEXT NOT NULL,
    answer        MEDIUMTEXT NOT NULL,
    sources_json  JSON NOT NULL,
    confidence    DOUBLE NOT NULL,
    access_scope  VARCHAR(64) NOT NULL,
    source_hashes JSON NOT NULL,             -- record_id -> content hash
    hits          INT NOT NULL DEFAULT 0,
    created_at    VARCHAR(40) NOT NULL,
    expires_at    VARCHAR(40) NOT NULL,
    KEY idx_cache_expires (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS router_decisions (
    id                  BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    request_id          VARCHAR(64) NOT NULL,
    query               MEDIUMTEXT NOT NULL,
    routed_to           VARCHAR(32) NOT NULL,
    reasoning           TEXT NOT NULL,
    complexity          VARCHAR(16),
    intent              VARCHAR(32),
    features_json       JSON,
    latency_ms          DOUBLE NOT NULL,
    estimated_cost      DOUBLE NOT NULL,
    always_cloud_cost   DOUBLE NOT NULL,
    oracle_route        VARCHAR(32),
    ram_available_mb    INT,
    cpu_load_pct        DOUBLE,
    bandwidth_kbps      INT,
    api_quota_remaining INT,
    created_at          VARCHAR(40) NOT NULL,
    KEY idx_router_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS resource_samples (
    id                  BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    ram_available_mb    INT NOT NULL,
    cpu_load_pct        DOUBLE NOT NULL,
    bandwidth_kbps      INT NOT NULL,
    api_quota_remaining INT NOT NULL,
    ollama_status       VARCHAR(32),
    scenario            VARCHAR(32),
    sampled_at          VARCHAR(40) NOT NULL,
    KEY idx_resource_sampled (sampled_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS eval_runs (
    run_id       VARCHAR(64) NOT NULL PRIMARY KEY,
    kind         VARCHAR(32) NOT NULL,        -- retrieval | end_to_end | routing
    config_json  JSON NOT NULL,
    metrics_json JSON NOT NULL,
    report_path  VARCHAR(512),
    created_at   VARCHAR(40) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- --------------------------------------------------------------------------
-- Placement
-- --------------------------------------------------------------------------

-- Every cohort query ("who is eligible for X") is logged here, because a staff
-- query over many students' records is an accountability event. Single-student
-- eligibility checks are per-request and are not logged here.
CREATE TABLE IF NOT EXISTS cohort_queries (
    id           BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    kind         VARCHAR(32) NOT NULL,       -- eligibility | match | skill_gap | what_if
    query        MEDIUMTEXT NOT NULL,
    company      VARCHAR(191),
    role_title   VARCHAR(191),
    role_id      BIGINT,
    department   VARCHAR(64),
    user_id      VARCHAR(32),
    `role`       VARCHAR(16) NOT NULL DEFAULT 'staff',
    result_count INT NOT NULL DEFAULT 0,
    created_at   VARCHAR(40) NOT NULL,
    KEY idx_cohort_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
