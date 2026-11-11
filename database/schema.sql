-- NetSage AI Database Schema

-- Pre-loaded troubleshooting case dataset
CREATE TABLE IF NOT EXISTS cases (
    case_id     TEXT PRIMARY KEY,
    category    TEXT NOT NULL,
    symptom     TEXT NOT NULL,
    topology    TEXT NOT NULL,
    show_output TEXT NOT NULL,
    expected_fault TEXT NOT NULL,
    osi_layer   TEXT NOT NULL,
    concept     TEXT NOT NULL,
    severity    TEXT NOT NULL CHECK(severity IN ('Low','Medium','High','Critical'))
);

-- AI-generated diagnoses (one per analysis run)
CREATE TABLE IF NOT EXISTS diagnoses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_ref        TEXT,                       -- NULL for free-form inputs
    category        TEXT,
    symptom         TEXT NOT NULL,
    topology        TEXT,
    show_output     TEXT,
    root_cause      TEXT,
    osi_layer       TEXT,
    confidence      TEXT CHECK(confidence IN ('Low','Medium','High')),
    evidence        TEXT,                       -- JSON array as text
    next_command    TEXT,
    fix_steps       TEXT,                       -- JSON array as text
    rule_results    TEXT,                       -- JSON array as text
    ai_conflict     INTEGER DEFAULT 0,          -- 1 if AI vs Rule checker disagree
    seed_key            TEXT,                      -- NULL for user-created diagnoses
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Human review decisions
CREATE TABLE IF NOT EXISTS reviews (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    diagnosis_id        INTEGER NOT NULL REFERENCES diagnoses(id),
    decision            TEXT NOT NULL CHECK(decision IN ('accept','edit','reject')),
    human_root_cause    TEXT,                   -- populated on edit
    human_correction    TEXT,                   -- free-text correction notes
    reason              TEXT,                   -- reason for edit/reject
    verified_before     TEXT,                   -- 'pass' | 'fail' | NULL
    fix_applied         TEXT,                   -- description of fix applied
    verified_after      TEXT,                   -- 'pass' | 'fail' | NULL
    reviewed_at         DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Responsible AI log view for every reviewed diagnosis
CREATE VIEW IF NOT EXISTS responsible_ai_log AS
SELECT
    d.id                AS diagnosis_id,
    d.case_ref,
    d.category,
    d.root_cause        AS ai_diagnosis,
    d.confidence        AS ai_confidence,
    r.decision          AS human_decision,
    r.human_root_cause  AS human_diagnosis,
    r.reason,
    r.reviewed_at
FROM diagnoses d
LEFT JOIN reviews r ON r.diagnosis_id = d.id
ORDER BY r.reviewed_at DESC;

CREATE UNIQUE INDEX IF NOT EXISTS idx_reviews_one_per_diagnosis ON reviews(diagnosis_id);
