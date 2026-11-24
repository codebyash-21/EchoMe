"""SQLite storage for EchoMe. Everything lives in one local file: data/echome.db."""
import os
import sqlite3
from contextlib import contextmanager

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CLIPS_DIR = os.path.join(DATA_DIR, "clips")
DB_PATH = os.path.join(DATA_DIR, "echome.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS user_profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    name TEXT NOT NULL,
    north_star TEXT,
    self_trust INTEGER NOT NULL DEFAULT 60
);
CREATE TABLE IF NOT EXISTS health_logs (
    date TEXT PRIMARY KEY,              -- YYYY-MM-DD
    sleep_hours REAL,
    resting_hr INTEGER,
    steps INTEGER,
    stress INTEGER                      -- 0-100
);
CREATE TABLE IF NOT EXISTS promises (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,           -- ISO datetime
    original_text TEXT NOT NULL,
    final_text TEXT NOT NULL,
    est_minutes INTEGER,
    capacity_minutes INTEGER,
    due_at TEXT,
    status TEXT NOT NULL DEFAULT 'active',   -- active | kept | broken | moved
    why_clip TEXT,                      -- file name in data/clips
    why_text TEXT
);
CREATE TABLE IF NOT EXISTS checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    text TEXT NOT NULL,
    mode TEXT,                          -- push | protect | gentle | neutral
    reply TEXT
);
CREATE TABLE IF NOT EXISTS about_me (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    text TEXT NOT NULL,
    temporary INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS manual_rules (
    key TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    evidence TEXT,
    status TEXT NOT NULL DEFAULT 'proposed'  -- proposed | confirmed | rejected
);
CREATE TABLE IF NOT EXISTS trust_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    delta INTEGER NOT NULL,
    reason TEXT
);
"""


def ensure_dirs():
    os.makedirs(CLIPS_DIR, exist_ok=True)


@contextmanager
def connect():
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with connect() as c:
        c.executescript(SCHEMA)


def rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def one(conn, sql, params=()):
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None


def wipe_everything():
    """'Forget everything': delete the database and every recorded clip."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    if os.path.isdir(CLIPS_DIR):
        for f in os.listdir(CLIPS_DIR):
            try:
                os.remove(os.path.join(CLIPS_DIR, f))
            except OSError:
                pass
    init_db()
