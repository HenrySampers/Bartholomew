import json
import sqlite3
from datetime import datetime
from pathlib import Path


DATA_DIR = Path("data")
DB_PATH = DATA_DIR / "bart_memory.sqlite3"


class MemoryStore:
    def __init__(self, db_path=DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS command_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_text TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    result TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def remember(self, key, value):
        created_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO memories (key, value, created_at) VALUES (?, ?, ?)",
                (key.strip(), value.strip(), created_at),
            )

    def recall(self, query, limit=5):
        pattern = f"%{query.strip()}%"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT key, value, created_at
                FROM memories
                WHERE key LIKE ? OR value LIKE ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (pattern, pattern, limit),
            ).fetchall()
        return [{"key": key, "value": value, "created_at": created_at} for key, value, created_at in rows]

    def recent_memories(self, limit=8):
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT key, value, created_at
                FROM memories
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [{"key": key, "value": value, "created_at": created_at} for key, value, created_at in rows]

    def log_command(self, user_text, decision, result):
        created_at = datetime.now().isoformat(timespec="seconds")
        decision_text = json.dumps(decision, ensure_ascii=True) if not isinstance(decision, str) else decision
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO command_log (user_text, decision, result, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_text, decision_text, result, created_at),
            )
