"""Note tools: create, list, and read local markdown notes."""
import re
from pathlib import Path


def _note_path(title):
    safe = re.sub(r"[^a-zA-Z0-9 _-]", "", title).strip().lower().replace(" ", "_")
    return Path("data") / "notes" / f"{safe or 'untitled'}.md"


def create_note(title, contents):
    path = _note_path(title)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {title.strip()}\n\n{contents.strip()}\n", encoding="utf-8")
    return f"Note saved, Sir."


def list_notes():
    folder = Path("data") / "notes"
    if not folder.exists():
        return "There are no notes yet, Sir."
    notes = sorted(p.stem.replace("_", " ") for p in folder.glob("*.md"))
    return ("Notes: " + ", ".join(notes)) if notes else "There are no notes yet, Sir."


def read_note(title):
    path = _note_path(title)
    if not path.exists():
        return f"I cannot find a note called {title!r}, Sir."
    return path.read_text(encoding="utf-8")[:2000]
