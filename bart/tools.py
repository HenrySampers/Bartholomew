import os
import platform
import re
import subprocess
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config_loader import BartConfig
from .text_utils import normalize_command


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    handler: Callable
    requires_confirmation: bool = False
    confirmation_reason: str = "This action changes your computer state."


class ToolRegistry:
    def __init__(self, memory):
        self.memory = memory
        self.config = BartConfig()
        self.tools = {}
        self.register_defaults()

    def register(self, tool):
        self.tools[tool.name] = tool

    def describe_for_prompt(self):
        lines = []
        for tool in self.tools.values():
            flag = " Requires confirmation." if tool.requires_confirmation else ""
            lines.append(f"- {tool.name}: {tool.description}.{flag}")
        return "\n".join(lines)

    def execute(self, name, args):
        if name not in self.tools:
            return f"I do not have a tool called {name!r}, Sir."
        if not isinstance(args, dict):
            return "The tool arguments were malformed, Sir."
        try:
            return self.tools[name].handler(**args)
        except TypeError as exc:
            return f"The tool arguments were not quite right, Sir: {exc}"
        except Exception as exc:
            return f"The tool failed, Sir: {exc}"

    def register_defaults(self):
        self.register(
            Tool(
                name="remember",
                description="Store a memory. Args: key, value",
                handler=self.remember,
            )
        )
        self.register(
            Tool(
                name="recall",
                description="Search Bart's saved memories. Args: query",
                handler=self.recall,
            )
        )
        self.register(
            Tool(
                name="open_app",
                description="Open a configured application or direct app/path. Args: name",
                handler=self.open_app,
            )
        )
        self.register(
            Tool(
                name="open_folder",
                description="Open a configured folder in Explorer. Args: name",
                handler=self.open_folder,
            )
        )
        self.register(
            Tool(
                name="open_project",
                description="Open a configured project. Args: name",
                handler=self.open_project,
            )
        )
        self.register(
            Tool(
                name="open_named_website",
                description="Open a configured website by friendly name. Args: name",
                handler=self.open_named_website,
            )
        )
        self.register(
            Tool(
                name="start_routine",
                description="Run a configured routine. Args: name",
                handler=self.start_routine,
                requires_confirmation=True,
                confirmation_reason="Routines may open apps, websites, folders, or start local processes.",
            )
        )
        self.register(
            Tool(
                name="run_project",
                description="Run a configured project command. Args: name",
                handler=self.run_project,
                requires_confirmation=True,
                confirmation_reason="Running a project command starts local processes on your computer.",
            )
        )
        self.register(
            Tool(
                name="list_config",
                description="List configured apps, folders, and projects. Args: none",
                handler=self.list_config,
            )
        )
        self.register(
            Tool(
                name="create_note",
                description="Create a local markdown note. Args: title, contents",
                handler=self.create_note,
            )
        )
        self.register(
            Tool(
                name="list_notes",
                description="List local notes. Args: none",
                handler=self.list_notes,
            )
        )
        self.register(
            Tool(
                name="read_note",
                description="Read a local note by title. Args: title",
                handler=self.read_note,
            )
        )
        self.register(
            Tool(
                name="open_website",
                description="Open a website in the default browser. Args: url",
                handler=self.open_website,
            )
        )
        self.register(
            Tool(
                name="web_search",
                description="Open a web search in the default browser. Args: query",
                handler=self.web_search,
            )
        )
        self.register(
            Tool(
                name="current_time",
                description="Return the current date and time. Args: none",
                handler=self.current_time,
            )
        )
        self.register(
            Tool(
                name="system_info",
                description="Return basic computer and Python information. Args: none",
                handler=self.system_info,
            )
        )
        self.register(
            Tool(
                name="screenshot",
                description="Take a screenshot and save it under data/screenshots. Args: none",
                handler=self.screenshot,
            )
        )
        self.register(
            Tool(
                name="run_powershell",
                description="Run a PowerShell command. Args: command",
                handler=self.run_powershell,
                requires_confirmation=True,
                confirmation_reason="PowerShell commands can alter files, apps, settings, or security state.",
            )
        )

    def remember(self, key, value):
        self.memory.remember(key, value)
        return f"Remembered, Sir: {key}."

    def recall(self, query):
        rows = self.memory.recall(query)
        if not rows:
            return "I do not have a matching memory yet, Sir."
        return "\n".join(f"{row['key']}: {row['value']} ({row['created_at']})" for row in rows)

    def _launch_target(self, target, cwd=None):
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

    def _find_start_menu_shortcut(self, app_name):
        normalized_name = normalize_command(app_name)
        start_menu_roots = [
            Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
            Path(os.environ.get("PROGRAMDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        ]
        for root in start_menu_roots:
            if not root.exists():
                continue
            for shortcut in root.rglob("*.lnk"):
                if normalized_name in normalize_command(shortcut.stem):
                    return shortcut
        return None

    def _find_spotify_exe(self):
        candidates = [
            Path(os.environ.get("APPDATA", "")) / "Spotify" / "Spotify.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps" / "Spotify.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Packages" / "SpotifyAB.SpotifyMusic_zpdnekdrzrea0" / "Spotify.exe",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def open_app(self, name):
        target = self.config.get_app(name) or name.strip()
        if not target:
            return "I need an application name, Sir."

        normalized_name = normalize_command(name)
        if normalized_name == "spotify":
            spotify_exe = self._find_spotify_exe()
            if spotify_exe:
                self._launch_target(spotify_exe)
                return "Opening Spotify, Sir."
            shortcut = self._find_start_menu_shortcut("spotify")
            if shortcut:
                os.startfile(shortcut)
                return "Opening Spotify, Sir."

        shortcut = self._find_start_menu_shortcut(normalized_name)
        if shortcut:
            os.startfile(shortcut)
        else:
            self._launch_target(target)
        return f"Opening {name}, Sir."

    def open_folder(self, name):
        target = self.config.get_folder(name) or name.strip()
        if not target:
            return "I need a folder name, Sir."
        path = Path(target).expanduser()
        if not path.exists():
            return f"I cannot find that folder, Sir: {path}"
        os.startfile(path)
        return f"Opening {name}, Sir."

    def open_project(self, name):
        project = self.config.get_project(name)
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

    def open_named_website(self, name):
        url = self.config.get_website(name)
        if not url:
            return f"I do not have a website called {name!r} configured, Sir."
        return self.open_website(url)

    def run_project(self, name):
        project = self.config.get_project(name)
        if not project:
            return f"I do not have a project called {name!r} configured, Sir."
        command = project.get("run_command")
        path = project.get("path")
        if not command:
            return f"The {name} project has no run command configured, Sir."
        subprocess.Popen(command, cwd=path or None, shell=True)
        return f"Starting the {name} project, Sir."

    def start_routine(self, name):
        routine = self.config.get_routine(name)
        if not routine:
            return f"I do not have a routine called {name!r} configured, Sir."

        results = []
        for step in routine:
            tool_name = step.get("tool")
            args = step.get("args", {})
            if tool_name == "start_routine":
                results.append("Skipped a nested routine, Sir.")
                continue
            results.append(self.execute(tool_name, args))
        return "\n".join(results)

    def list_config(self):
        return self.config.describe_names()

    def _note_path(self, title):
        safe_title = re.sub(r"[^a-zA-Z0-9 _-]", "", title).strip().lower().replace(" ", "_")
        if not safe_title:
            safe_title = "untitled"
        return Path("data") / "notes" / f"{safe_title}.md"

    def create_note(self, title, contents):
        path = self._note_path(title)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {title.strip()}\n\n{contents.strip()}\n", encoding="utf-8")
        return f"Note saved to {path}, Sir."

    def list_notes(self):
        folder = Path("data") / "notes"
        if not folder.exists():
            return "There are no notes yet, Sir."
        notes = sorted(path.stem.replace("_", " ") for path in folder.glob("*.md"))
        if not notes:
            return "There are no notes yet, Sir."
        return "Notes: " + ", ".join(notes)

    def read_note(self, title):
        path = self._note_path(title)
        if not path.exists():
            return f"I cannot find a note called {title!r}, Sir."
        return path.read_text(encoding="utf-8")[:2000]

    def open_website(self, url):
        cleaned = url.strip()
        if not cleaned:
            return "I need a website address, Sir."
        if not cleaned.startswith(("http://", "https://")):
            cleaned = f"https://{cleaned}"
        try:
            self._launch_target(cleaned)
        except Exception:
            webbrowser.open(cleaned)
        return f"Opening {cleaned}, Sir."

    def web_search(self, query):
        if not query.strip():
            return "I need a search query, Sir."
        webbrowser.open(f"https://www.google.com/search?q={query.replace(' ', '+')}")
        return f"Searching the web for {query}, Sir."

    def current_time(self):
        return datetime.now().strftime("It is %A, %d %B %Y at %H:%M, Sir.")

    def system_info(self):
        return (
            f"System: {platform.system()} {platform.release()} on {platform.machine()}. "
            f"Python: {platform.python_version()}."
        )

    def screenshot(self):
        try:
            from PIL import ImageGrab
        except ImportError:
            return "Screenshot support needs Pillow installed. Run: pip install pillow"

        folder = Path("data") / "screenshots"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"screenshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        image = ImageGrab.grab()
        image.save(path)
        return f"Screenshot saved to {path}, Sir."

    def run_powershell(self, command):
        if not command.strip():
            return "I need a PowerShell command, Sir."
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = completed.stdout.strip() or completed.stderr.strip() or "No output."
        return f"PowerShell exited with code {completed.returncode}.\n{output[:2000]}"
