-- Backfill for databases whose 001_init.sql was applied before the placement
-- tables existed. 001_init.sql already contains this table, so on a fresh
-- database this file is a no-op thanks to CREATE TABLE IF NOT EXISTS; it exists
-- only so an already-seeded database picks the table up from the migration
-- runner without a manual step.

SET NAMES utf8mb4;

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
    KEY idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
