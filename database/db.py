"""Database adapter for SQLite (local development) and PostgreSQL (deployment)."""
from __future__ import annotations

import json
import os
import re
import sqlite3
from threading import Lock
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("SQLITE_PATH", BASE_DIR / "database" / "netsage.db"))
SCHEMA = BASE_DIR / "database" / "schema.sql"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
_USE_POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://"))
_PG_POOL = None
_PG_POOL_LOCK = Lock()


def _pg_url() -> str:
    url = DATABASE_URL
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    if "connect_timeout=" not in url:
        url += ("&" if "?" in url else "?") + "connect_timeout=10"
    return url


class _PostgresConnection:
    """Small DB-API wrapper keeping the existing helper API portable."""
    def __init__(self, raw, pool):
        self.raw = raw
        self.pool = pool
        self._closed = False

    def execute(self, sql: str, params: Any = None):
        from psycopg2.extras import DictCursor
        sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO")
        if "INSERT INTO cases" in sql and "ON CONFLICT" not in sql.upper():
            sql = sql.rstrip().rstrip(";") + " ON CONFLICT (case_id) DO NOTHING"
        if isinstance(params, dict):
            sql = re.sub(r":([A-Za-z_][A-Za-z0-9_]*)", r"%(\1)s", sql)
        else:
            sql = re.sub(r"\?", "%s", sql)
        cur = self.raw.cursor(cursor_factory=DictCursor)
        cur.execute(sql, params or ())
        return cur

    def executescript(self, script: str):
        cur = self.raw.cursor()
        for statement in script.split(";"):
            if statement.strip():
                cur.execute(statement)
        return cur

    def commit(self):
        self.raw.commit()

    def close(self):
        if not self._closed:
            self.raw.rollback()
            self.pool.putconn(self.raw)
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self.raw.rollback()
        else:
            self.raw.commit()
        self.close()


def get_connection():
    if _USE_POSTGRES:
        try:
            from psycopg2.pool import ThreadedConnectionPool
        except ImportError as exc:
            raise RuntimeError("PostgreSQL support requires psycopg2-binary. Install requirements.txt.") from exc
        global _PG_POOL
        if _PG_POOL is None:
            with _PG_POOL_LOCK:
                if _PG_POOL is None:
                    min_connections = max(1, int(os.getenv("PG_POOL_MIN", "1")))
                    max_connections = max(
                        min_connections,
                        int(os.getenv("PG_POOL_MAX", "4")),
                    )
                    _PG_POOL = ThreadedConnectionPool(
                        min_connections,
                        max_connections,
                        dsn=_pg_url(),
                    )
        return _PostgresConnection(_PG_POOL.getconn(), _PG_POOL)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def _schema_postgres() -> str:
    return """
    CREATE TABLE IF NOT EXISTS cases (
      case_id TEXT PRIMARY KEY, category TEXT NOT NULL, symptom TEXT NOT NULL,
      topology TEXT NOT NULL, show_output TEXT NOT NULL, expected_fault TEXT NOT NULL,
      osi_layer TEXT NOT NULL, concept TEXT NOT NULL,
      severity TEXT NOT NULL CHECK (severity IN ('Low','Medium','High','Critical'))
    );
    CREATE TABLE IF NOT EXISTS diagnoses (
      id BIGSERIAL PRIMARY KEY, case_ref TEXT, category TEXT,
      symptom TEXT NOT NULL, topology TEXT, show_output TEXT, root_cause TEXT,
      osi_layer TEXT, confidence TEXT CHECK (confidence IN ('Low','Medium','High')),
      evidence TEXT, next_command TEXT, fix_steps TEXT, rule_results TEXT,
      ai_conflict INTEGER DEFAULT 0, seed_key TEXT,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    ALTER TABLE diagnoses ADD COLUMN IF NOT EXISTS seed_key TEXT;
    CREATE UNIQUE INDEX IF NOT EXISTS idx_diagnoses_seed_key
      ON diagnoses(seed_key) WHERE seed_key IS NOT NULL;
    CREATE TABLE IF NOT EXISTS reviews (
      id BIGSERIAL PRIMARY KEY,
      diagnosis_id BIGINT NOT NULL REFERENCES diagnoses(id) ON DELETE CASCADE,
      decision TEXT NOT NULL CHECK (decision IN ('accept','edit','reject')),
      human_root_cause TEXT, human_correction TEXT, reason TEXT,
      verified_before TEXT, fix_applied TEXT, verified_after TEXT,
      reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      CONSTRAINT one_review_per_diagnosis UNIQUE (diagnosis_id)
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_reviews_one_per_diagnosis ON reviews(diagnosis_id);
    CREATE OR REPLACE VIEW responsible_ai_log AS
    SELECT d.id AS diagnosis_id, d.case_ref, d.category,
      d.root_cause AS ai_diagnosis, d.confidence AS ai_confidence,
      r.decision AS human_decision, r.human_root_cause AS human_diagnosis,
      r.reason, r.reviewed_at
    FROM diagnoses d LEFT JOIN reviews r ON r.diagnosis_id = d.id
    ORDER BY r.reviewed_at DESC;
    """


