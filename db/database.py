"""Database abstraction layer — SQLite for local dev, PostgreSQL for production."""

import asyncio
import logging
import re
import sqlite3

logger = logging.getLogger(__name__)


class Database:
    """Abstract database interface. Models.py uses ? placeholders everywhere.
    The PostgreSQL backend auto-converts ? → $1, $2, ... internally."""

    async def init(self) -> None:
        raise NotImplementedError

    async def execute_write(self, sql: str, params: tuple = ()) -> int:
        """Execute a write query. Returns lastrowid (or 0)."""
        raise NotImplementedError

    async def fetchone(self, sql: str, params: tuple = ()) -> dict | None:
        raise NotImplementedError

    async def fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError


class SQLiteDatabase(Database):
    """SQLite backend for local development."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._write_lock = asyncio.Lock()

    async def init(self) -> None:
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        async with self._write_lock:
            self._conn.executescript(SQLITE_SCHEMA)
            self._conn.commit()
        logger.info(f"SQLite database initialized at {self.db_path}")

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database not initialized. Call init() first.")
        return self._conn

    async def execute_write(self, sql: str, params: tuple = ()) -> int:
        async with self._write_lock:
            cursor = self.conn.execute(sql, params)
            self.conn.commit()
            if "RETURNING" in sql.upper():
                row = cursor.fetchone()
                return row[0] if row else 0
            return cursor.lastrowid or 0

    async def fetchone(self, sql: str, params: tuple = ()) -> dict | None:
        cursor = self.conn.execute(sql, params)
        row = cursor.fetchone()
        return dict(row) if row else None

    async def fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        cursor = self.conn.execute(sql, params)
        return [dict(r) for r in cursor.fetchall()]

    async def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


def _sqlite_to_pg(sql: str) -> str:
    """Convert SQLite SQL to PostgreSQL dialect."""
    # Replace ? placeholders with $1, $2, ...
    counter = [0]

    def replacer(match):
        counter[0] += 1
        return f"${counter[0]}"

    result = re.sub(r"\?", replacer, sql)
    # datetime('now') → NOW()
    result = result.replace("datetime('now')", "NOW()")
    # date('now') → CURRENT_DATE
    result = result.replace("date('now')", "CURRENT_DATE")
    return result


class PostgresDatabase(Database):
    """PostgreSQL backend for Railway production."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._pool = None

    async def init(self) -> None:
        import asyncpg
        self._pool = await asyncpg.create_pool(self.database_url, min_size=2, max_size=10)
        async with self._pool.acquire() as conn:
            await conn.execute(POSTGRES_SCHEMA)
        logger.info("PostgreSQL database initialized")

    async def execute_write(self, sql: str, params: tuple = ()) -> int:
        pg_sql = _sqlite_to_pg(sql)
        async with self._pool.acquire() as conn:
            if "RETURNING" in pg_sql.upper():
                result = await conn.fetchval(pg_sql, *params)
                return result or 0
            else:
                await conn.execute(pg_sql, *params)
                return 0

    async def fetchone(self, sql: str, params: tuple = ()) -> dict | None:
        pg_sql = _sqlite_to_pg(sql)
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(pg_sql, *params)
            return dict(row) if row else None

    async def fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        pg_sql = _sqlite_to_pg(sql)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(pg_sql, *params)
            return [dict(r) for r in rows]

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None


def create_database(database_url: str = "", database_path: str = "jiro.db") -> Database:
    """Factory: returns PostgreSQL if DATABASE_URL is set, otherwise SQLite."""
    if database_url:
        return PostgresDatabase(database_url)
    return SQLiteDatabase(database_path)


# ── SQLite Schema (unchanged from original) ──

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_profile (
    user_id INTEGER PRIMARY KEY,
    display_name TEXT NOT NULL DEFAULT '',
    timezone TEXT NOT NULL DEFAULT 'Asia/Tokyo',
    current_level TEXT NOT NULL DEFAULT 'N2',
    target_level TEXT NOT NULL DEFAULT 'fluent',
    daily_question_time TEXT NOT NULL DEFAULT '08:00',
    preferred_topics TEXT NOT NULL DEFAULT '[]',
    register_preference TEXT NOT NULL DEFAULT 'mixed' CHECK(register_preference IN ('casual', 'polite', 'mixed')),
    correction_intensity TEXT NOT NULL DEFAULT 'normal' CHECK(correction_intensity IN ('light', 'normal', 'strict')),
    mode TEXT NOT NULL DEFAULT 'conversation' CHECK(mode IN ('test_prep', 'conversation')),
    difficulty_ramp TEXT NOT NULL DEFAULT 'normal' CHECK(difficulty_ramp IN ('slow', 'normal', 'fast')),
    recurring_error_patterns TEXT NOT NULL DEFAULT '{}',
    learner_summary TEXT NOT NULL DEFAULT '',
    streak_count INTEGER NOT NULL DEFAULT 0,
    last_active TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS conversation_sessions (
    session_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at TEXT,
    mode TEXT NOT NULL DEFAULT 'conversation',
    topic_tags TEXT NOT NULL DEFAULT '[]',
    FOREIGN KEY (user_id) REFERENCES user_profile(user_id)
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'bot')),
    text TEXT NOT NULL,
    transcript TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES conversation_sessions(session_id)
);

