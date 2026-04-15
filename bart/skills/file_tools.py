"""Local file utilities for browsing, reading, opening, and writing files."""
import os
from pathlib import Path


_ALIASES = {
    "home": Path.home(),
    "desktop": Path.home() / "Desktop",
    "downloads": Path.home() / "Downloads",
    "documents": Path.home() / "Documents",
    "pictures": Path.home() / "Pictures",
    "music": Path.home() / "Music",
    "videos": Path.home() / "Videos",
    "bart": Path.cwd(),
    "bartholomew": Path.cwd(),
}


def _resolve(path: str) -> Path:
    raw = (path or "").strip().strip('"')
    if not raw:
        return Path.cwd()
    key = raw.lower()
    if key in _ALIASES:
        return _ALIASES[key]
    for alias, root in _ALIASES.items():
        if key.startswith(alias + "\\") or key.startswith(alias + "/"):
            return root / raw[len(alias):].lstrip("\\/")
    return Path(os.path.expandvars(raw)).expanduser()


def _preview_path(path: Path) -> str:
    try:
        return str(path.resolve())
    except Exception:
        return str(path)


def list_directory(path: str = ".", limit: int = 20) -> str:
    folder = _resolve(path)
    if not folder.exists():
        return f"can't find that folder bro: {_preview_path(folder)}"
    if not folder.is_dir():
        return f"that's not a folder bro: {_preview_path(folder)}"

    try:
        entries = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError:
        return f"don't have permission to list that folder bro: {_preview_path(folder)}"

    if not entries:
        return f"{folder.name or folder} is empty."

    limit = max(1, min(int(limit or 20), 50))
    lines = []
    for item in entries[:limit]:
        marker = "[folder]" if item.is_dir() else "[file]"
        lines.append(f"{marker} {item.name}")
    more = f"\n...and {len(entries) - limit} more" if len(entries) > limit else ""
    return f"{_preview_path(folder)}:\n" + "\n".join(lines) + more


def open_path(path: str) -> str:
    target = _resolve(path)
    if not target.exists():
        return f"can't find that path bro: {_preview_path(target)}"
    os.startfile(target)
    return f"opened {_preview_path(target)}."


def reveal_path(path: str) -> str:
    target = _resolve(path)
    if not target.exists():
        return f"can't find that path bro: {_preview_path(target)}"
    if target.is_dir():
        os.startfile(target)
    else:
        import subprocess

        subprocess.Popen(["explorer", "/select,", str(target)])
    return f"showing {_preview_path(target)}."


def read_text_file(path: str, max_chars: int = 4000) -> str:
    target = _resolve(path)
    if not target.exists():
        return f"can't find that file bro: {_preview_path(target)}"
    if not target.is_file():
        return f"that's not a file bro: {_preview_path(target)}"
    if target.stat().st_size > 2_000_000:
        return "that file is too big to read aloud comfortably bro."

    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            text = target.read_text(encoding="cp1252")
        except Exception:
            return "that doesn't look like a readable text file bro."
    except PermissionError:
        return f"don't have permission to read that file bro: {_preview_path(target)}"

    max_chars = max(200, min(int(max_chars or 4000), 10000))
    suffix = "\n...truncated." if len(text) > max_chars else ""
    return text[:max_chars] + suffix


def create_folder(path: str) -> str:
    target = _resolve(path)
    target.mkdir(parents=True, exist_ok=True)
    return f"folder ready: {_preview_path(target)}"


def write_text_file(path: str, contents: str) -> str:
    target = _resolve(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(contents or "", encoding="utf-8")
    return f"wrote {_preview_path(target)}."


def append_text_file(path: str, contents: str) -> str:
    target = _resolve(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as file:
        file.write(contents or "")
        if contents and not contents.endswith("\n"):
            file.write("\n")
    return f"added that to {_preview_path(target)}."
