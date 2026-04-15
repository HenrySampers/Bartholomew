"""Memory tools: remember and recall — backed by MemPalace (semantic) + SQLite (fallback)."""


def remember(memory, key, value):
    # SQLite — keeps exact-match history
    memory.remember(key, value)
    # Palace — semantic vector index for smart recall
    try:
        from .. import palace
        palace.remember(key, value)
    except Exception:
        pass
    return f"locked in bro: {key}."


def recall(memory, query):
    # Semantic search first
    try:
        from .. import palace
        result = palace.recall(query)
        if result:
            return result
    except Exception:
        pass
    # Exact-match SQLite fallback
    rows = memory.recall(query)
    if not rows:
        return "i don't have anything on that bro."
    return "\n".join(f"{row['key']}: {row['value']}" for row in rows)