CREATE TABLE IF NOT EXISTS grades (
    grade_id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL,
    overall_score INTEGER NOT NULL DEFAULT 0,
    grammar_score INTEGER NOT NULL DEFAULT 0,
    vocab_score INTEGER NOT NULL DEFAULT 0,
    pronunciation_score INTEGER NOT NULL DEFAULT 0,
    fluency_score INTEGER NOT NULL DEFAULT 0,
    naturalness_score INTEGER NOT NULL DEFAULT 0,
    issues TEXT NOT NULL DEFAULT '[]',
    suggestions TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (message_id) REFERENCES conversation_messages(message_id)
);

CREATE TABLE IF NOT EXISTS learning_items (
    item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    item_type TEXT NOT NULL CHECK(item_type IN ('grammar', 'vocab', 'phrase', 'pronunciation')),
    content TEXT NOT NULL,
    easiness REAL NOT NULL DEFAULT 2.5,
    interval_days INTEGER NOT NULL DEFAULT 1,
    next_due TEXT NOT NULL DEFAULT (date('now')),
    last_reviewed TEXT,
    stats TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (user_id) REFERENCES user_profile(user_id)
);

CREATE TABLE IF NOT EXISTS daily_questions (
    question_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    prompt_text TEXT NOT NULL,
    target_skills TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    answered_at TEXT,
    FOREIGN KEY (user_id) REFERENCES user_profile(user_id)
);

CREATE TABLE IF NOT EXISTS weekly_summaries (
    summary_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    week_start TEXT NOT NULL,
    highlights TEXT NOT NULL DEFAULT '[]',
    weak_areas TEXT NOT NULL DEFAULT '[]',
    improvements TEXT NOT NULL DEFAULT '[]',
    recommended_focus TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES user_profile(user_id)
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON conversation_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_grades_message ON grades(message_id);
CREATE INDEX IF NOT EXISTS idx_learning_items_user_due ON learning_items(user_id, next_due);
CREATE INDEX IF NOT EXISTS idx_daily_questions_user ON daily_questions(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON conversation_sessions(user_id, started_at);
"""

# ── PostgreSQL Schema ──

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_profile (
    user_id BIGINT PRIMARY KEY,
    display_name TEXT NOT NULL DEFAULT '',
    timezone TEXT NOT NULL DEFAULT 'Asia/Tokyo',
    current_level TEXT NOT NULL DEFAULT 'N2',
    target_level TEXT NOT NULL DEFAULT 'fluent',
    daily_question_time TEXT NOT NULL DEFAULT '08:00',
    preferred_topics TEXT NOT NULL DEFAULT '[]',
    register_preference TEXT NOT NULL DEFAULT 'mixed' CHECK(register_preference IN ('casual', 'polite', 'mixed')),
    correction_intensity TEXT NOT NULL DEFAULT 'normal' CHECK(correction_intensity IN ('light', 'normal', 'strict')),
    mode TEXT NOT NULL DEFAULT 'conversation' CHECK(mode IN ('test_prep', 'conversation')),
    difficulty_ramp TEXT NOT NULL DEFAULT 'normal' CHECK(difficulty_ramp IN ('slow', 'normal', 'fast')),
    recurring_error_patterns TEXT NOT NULL DEFAULT '{}',
    learner_summary TEXT NOT NULL DEFAULT '',
    streak_count INTEGER NOT NULL DEFAULT 0,
    last_active TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS conversation_sessions (
    session_id TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES user_profile(user_id),
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMP,
    mode TEXT NOT NULL DEFAULT 'conversation',
    topic_tags TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    message_id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES conversation_sessions(session_id),
    role TEXT NOT NULL CHECK(role IN ('user', 'bot')),
    text TEXT NOT NULL,
    transcript TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS grades (
    grade_id SERIAL PRIMARY KEY,
    message_id INTEGER NOT NULL REFERENCES conversation_messages(message_id),
    overall_score INTEGER NOT NULL DEFAULT 0,
    grammar_score INTEGER NOT NULL DEFAULT 0,
    vocab_score INTEGER NOT NULL DEFAULT 0,
    pronunciation_score INTEGER NOT NULL DEFAULT 0,
    fluency_score INTEGER NOT NULL DEFAULT 0,
    naturalness_score INTEGER NOT NULL DEFAULT 0,
    issues TEXT NOT NULL DEFAULT '[]',
    suggestions TEXT NOT NULL DEFAULT '[]',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS learning_items (
    item_id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES user_profile(user_id),
    item_type TEXT NOT NULL CHECK(item_type IN ('grammar', 'vocab', 'phrase', 'pronunciation')),
    content TEXT NOT NULL,
    easiness REAL NOT NULL DEFAULT 2.5,
    interval_days INTEGER NOT NULL DEFAULT 1,
    next_due DATE NOT NULL DEFAULT CURRENT_DATE,
    last_reviewed TEXT,
    stats TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS daily_questions (
    question_id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES user_profile(user_id),
    prompt_text TEXT NOT NULL,
    target_skills TEXT NOT NULL DEFAULT '[]',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    answered_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS weekly_summaries (
    summary_id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES user_profile(user_id),
    week_start TEXT NOT NULL,
    highlights TEXT NOT NULL DEFAULT '[]',
    weak_areas TEXT NOT NULL DEFAULT '[]',
    improvements TEXT NOT NULL DEFAULT '[]',
    recommended_focus TEXT NOT NULL DEFAULT '[]',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON conversation_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_grades_message ON grades(message_id);
CREATE INDEX IF NOT EXISTS idx_learning_items_user_due ON learning_items(user_id, next_due);
CREATE INDEX IF NOT EXISTS idx_daily_questions_user ON daily_questions(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON conversation_sessions(user_id, started_at);
"""
