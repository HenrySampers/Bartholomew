import json
import sqlite3
from datetime import datetime
from pathlib import Path


DATA_DIR = Path("data")
DB_PATH = DATA_DIR / "bart_memory.sqlite3"
HISTORY_KEEP = 40  # messages (20 exchanges)


class MemoryStore:
    def __init__(self, db_path=DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS command_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_text TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    result TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

    # ------------------------------------------------------------------
    # Memories
    # ------------------------------------------------------------------

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
                """SELECT key, value, created_at FROM memories
                   WHERE key LIKE ? OR value LIKE ?
                   ORDER BY id DESC LIMIT ?""",
                (pattern, pattern, limit),
            ).fetchall()
        return [{"key": k, "value": v, "created_at": c} for k, v, c in rows]

    def recent_memories(self, limit=8):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT key, value, created_at FROM memories ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [{"key": k, "value": v, "created_at": c} for k, v, c in rows]

    def get_profile_context(self) -> str:
        """Return saved memories formatted for injection into the system prompt."""
        rows = self.recent_memories(limit=12)
        if not rows:
            return ""
        lines = "\n".join(f"- {r['key']}: {r['value']}" for r in rows)
        return f"What you know about the user:\n{lines}"

    # ------------------------------------------------------------------
    # Persistent conversation history
    # ------------------------------------------------------------------

    def save_history_turn(self, role: str, content: str):
        created_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO conversation_history (role, content, created_at) VALUES (?, ?, ?)",
                (role, content, created_at),
            )
            # Trim to keep only the last HISTORY_KEEP rows
            conn.execute(
                f"""DELETE FROM conversation_history WHERE id NOT IN (
                    SELECT id FROM conversation_history ORDER BY id DESC LIMIT {HISTORY_KEEP}
                )"""
            )

    def load_history(self) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT role, content FROM conversation_history ORDER BY id ASC"
            ).fetchall()
        return [{"role": role, "content": content} for role, content in rows]

    # ------------------------------------------------------------------
    # Command log
    # ------------------------------------------------------------------

    def log_command(self, user_text, decision, result):
        created_at = datetime.now().isoformat(timespec="seconds")
        decision_text = json.dumps(decision, ensure_ascii=True) if not isinstance(decision, str) else decision
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO command_log (user_text, decision, result, created_at) VALUES (?, ?, ?, ?)",
                (user_text, decision_text, result, created_at),
            )
