"""
palace.py — MemPalace integration for Bart.

Adds semantic (vector) memory on top of the existing SQLite store.
All storage is fully local via ChromaDB. No API keys required.

Architecture:
  remember(key, value) → upserts a drawer into the 'memories' wing
  recall(query)        → hybrid vector+BM25 search, returns formatted text
  wake_up_context()    → 600-900 token identity snapshot for system prompt
                         (cached 5 min so every LLM call doesn't recompute it)
"""

import time
import uuid
from datetime import datetime
from pathlib import Path

PALACE_PATH = Path("data/palace")
_WAKE_UP_TTL = 300  # seconds

_stack = None
_wake_cache: tuple[float, str] | None = None  # (timestamp, text)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _ensure():
    PALACE_PATH.mkdir(parents=True, exist_ok=True)


def _get_stack():
    global _stack
    if _stack is None:
        _ensure()
        from mempalace.layers import MemoryStack
        _stack = MemoryStack(palace_path=str(PALACE_PATH))
    return _stack


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def remember(key: str, value: str) -> None:
    """
    Store a key-value fact as a semantic drawer in the 'memories' wing.
    Can be searched later with recall().
    """
    _ensure()
    from mempalace.palace import get_collection
    col = get_collection(str(PALACE_PATH), create=True)
    content = f"{key}: {value}"
    col.upsert(
        ids=[str(uuid.uuid4())],
        documents=[content],
        metadatas=[{
            "wing": "memories",
            "room": key.lower().strip()[:50],
            "source_file": "bart_direct",
            "chunk_index": 0,
            "timestamp": datetime.now().isoformat(),
            "hall": "personal",
            "entities": "",
        }],
    )
    # Invalidate wake_up cache so next call reflects the new memory
    global _wake_cache
    _wake_cache = None


def recall(query: str, n_results: int = 5) -> str:
    """
    Semantic search over the palace.
    Returns a formatted string ready for Bart to read aloud, or '' if nothing found.
    """
    _ensure()
    try:
        from mempalace.searcher import search_memories
        result = search_memories(
            query=query,
            palace_path=str(PALACE_PATH),
            n_results=n_results,
            max_distance=0.75,
        )
        if isinstance(result, str):
            return result.strip()
        if isinstance(result, (list, tuple)):
            return "\n".join(str(r) for r in result).strip()
        return ""
    except Exception:
        return ""


def wake_up_context() -> str:
    """
    Return a rich identity/memory snapshot (600-900 tokens) for system prompt injection.
    Result is cached for 5 minutes — safe to call on every LLM turn.
    """
    global _wake_cache
    now = time.time()
    if _wake_cache is None or now - _wake_cache[0] > _WAKE_UP_TTL:
        try:
            ctx = _get_stack().wake_up().strip()
        except Exception:
            ctx = ""
        _wake_cache = (now, ctx)
    return _wake_cache[1]


def mine_conversation(turns: list[dict]) -> None:
    """
    Mine a list of {role, content} conversation turns into the palace.
    Writes to data/conversations/ — never the system temp dir — so only
    this session's file is indexed, not unrelated files.
    """
    if not turns:
        return
    try:
        from mempalace.convo_miner import mine_convos
        _ensure()
        export_dir = PALACE_PATH.parent / "conversations"
        export_dir.mkdir(parents=True, exist_ok=True)

        lines = []
        for t in turns:
            if t["role"] == "user":
                lines.append(f"> {t['content']}")
            else:
                lines.append(t["content"])

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_file = export_dir / f"session_{ts}.txt"
        export_file.write_text("\n".join(lines), encoding="utf-8")

        mine_convos(str(export_dir), str(PALACE_PATH))
    except Exception:
        pass
