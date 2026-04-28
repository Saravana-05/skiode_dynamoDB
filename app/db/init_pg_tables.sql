-- ============================================================
-- PostgreSQL table definitions for FastAPI service
-- Run once: psql -d <db> -f init_pg_tables.sql
-- ============================================================


-- ── event_log ─────────────────────────────────────────────────
-- Stores form submissions with fields as a JSON string (TEXT)
CREATE TABLE IF NOT EXISTS event_log (
    id          VARCHAR PRIMARY KEY,
    name        VARCHAR NOT NULL,
    fields      TEXT,               -- JSON string  e.g. '[{"field_id":...}]'
    created_at  VARCHAR
);
CREATE INDEX IF NOT EXISTS idx_event_log_name       ON event_log (name);
CREATE INDEX IF NOT EXISTS idx_event_log_created_at ON event_log (created_at);


-- ── employee_details ──────────────────────────────────────────
-- Each employee field stored as its own column (not JSON)
CREATE TABLE IF NOT EXISTS employee_details (
    id                  VARCHAR PRIMARY KEY,
    form_name           VARCHAR,
    event_log_id        VARCHAR,            -- FK reference to event_log.id
    employee_name       VARCHAR,
    employee_age        NUMERIC,
    employee_salary     NUMERIC,
    employee_dept       VARCHAR,
    employee_experience NUMERIC,
    employee_region     VARCHAR,
    created_at          VARCHAR
);
CREATE INDEX IF NOT EXISTS idx_emp_dept   ON employee_details (employee_dept);
CREATE INDEX IF NOT EXISTS idx_emp_region ON employee_details (employee_region);


-- ── datastore_schemas ─────────────────────────────────────────
-- Stores user-defined table schemas for the dynamic datastore
CREATE TABLE IF NOT EXISTS datastore_schemas (
    table_name  VARCHAR PRIMARY KEY,
    schema      TEXT NOT NULL,      -- JSON string  e.g. '[{"field_id":...,"type":...}]'
    created_at  VARCHAR
);
