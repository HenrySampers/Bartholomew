"""File search tool — searches common user directories."""
import os
from pathlib import Path


_SEARCH_ROOTS = [
    Path.home() / "Desktop",
    Path.home() / "Downloads",
    Path.home() / "Documents",
    Path.home() / "Pictures",
    Path.home() / "Videos",
    Path.home() / "Music",
    Path.home(),
]

MAX_RESULTS = 6


def file_search(query: str) -> str:
    if not query.strip():
        return "what are you looking for bro?"

    query_lower = query.strip().lower()
    found = []

    for root in _SEARCH_ROOTS:
        if not root.exists():
            continue
        try:
            for path in root.rglob("*"):
                if query_lower in path.name.lower():
                    found.append(path)
                if len(found) >= MAX_RESULTS:
                    break
        except PermissionError:
            continue
        if len(found) >= MAX_RESULTS:
            break

    if not found:
        return f"couldn't find anything matching '{query}' bro."

    lines = [str(p) for p in found[:MAX_RESULTS]]
    result = f"found {len(lines)} match{'es' if len(lines) > 1 else ''}:\n" + "\n".join(lines)
    return result
