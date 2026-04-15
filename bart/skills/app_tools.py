"""
App/folder/project/website/routine tools.
All functions that need config receive it as their first argument.
The ToolRegistry binds config via functools.partial.
"""
import os
import subprocess
import webbrowser
from pathlib import Path

from ..text_utils import normalize_command


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _launch_target(target, cwd=None):
    cleaned = str(target).strip()
    if not cleaned:
        raise ValueError("No launch target provided.")
    if cleaned.startswith(("http://", "https://")) or cleaned.endswith(":"):
        os.startfile(cleaned)
        return
    path = Path(cleaned).expanduser()
    if path.exists():
        os.startfile(path)
        return
    subprocess.Popen(
        ["cmd", "/c", "start", "", cleaned],
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
    )


def _find_start_menu_shortcut(app_name):
    normalized = normalize_command(app_name)
    roots = [
        Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    ]
    for root in roots:
        if not root.exists():
            continue
        for shortcut in root.rglob("*.lnk"):
            if normalized in normalize_command(shortcut.stem):
                return shortcut
    return None


def _find_spotify_exe():
    candidates = [
        Path(os.environ.get("APPDATA", "")) / "Spotify" / "Spotify.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps" / "Spotify.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Packages" / "SpotifyAB.SpotifyMusic_zpdnekdrzrea0" / "Spotify.exe",
    ]
    return next((c for c in candidates if c.exists()), None)


# ---------------------------------------------------------------------------
# Tool handlers  (config is bound by ToolRegistry via functools.partial)
# ---------------------------------------------------------------------------

def open_app(config, name):
    target = config.get_app(name) or name.strip()
    if not target:
        return "I need an application name, Sir."
    normalized = normalize_command(name)
    if normalized == "spotify":
        exe = _find_spotify_exe()
        if exe:
            _launch_target(exe)
            return "Opening Spotify, Sir."
        shortcut = _find_start_menu_shortcut("spotify")
        if shortcut:
            os.startfile(shortcut)
            return "Opening Spotify, Sir."
    shortcut = _find_start_menu_shortcut(normalized)
    if shortcut:
        os.startfile(shortcut)
    else:
        _launch_target(target)
    return f"Opening {name}, Sir."


def open_folder(config, name):
    target = config.get_folder(name) or name.strip()
    if not target:
        return "I need a folder name, Sir."
    path = Path(target).expanduser()
    if not path.exists():
        return f"I cannot find that folder, Sir: {path}"
    os.startfile(path)
    return f"Opening {name}, Sir."


def open_project(config, name):
    project = config.get_project(name)
    if not project:
        return f"I do not have a project called {name!r} configured, Sir."
    command = project.get("open_command")
    path = project.get("path")
    if command:
        subprocess.Popen(command, cwd=path or None, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True)
        return f"Opening the {name} project, Sir."
    if path and Path(path).exists():
        os.startfile(path)
        return f"Opening the {name} project folder, Sir."
    return f"The {name} project config is missing a valid path or open command, Sir."


def open_named_website(config, name):
    url = config.get_website(name)
    if not url:
        return f"I do not have a website called {name!r} configured, Sir."
    return open_website(url)


def run_project(config, name):
    project = config.get_project(name)
    if not project:
        return f"I do not have a project called {name!r} configured, Sir."
    command = project.get("run_command")
    path = project.get("path")
    if not command:
        return f"The {name} project has no run command configured, Sir."
    subprocess.Popen(command, cwd=path or None, shell=True)
    return f"Starting the {name} project, Sir."


def list_config(config):
    return config.describe_names()


def open_website(url):
    cleaned = url.strip()
    if not cleaned:
        return "I need a website address, Sir."
    if not cleaned.startswith(("http://", "https://")):
        cleaned = f"https://{cleaned}"
    try:
        _launch_target(cleaned)
    except Exception:
        webbrowser.open(cleaned)
    return f"Opening {cleaned}, Sir."


def web_search(query):
    if not query.strip():
        return "I need a search query, Sir."
    webbrowser.open(f"https://www.google.com/search?q={query.replace(' ', '+')}")
    return f"Searching for {query}, Sir."