def init_db():
    conn = get_connection()
    try:
        if _USE_POSTGRES:
            conn.executescript(_schema_postgres())
        else:
            with open(SCHEMA, encoding="utf-8") as f:
                conn.executescript(f.read())
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(diagnoses)")
            }
            if "seed_key" not in columns:
                conn.execute("ALTER TABLE diagnoses ADD COLUMN seed_key TEXT")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_diagnoses_seed_key "
                "ON diagnoses(seed_key)"
            )
            conn.execute("DROP VIEW IF EXISTS responsible_ai_log")
            conn.execute(
                """CREATE VIEW responsible_ai_log AS
                SELECT d.id AS diagnosis_id, d.case_ref, d.category,
                  d.root_cause AS ai_diagnosis, d.confidence AS ai_confidence,
                  r.decision AS human_decision, r.human_root_cause AS human_diagnosis,
                  r.reason, r.reviewed_at
                FROM diagnoses d LEFT JOIN reviews r ON r.diagnosis_id = d.id
                ORDER BY r.reviewed_at DESC"""
            )
        conn.commit()
    finally:
        conn.close()


def _insert_id(sql: str, params: tuple, conn=None) -> int:
    if _USE_POSTGRES:
        sql = sql.rstrip().rstrip(";") + " RETURNING id"
    if conn is not None:
        cur = conn.execute(sql, params)
        if _USE_POSTGRES:
            return int(cur.fetchone()["id"])
        return int(cur.lastrowid)
    with get_connection() as connection:
        cur = connection.execute(sql, params)
        if _USE_POSTGRES:
            return int(cur.fetchone()["id"])
        return int(cur.lastrowid)

# Cases

def insert_case(row: dict):
    sql = """INSERT OR IGNORE INTO cases
      (case_id, category, symptom, topology, show_output, expected_fault, osi_layer, concept, severity)
      VALUES (:case_id,:category,:symptom,:topology,:show_output,:expected_fault,:osi_layer,:concept,:severity)"""
    if _USE_POSTGRES:
        sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO") + " ON CONFLICT (case_id) DO NOTHING"
    with get_connection() as conn:
        conn.execute(sql, row)


def get_all_cases() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM cases ORDER BY case_id").fetchall()
    return [dict(r) for r in rows]


