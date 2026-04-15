"""
ToolRegistry — loads all skills and exposes a unified execute() interface.
Adding a new skill: create a module in bart/skills/, add its tools here.
"""
import functools

from .tool_types import Tool
from .config_loader import BartConfig
from .memory import MemoryStore
from .skills import (system_tools, app_tools, memory_tools, note_tools,
                     config_tools, weather_tools, timer_tools, search_tools, spotify_tools)


class ToolRegistry:
    def __init__(self, memory: MemoryStore):
        self.memory = memory
        self.config = BartConfig()
        self.tools: dict[str, Tool] = {}
        self._register_all()

    # ------------------------------------------------------------------
    # Registration helpers
    # ------------------------------------------------------------------

    def register(self, tool: Tool):
        self.tools[tool.name] = tool

    def _reg(self, name, description, fn, requires_confirmation=False, confirmation_reason=""):
        self.register(Tool(
            name=name,
            description=description,
            handler=fn,
            requires_confirmation=requires_confirmation,
            confirmation_reason=confirmation_reason or "This action changes your computer state.",
        ))

    def _bind(self, fn, *args):
        """Partially apply positional args (e.g. config or memory) to a skill function."""
        return functools.partial(fn, *args)

    # ------------------------------------------------------------------
    # Register every skill
    # ------------------------------------------------------------------

    def _register_all(self):
        cfg = self.config
        mem = self.memory

        # --- Memory ---
        self._reg("remember", "Store a memory. Args: key, value", self._bind(memory_tools.remember, mem))
        self._reg("recall", "Search saved memories. Args: query", self._bind(memory_tools.recall, mem))

        # --- Notes ---
        self._reg("create_note", "Create a local markdown note. Args: title, contents", note_tools.create_note)
        self._reg("list_notes", "List local notes.", note_tools.list_notes)
        self._reg("read_note", "Read a local note by title. Args: title", note_tools.read_note)

        # --- Apps / folders / projects ---
        self._reg("open_app", "Open an application. Args: name", self._bind(app_tools.open_app, cfg))
        self._reg("open_folder", "Open a folder in Explorer. Args: name", self._bind(app_tools.open_folder, cfg))
        self._reg("open_project", "Open a configured project. Args: name", self._bind(app_tools.open_project, cfg))
        self._reg("open_named_website", "Open a configured website. Args: name", self._bind(app_tools.open_named_website, cfg))
        self._reg("open_website", "Open any website. Args: url", app_tools.open_website)
        self._reg("web_search", "Search the web. Args: query", app_tools.web_search)
        self._reg("list_config", "List configured apps, folders, websites, projects.", self._bind(app_tools.list_config, cfg))
        self._reg(
            "run_project", "Run a configured project command. Args: name",
            self._bind(app_tools.run_project, cfg),
            requires_confirmation=True,
            confirmation_reason="Running a project command starts local processes on your computer.",
        )
        self._reg(
            "start_routine", "Run a configured routine. Args: name",
            self._start_routine,
            requires_confirmation=True,
            confirmation_reason="Routines may open apps, websites, folders, or start local processes.",
        )

        # --- System ---
        self._reg("current_time", "Return current date and time.", system_tools.current_time)
        self._reg("system_info", "Return OS and Python info.", system_tools.system_info)
        self._reg("system_stats", "Return CPU, RAM, and disk usage.", system_tools.system_stats)
        self._reg("screenshot", "Take a screenshot.", system_tools.screenshot)
        self._reg(
            "run_powershell", "Run a PowerShell command. Args: command",
            system_tools.run_powershell,
            requires_confirmation=True,
            confirmation_reason="PowerShell commands can alter files, apps, settings, or security state.",
        )

        # --- Volume & media ---
        self._reg("volume_up", "Increase system volume.", system_tools.volume_up)
        self._reg("volume_down", "Decrease system volume.", system_tools.volume_down)
        self._reg("mute", "Toggle mute.", system_tools.mute)
        self._reg("media_play_pause", "Play or pause media.", system_tools.media_play_pause)
        self._reg("media_next", "Skip to next track.", system_tools.media_next)
        self._reg("media_prev", "Go to previous track.", system_tools.media_prev)

        # --- Clipboard ---
        self._reg("get_clipboard", "Read the clipboard.", system_tools.get_clipboard)
        self._reg("set_clipboard", "Write text to the clipboard. Args: text", system_tools.set_clipboard)

        # --- Weather ---
        self._reg("weather", "Get current weather.", weather_tools.weather)

        # --- Timers ---
        self._reg("set_timer", "Set a timer. Args: seconds, label", timer_tools.set_timer)
        self._reg("cancel_timer", "Cancel a timer. Args: label (optional)", timer_tools.cancel_timer)
        self._reg("list_timers", "List active timers.", timer_tools.list_timers)

        # --- File search ---
        self._reg("file_search", "Search for files by name. Args: query", search_tools.file_search)

        # --- Spotify ---
        self._reg("spotify_current", "Show what's playing on Spotify.", spotify_tools.spotify_current)
        self._reg("spotify_play_pause", "Play or pause Spotify.", spotify_tools.spotify_play_pause)
        self._reg("spotify_next", "Skip to next Spotify track.", spotify_tools.spotify_next)
        self._reg("spotify_prev", "Go back a Spotify track.", spotify_tools.spotify_prev)
        self._reg("spotify_search_play", "Search and play a song on Spotify. Args: query", spotify_tools.spotify_search_play)

        # --- Voice config editing ---
        self._reg("add_app", "Teach Bart a new application. Args: name, target", self._bind(config_tools.add_app, cfg))
        self._reg("remove_app", "Remove an application. Args: name", self._bind(config_tools.remove_app, cfg))
        self._reg("add_folder", "Teach Bart a new folder. Args: name, path", self._bind(config_tools.add_folder, cfg))
        self._reg("remove_folder", "Remove a folder. Args: name", self._bind(config_tools.remove_folder, cfg))
        self._reg("add_website", "Teach Bart a new website. Args: name, url", self._bind(config_tools.add_website, cfg))
        self._reg("remove_website", "Remove a website. Args: name", self._bind(config_tools.remove_website, cfg))

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(self, name, args):
        if name not in self.tools:
            return f"yo that tool doesn't exist bro: {name!r}"
        if not isinstance(args, dict):
            return "tool args were malformed bro."
        try:
            return self.tools[name].handler(**args)
        except TypeError as exc:
            return f"tool args were off bro: {exc}"
        except Exception as exc:
            return f"tool hit a problem bro: {exc}"

    # ------------------------------------------------------------------
    # start_routine needs access to execute(), so it lives here
    # ------------------------------------------------------------------

    def _start_routine(self, name):
        routine = self.config.get_routine(name)
        if not routine:
            return f"don't have a routine called {name!r} bro."
        results = []
        for step in routine:
            tool_name = step.get("tool")
            args = step.get("args", {})
            if tool_name == "start_routine":
                results.append("skipped a nested routine to avoid recursion bro.")
                continue
            results.append(self.execute(tool_name, args))
        return "\n".join(results)

    def describe_for_prompt(self):
        lines = []
        for tool in self.tools.values():
            flag = " [Requires confirmation]" if tool.requires_confirmation else ""
            lines.append(f"- {tool.name}: {tool.description}{flag}")
        return "\n".join(lines)
