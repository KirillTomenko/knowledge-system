"""SQLite access layer.

Deliberately plain sqlite3 (no ORM) so the schema and every query are
visible in one place — matches the rest of the project's "explicit
pipeline over framework black box" style.
"""
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

DATABASE_PATH = os.getenv("DATABASE_PATH", "./data/knowledge.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snippets (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    document_id TEXT NOT NULL,
    snippet_text TEXT NOT NULL,
    FOREIGN KEY (document_id) REFERENCES documents(id)
);

CREATE TABLE IF NOT EXISTS qa_runs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT,
    sources_json TEXT,
    needs_review INTEGER NOT NULL DEFAULT 0,
    error TEXT
);

CREATE TABLE IF NOT EXISTS audit_runs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    action TEXT NOT NULL,
    input TEXT,
    output TEXT,
    status TEXT NOT NULL,
    error TEXT,
    duration_ms INTEGER
);
"""


def init_db() -> None:
    Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(SCHEMA)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# --- documents -------------------------------------------------------

def insert_document(title: str, text: str) -> str:
    doc_id = new_id()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO documents (id, created_at, title, text) VALUES (?, ?, ?, ?)",
            (doc_id, now_iso(), title, text),
        )
    return doc_id


def list_documents():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, created_at, length(text) AS chars FROM documents ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_document(document_id: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, title, created_at, text FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
    return dict(row) if row else None


# --- snippets ----------------------------------------------------------

def insert_snippet(document_id: str, snippet_text: str) -> str:
    snip_id = new_id()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO snippets (id, created_at, document_id, snippet_text) VALUES (?, ?, ?, ?)",
            (snip_id, now_iso(), document_id, snippet_text),
        )
    return snip_id


def all_snippets():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT s.id, s.document_id, s.snippet_text, d.title as document_title "
            "FROM snippets s JOIN documents d ON s.document_id = d.id"
        ).fetchall()
    return [dict(r) for r in rows]


# --- qa_runs -------------------------------------------------------------

def insert_qa_run(question, answer, sources_json, needs_review, error=None) -> str:
    qa_id = new_id()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO qa_runs (id, created_at, question, answer, sources_json, needs_review, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (qa_id, now_iso(), question, answer, sources_json, int(needs_review), error),
        )
    return qa_id


def list_qa_runs(limit: int = 100, needs_review_only: bool = False):
    query = "SELECT * FROM qa_runs"
    if needs_review_only:
        query += " WHERE needs_review = 1"
    query += " ORDER BY created_at DESC LIMIT ?"
    with get_conn() as conn:
        rows = conn.execute(query, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_qa_run(qa_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM qa_runs WHERE id = ?", (qa_id,)).fetchone()
    return dict(row) if row else None


# --- audit_runs ------------------------------------------------------------

def insert_audit_run(action, input_data, output_data, status, error, duration_ms) -> str:
    audit_id = new_id()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO audit_runs (id, created_at, action, input, output, status, error, duration_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (audit_id, now_iso(), action, input_data, output_data, status, error, duration_ms),
        )
    return audit_id


def list_audit_runs(limit: int = 100):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_runs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