def get_case(case_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM cases WHERE case_id=?", (case_id,)).fetchone()
    return dict(row) if row else None

# Diagnoses

def insert_diagnosis(d: dict, conn=None) -> int:
    sql = """INSERT INTO diagnoses
      (case_ref, category, symptom, topology, show_output, root_cause, osi_layer,
       confidence, evidence, next_command, fix_steps, rule_results, ai_conflict)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"""
    params = (d.get("case_ref"), d.get("category"), d["symptom"], d.get("topology"),
      d.get("show_output"), d.get("root_cause"), d.get("osi_layer"), d.get("confidence"),
      json.dumps(d.get("evidence", [])), d.get("next_command"),
      json.dumps(d.get("fix_steps", [])), json.dumps(d.get("rule_results", [])),
      int(bool(d.get("ai_conflict", False))))
    return _insert_id(sql, params, conn)


def insert_seeded_diagnosis(d: dict, seed_key: str, conn) -> int | None:
    """Insert a built-in diagnosis once, using the caller's transaction."""
    conn.execute(
        """UPDATE diagnoses SET seed_key=?
           WHERE seed_key IS NULL AND case_ref=? AND category=? AND symptom=?
             AND topology=? AND show_output=? AND root_cause=?""",
        (seed_key, d.get("case_ref"), d.get("category"), d["symptom"],
         d.get("topology"), d.get("show_output"), d.get("root_cause")),
    )
    existing = conn.execute(
        "SELECT id FROM diagnoses WHERE seed_key=?",
        (seed_key,),
    ).fetchone()
    if existing:
        reviewed = conn.execute(
            "SELECT 1 FROM reviews WHERE diagnosis_id=?",
            (existing["id"],),
        ).fetchone()
        return None if reviewed else int(existing["id"])

    sql = """INSERT INTO diagnoses
      (case_ref, category, symptom, topology, show_output, root_cause, osi_layer,
       confidence, evidence, next_command, fix_steps, rule_results, ai_conflict, seed_key)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
    params = (d.get("case_ref"), d.get("category"), d["symptom"], d.get("topology"),
      d.get("show_output"), d.get("root_cause"), d.get("osi_layer"), d.get("confidence"),
      json.dumps(d.get("evidence", [])), d.get("next_command"),
      json.dumps(d.get("fix_steps", [])), json.dumps(d.get("rule_results", [])),
      int(bool(d.get("ai_conflict", False))), seed_key)
    if _USE_POSTGRES:
        sql += " ON CONFLICT (seed_key) WHERE seed_key IS NOT NULL DO NOTHING RETURNING id"
    else:
        sql = sql.replace("INSERT INTO", "INSERT OR IGNORE INTO")
    cur = conn.execute(sql, params)
    if _USE_POSTGRES:
        row = cur.fetchone()
        return int(row["id"]) if row else None
    return int(cur.lastrowid) if cur.rowcount else None


def _decode_diagnosis(row) -> dict | None:
    if not row:
        return None
    d = dict(row)
    for key in ("evidence", "fix_steps", "rule_results"):
        value = d.get(key)
        d[key] = json.loads(value or "[]") if isinstance(value, str) else (value or [])
    if hasattr(d.get("created_at"), "isoformat"):
        d["created_at"] = d["created_at"].isoformat(sep=" ")
    return d


def get_diagnosis(diag_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM diagnoses WHERE id=?", (diag_id,)).fetchone()
    return _decode_diagnosis(row)


def get_all_diagnoses() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT d.*, r.decision FROM diagnoses d LEFT JOIN reviews r ON r.diagnosis_id=d.id ORDER BY d.created_at DESC").fetchall()
    return [_decode_diagnosis(row) for row in rows]

# Reviews

def insert_review(r: dict, conn=None) -> int:
    sql = """INSERT INTO reviews
      (diagnosis_id, decision, human_root_cause, human_correction, reason,
       verified_before, fix_applied, verified_after) VALUES (?,?,?,?,?,?,?,?)"""
    params = (r["diagnosis_id"], r["decision"], r.get("human_root_cause"),
      r.get("human_correction"), r.get("reason"), r.get("verified_before"),
      r.get("fix_applied"), r.get("verified_after"))
    return _insert_id(sql, params, conn)


def get_review_for_diagnosis(diag_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM reviews WHERE diagnosis_id=?", (diag_id,)).fetchone()
    return dict(row) if row else None


def get_all_reviews() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("""SELECT r.*, d.symptom, d.category, d.root_cause AS ai_root_cause,
          d.confidence, d.case_ref FROM reviews r JOIN diagnoses d ON d.id=r.diagnosis_id
          ORDER BY r.reviewed_at DESC""").fetchall()
    result = []
    for row in rows:
        item = dict(row)
        if hasattr(item.get("reviewed_at"), "isoformat"):
            item["reviewed_at"] = item["reviewed_at"].isoformat(sep=" ")
        result.append(item)
    return result


def get_responsible_ai_log() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM responsible_ai_log").fetchall()
    result = []
    for row in rows:
        item = dict(row)
        if hasattr(item.get("reviewed_at"), "isoformat"):
            item["reviewed_at"] = item["reviewed_at"].isoformat(sep=" ")
        result.append(item)
    return result

# Dashboard

def get_dashboard_stats() -> dict:
    with get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
        accepted = conn.execute("SELECT COUNT(*) FROM reviews WHERE decision='accept'").fetchone()[0]
        edited = conn.execute("SELECT COUNT(*) FROM reviews WHERE decision='edit'").fetchone()[0]
        rejected = conn.execute("SELECT COUNT(*) FROM reviews WHERE decision='reject'").fetchone()[0]
        by_category = conn.execute("""SELECT d.category, COUNT(*) AS cnt FROM diagnoses d
          JOIN reviews r ON r.diagnosis_id=d.id GROUP BY d.category""").fetchall()
        by_severity = conn.execute("SELECT c.severity, COUNT(*) AS cnt FROM cases c GROUP BY c.severity").fetchall()
        confidence_dist = conn.execute("SELECT confidence, COUNT(*) AS cnt FROM diagnoses GROUP BY confidence").fetchall()
    return {"total": total, "accepted": accepted, "edited": edited, "rejected": rejected,
      "agreement_pct": round(accepted / total * 100, 1) if total else 0,
      "by_category": [dict(r) for r in by_category], "by_severity": [dict(r) for r in by_severity],
      "confidence": [dict(r) for r in confidence_dist]}


def check_database() -> bool:
    with get_connection() as conn:
        conn.execute("SELECT 1").fetchone()
    return True
