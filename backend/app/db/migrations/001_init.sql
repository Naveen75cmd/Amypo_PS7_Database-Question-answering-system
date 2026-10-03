-- AMYPO Campus Assistant schema (SQLite).
-- Plain SQL, applied in filename order by app.db.migrate. All statements are
-- idempotent so re-running the migration set is safe.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- --------------------------------------------------------------------------
-- Structured campus data
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS students (
    student_id      TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    department      TEXT NOT NULL,
    year            INTEGER NOT NULL,
    cgpa            REAL NOT NULL,
    backlogs        INTEGER NOT NULL DEFAULT 0,
    attendance_pct  REAL NOT NULL,
    communication_score REAL NOT NULL DEFAULT 0,
    project_count   INTEGER NOT NULL DEFAULT 0,
    email           TEXT,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS courses (
    course_id   TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    department  TEXT NOT NULL,
    credits     INTEGER NOT NULL DEFAULT 3,
    semester    INTEGER NOT NULL DEFAULT 1,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS enrollments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  TEXT NOT NULL REFERENCES students(student_id),
    course_id   TEXT NOT NULL REFERENCES courses(course_id),
    semester    INTEGER NOT NULL,
    score       REAL,
    grade       TEXT,
    project_grade REAL,
    coding_score  REAL,
    updated_at  TEXT NOT NULL,
    UNIQUE(student_id, course_id, semester)
);

CREATE TABLE IF NOT EXISTS grades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  TEXT NOT NULL REFERENCES students(student_id),
    course_id   TEXT NOT NULL REFERENCES courses(course_id),
    assessment  TEXT NOT NULL,
    score       REAL NOT NULL,
    max_score   REAL NOT NULL DEFAULT 100,
    weight      REAL NOT NULL DEFAULT 1,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attendance (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  TEXT NOT NULL REFERENCES students(student_id),
    course_id   TEXT NOT NULL REFERENCES courses(course_id),
    attended    INTEGER NOT NULL,
    held        INTEGER NOT NULL,
    percent     REAL NOT NULL,
    as_of       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schedules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id   TEXT NOT NULL REFERENCES courses(course_id),
    day_of_week TEXT NOT NULL,
    start_time  TEXT NOT NULL,
    end_time    TEXT NOT NULL,
    room        TEXT,
    faculty     TEXT,
    updated_at  TEXT NOT NULL
);

-- --------------------------------------------------------------------------
-- Skills
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS skills (
    skill_id    TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL,  -- language | framework | tool | soft | database | cloud
    description TEXT
);

CREATE TABLE IF NOT EXISTS student_skills (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id      TEXT NOT NULL REFERENCES students(student_id),
    skill_id        TEXT NOT NULL REFERENCES skills(skill_id),
    level           INTEGER NOT NULL,          -- 0..5
    evidence_source TEXT NOT NULL,             -- module | project | coding_test | self
    evidence_ref    TEXT,
    updated_at      TEXT NOT NULL,
    UNIQUE(student_id, skill_id)
);

-- --------------------------------------------------------------------------
-- Placement
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS companies (
    company_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    sector      TEXT,
    tier        TEXT,
    website     TEXT,
    description TEXT,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS company_roles (
    role_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id          INTEGER NOT NULL REFERENCES companies(company_id),
    title               TEXT NOT NULL,
    location            TEXT,
    package_lpa         REAL,
    min_cgpa            REAL NOT NULL DEFAULT 0,
    max_backlogs        INTEGER NOT NULL DEFAULT 0,
    min_attendance_pct  REAL NOT NULL DEFAULT 0,
    min_project_count   INTEGER NOT NULL DEFAULT 0,
    min_communication   REAL NOT NULL DEFAULT 0,
    allowed_departments TEXT NOT NULL DEFAULT '[]',  -- JSON array
    weights             TEXT NOT NULL DEFAULT '{}',  -- JSON: suitability weights
    updated_at          TEXT NOT NULL,
    UNIQUE(company_id, title)
);

CREATE TABLE IF NOT EXISTS role_requirements (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    role_id      INTEGER NOT NULL REFERENCES company_roles(role_id),
    skill_id     TEXT NOT NULL REFERENCES skills(skill_id),
    min_level    INTEGER NOT NULL,
    importance   REAL NOT NULL DEFAULT 1.0,  -- weight in suitability
    is_required  INTEGER NOT NULL DEFAULT 1, -- 1 = eligibility gate, 0 = preferred
    UNIQUE(role_id, skill_id)
);

-- --------------------------------------------------------------------------
-- Documents and chunks (retrieval)
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS documents (
    doc_id      TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    source_path TEXT NOT NULL,
    doc_type    TEXT NOT NULL,       -- md | txt | pdf | docx | csv | record_card
    content_hash TEXT NOT NULL,
    access_scope TEXT NOT NULL DEFAULT 'public',
    version     INTEGER NOT NULL DEFAULT 1,
    updated_at  TEXT NOT NULL,
    indexed_at  TEXT
);

CREATE TABLE IF NOT EXISTS chunks (
    record_id   TEXT PRIMARY KEY,     -- doc:<doc_id>#<n> | db:<table>:<pk>
    doc_id      TEXT NOT NULL,
    chunk_no    INTEGER NOT NULL,
    title       TEXT NOT NULL,
    section     TEXT,
    page        INTEGER,
    text        TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    access_scope TEXT NOT NULL DEFAULT 'public',
    content_hash TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    embedding   BLOB                 -- float32 little-endian, NULL if not encoded
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_scope ON chunks(access_scope);

-- --------------------------------------------------------------------------
-- Runtime: queries, traces, cache, routing, resources, evals
-- --------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS query_log (
    request_id  TEXT PRIMARY KEY,
    question    TEXT NOT NULL,
    user_id     TEXT,
    role        TEXT NOT NULL DEFAULT 'student',
    intent      TEXT,
    route       TEXT,
    answer      TEXT,
    confidence  REAL,
    groundedness REAL,
    abstained   INTEGER NOT NULL DEFAULT 0,
    degraded    INTEGER NOT NULL DEFAULT 0,
    latency_ms  REAL,
    estimated_cost REAL,
    feedback    INTEGER,              -- +1 / -1 thumbs
    trace_json  TEXT,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_query_log_created ON query_log(created_at);

CREATE TABLE IF NOT EXISTS cache_entries (
    cache_key    TEXT PRIMARY KEY,
    question     TEXT NOT NULL,
    normalized   TEXT NOT NULL,
    answer       TEXT NOT NULL,
    sources_json TEXT NOT NULL,
    confidence   REAL NOT NULL,
    access_scope TEXT NOT NULL,
    source_hashes TEXT NOT NULL,      -- JSON: record_id -> content hash
    hits         INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    expires_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS router_decisions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id   TEXT NOT NULL,
    query        TEXT NOT NULL,
    routed_to    TEXT NOT NULL,
    reasoning    TEXT NOT NULL,
    complexity   TEXT,
    intent       TEXT,
    features_json TEXT,
    latency_ms   REAL NOT NULL,
    estimated_cost REAL NOT NULL,
    always_cloud_cost REAL NOT NULL,
    oracle_route TEXT,
    ram_available_mb INTEGER,
    cpu_load_pct REAL,
    bandwidth_kbps INTEGER,
    api_quota_remaining INTEGER,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_router_created ON router_decisions(created_at);

CREATE TABLE IF NOT EXISTS resource_samples (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ram_available_mb INTEGER NOT NULL,
    cpu_load_pct REAL NOT NULL,
    bandwidth_kbps INTEGER NOT NULL,
    api_quota_remaining INTEGER NOT NULL,
    ollama_status TEXT,
    scenario     TEXT,
    sampled_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS eval_runs (
    run_id      TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,        -- retrieval | end_to_end | routing
    config_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    report_path TEXT,
    created_at  TEXT NOT NULL
);
