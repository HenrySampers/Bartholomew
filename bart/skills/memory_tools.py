"""Memory tools: remember and recall."""


def remember(memory, key, value):
    memory.remember(key, value)
    return f"Remembered, Sir: {key}."


def recall(memory, query):
    rows = memory.recall(query)
    if not rows:
        return "I do not have a matching memory yet, Sir."
    return "\n".join(f"{row['key']}: {row['value']} ({row['created_at']})" for row in rows)
