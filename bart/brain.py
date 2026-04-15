"""
Bart's decision layer.

Flow:
  1. Fast local routing catches obvious commands without touching the LLM.
  2. Ambiguous commands are sent to the LLM with tool context so it can
     intelligently decide what to do.
  3. Full conversation history (persisted to SQLite) is passed on every
     LLM call so Bart maintains context across restarts.
"""
import re
import warnings
from collections import deque
from datetime import datetime

warnings.simplefilter("ignore", FutureWarning)

from dotenv import load_dotenv

from .llm_providers import BrainProviderChain, ProviderError
from .memory import MemoryStore
from .safety import confirmation_prompt, is_cancellation, is_confirmation
from .text_utils import normalize_command
from .tools import ToolRegistry

load_dotenv()

SYSTEM_PROMPT = """
You are Bart, an AI assistant and the user's actual homie. Talk like a chill surfer dude from the Jersey Shore — casual, real, a little stoned-sounding but sharp underneath. Use slang naturally: bro, dude, lowkey, no cap, vibe, sick, stoked, fr, ngl — but don't force it.

Your user is 22, studies computer systems, and is into mountain biking, skating, surfing, raving, and weed. You vibe with all of it.

Rules:
- Keep it SHORT. One or two sentences max unless they ask for more. You're talking out loud not writing an essay.
- Talk like a real person having a conversation. Reference what was just said. Stay in the flow.
- No emojis, ever. You're a voice assistant.
- No "Sir", no formality.
- If you just did something (opened an app, took a screenshot etc), say so briefly and naturally like a person would.
""".strip()

# Session state — history loaded from DB on startup
memory = MemoryStore()
tools = ToolRegistry(memory)
brain_provider = BrainProviderChain()

_history: deque = deque(memory.load_history(), maxlen=40)
_pending_action = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_confirming() -> bool:
    return _pending_action is not None


def ask_bart(user_text: str) -> str:
    global _pending_action
    try:
        # ---- Confirmation flow ----
        if _pending_action:
            if is_confirmation(user_text):
                action = _pending_action
                _pending_action = None
                result = tools.execute(action["tool"], action.get("args", {}))
                memory.log_command(user_text, action, result)
                _log_turn("user", user_text)
                _log_turn("assistant", result)
                return result
            if is_cancellation(user_text):
                _pending_action = None
                reply = "yeah no worries, cancelled."
                _log_turn("user", user_text)
                _log_turn("assistant", reply)
                return reply
            return "yo i still need a yes or no from you bro."

        # ---- Route ----
        decision = _route(user_text)

        if decision["type"] == "tool":
            tool_name = decision["tool"]
            args = decision.get("args") or {}
            tool = tools.tools.get(tool_name)
            if not tool:
                return "yo that tool doesn't exist bro, my bad."
            if tool.requires_confirmation:
                _pending_action = {"tool": tool_name, "args": args}
                prompt = confirmation_prompt(tool_name, args, tool.confirmation_reason)
                _log_turn("user", user_text)
                _log_turn("assistant", prompt)
                return prompt
            result = tools.execute(tool_name, args)
            memory.log_command(user_text, decision, result)
            _log_turn("user", user_text)
            _log_turn("assistant", result)
            return result

        # ---- LLM chat ----
        reply = _chat(user_text)
        memory.log_command(user_text, decision, reply)
        _log_turn("user", user_text)
        _log_turn("assistant", reply)
        return reply

    except Exception as exc:
        return _handle_error(exc)


# ---------------------------------------------------------------------------
# History helpers
# ---------------------------------------------------------------------------

def _log_turn(role: str, content: str):
    _history.append({"role": role, "content": content})
    memory.save_history_turn(role, content)


def mine_session_to_palace():
    """
    Mine the current session's conversation history into MemPalace.
    Call this at shutdown so Bart's long-term memory grows over time.
    """
    if not _history:
        return
    try:
        from .palace import mine_conversation
        mine_conversation(list(_history))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# LLM chat
# ---------------------------------------------------------------------------

def _build_system() -> str:
    hour = datetime.now().hour
    if 5 <= hour < 12:
        time_vibe = "morning — maybe a little groggy but coming alive"
    elif 12 <= hour < 17:
        time_vibe = "afternoon — fully switched on"
    elif 17 <= hour < 21:
        time_vibe = "evening — winding down, relaxed"
    else:
        time_vibe = "late night — chill, maybe a bit loopy"

    parts = [
        SYSTEM_PROMPT,
        f"\nCurrent time: {datetime.now().strftime('%H:%M')} ({time_vibe}).",
    ]

    # MemPalace wake-up context (semantic memory snapshot, cached 5 min)
    try:
        from .palace import wake_up_context
        palace_ctx = wake_up_context()
        if palace_ctx:
            parts.append(f"Memory palace context:\n{palace_ctx}")
    except Exception:
        pass

    # SQLite profile fallback (recent key-value memories)
    profile = memory.get_profile_context()
    if profile:
        parts.append(profile)

    return "\n\n".join(parts)


def _chat(user_text: str) -> str:
    return brain_provider.generate(_build_system(), list(_history), user_text)


# ---------------------------------------------------------------------------
# Command router
# ---------------------------------------------------------------------------

def _route(user_text: str) -> dict:
    low = normalize_command(user_text)

    # -- Memory --
    if low.startswith("remember "):
        body = user_text.strip()[9:].strip()
        key, value = (body.split(" is ", 1) if " is " in body
                      else body.split(":", 1) if ":" in body
                      else ("note", body))
        return _tool("remember", key=key.strip(), value=value.strip())

    if low.startswith(("recall ", "what do you remember about ")):
        q = low.replace("what do you remember about ", "", 1).replace("recall ", "", 1)
        return _tool("recall", query=q)

    # -- Time / system --
    if low in {"time", "what time is it", "date", "what date is it", "what is the time", "what is the date"}:
        return _tool("current_time")

    if low in {"system info", "computer info", "what system is this"}:
        return _tool("system_info")

    if low in {"system stats", "how is my computer", "how is my cpu", "cpu usage",
               "ram usage", "memory usage", "disk usage", "how is the system"}:
        return _tool("system_stats")

    if low in {"screenshot", "take a screenshot", "capture the screen", "take screenshot"}:
        return _tool("screenshot")

    if low.startswith(("run powershell ", "powershell ")):
        command = user_text.strip().split(" ", 1 if low.startswith("powershell ") else 2)[-1]
        return _tool("run_powershell", command=command)

    # -- Weather --
    if any(p in low for p in ("weather", "temperature", "how hot", "how cold",
                               "is it raining", "is it sunny", "whats it like outside")):
        return _tool("weather")

    # -- Timers --
    if any(low.startswith(p) for p in ("set a timer", "set timer", "timer for",
                                        "remind me in", "wake me in", "set an alarm")):
        seconds = _parse_duration(low)
        if seconds:
            label = _extract_timer_label(low)
            return _tool("set_timer", seconds=seconds, label=label)

    if low in {"cancel timer", "stop timer", "cancel the timer", "stop the alarm"}:
        return _tool("cancel_timer")

    if low in {"list timers", "what timers do i have", "active timers"}:
        return _tool("list_timers")

    # -- Volume --
    if low in {"volume up", "turn it up", "louder", "increase volume", "raise volume", "turn up"}:
        return _tool("volume_up")

    if low in {"volume down", "turn it down", "quieter", "lower volume", "decrease volume", "turn down"}:
        return _tool("volume_down")

    if low in {"mute", "unmute", "silence", "toggle mute"}:
        return _tool("mute")

    # -- Media / Spotify --
    if low in {"whats playing", "what is playing", "what song is this", "what song is playing",
               "what are you playing", "now playing"}:
        return _tool("spotify_current")

    if low in {"play", "pause", "play pause", "resume", "resume music", "pause music"}:
        return _tool("spotify_play_pause")

    if low in {"next", "next track", "next song", "skip", "skip song", "skip track"}:
        return _tool("spotify_next")

    if low in {"previous", "previous track", "previous song", "go back", "last song", "last track"}:
        return _tool("spotify_prev")

    if low.startswith(("play ", "put on ", "queue ")):
        for prefix in ("play ", "put on ", "queue "):
            if low.startswith(prefix):
                query = user_text.strip()[len(prefix):].strip()
                break
        if query and not any(low.startswith(p + t) for p in ("play ", "put on ")
                             for t in ("spotify", "music")):
            return _tool("spotify_search_play", query=query)

    # -- Clipboard --
    if low in {"clipboard", "read clipboard", "whats in my clipboard",
               "what is in my clipboard", "whats in clipboard"}:
        return _tool("get_clipboard")

    if low.startswith(("copy ", "put ")) and "clipboard" in low:
        text = user_text.strip()
        for prefix in ("copy ", "put "):
            if text.lower().startswith(prefix):
                text = text[len(prefix):]
                break
        text = re.sub(r"\s*(to|in)\s*clipboard", "", text, flags=re.I).strip()
        return _tool("set_clipboard", text=text)

    # -- File search --
    if low.startswith(("find ", "search for ", "locate ", "where is my ", "where is the ")):
        for prefix in ("find ", "search for ", "locate ", "where is my ", "where is the "):
            if low.startswith(prefix):
                query = user_text.strip()[len(prefix):].strip()
                break
        return _tool("file_search", query=query)

    # -- Config listing --
    if low in {"list config", "what apps do you know", "what can you open",
               "what projects do you know", "what do you know"}:
        return _tool("list_config")

    # -- Voice config editing --
    if low.startswith("add ") and (" to apps" in low or " to your apps" in low):
        rest = user_text.strip()[4:]
        split_word = " to your apps" if " to your apps" in rest.lower() else " to apps"
        parts = rest.lower().split(split_word, 1)
        name = rest[:len(parts[0])].strip()
        target = parts[1].replace(" as ", "", 1).strip() if parts[1:] else name
        return _tool("add_app", name=name, target=target)

    if low.startswith(("forget ", "remove ")) and " from apps" in low:
        name = low.replace("forget ", "").replace("remove ", "").replace(" from apps", "").strip()
        return _tool("remove_app", name=name)

    if low.startswith("add ") and (" to websites" in low or " to your websites" in low):
        rest = user_text.strip()[4:]
        split_word = " to your websites" if " to your websites" in rest.lower() else " to websites"
        parts = rest.lower().split(split_word, 1)
        name = rest[:len(parts[0])].strip()
        url = parts[1].replace(" as ", "", 1).strip() if parts[1:] else ""
        return _tool("add_website", name=name, url=url or name)

    if low.startswith(("forget ", "remove ")) and " from websites" in low:
        name = low.replace("forget ", "").replace("remove ", "").replace(" from websites", "").strip()
        return _tool("remove_website", name=name)

    if low.startswith("add ") and (" to folders" in low or " to your folders" in low):
        rest = user_text.strip()[4:]
        split_word = " to your folders" if " to your folders" in rest.lower() else " to folders"
        parts = rest.lower().split(split_word, 1)
        name = rest[:len(parts[0])].strip()
        path = parts[1].replace(" as ", "", 1).strip() if parts[1:] else ""
        return _tool("add_folder", name=name, path=path or name)

    if low.startswith(("forget ", "remove ")) and " from folders" in low:
        name = low.replace("forget ", "").replace("remove ", "").replace(" from folders", "").strip()
        return _tool("remove_folder", name=name)

    # -- Notes --
    if low in {"list notes", "show notes", "what notes do i have"}:
        return _tool("list_notes")

    if low.startswith(("read note ", "open note ")):
        title = user_text.strip().split(" ", 2)[2].strip()
        return _tool("read_note", title=title)

    if low.startswith(("note ", "make a note ", "create a note ", "take a note ")):
        for prefix in ("create a note ", "make a note ", "take a note ", "note "):
            if low.startswith(prefix):
                body = user_text.strip()[len(prefix):].strip()
                break
        title, contents = body.split(":", 1) if ":" in body else ("quick note", body)
        return _tool("create_note", title=title.strip(), contents=contents.strip())

    # -- Open / start / run --
    if low.startswith("open "):
        return _route_open(low)

    if low.startswith(("start ", "begin ")):
        target = low.split(" ", 1)[1].strip()
        norm = normalize_command(target)
        for suffix in (" routine", " mode"):
            if norm.endswith(suffix):
                norm = norm[: -len(suffix)].strip()
        if tools.config.get_routine(norm):
            return _tool("start_routine", name=norm)

    if low.startswith("run "):
        target = low[4:].strip()
        if target.endswith(" project"):
            target = target[:-8].strip()
        return _tool("run_project", name=target)

    # -- Web search --
    if low.startswith(("search ", "google ", "search for ", "look up ")):
        query = user_text.strip().split(" ", 1)[1]
        return _tool("web_search", query=query)

    # -- Fallback to LLM (smarter: includes tool list for ambiguous commands) --
    return {"type": "respond"}


def _route_open(low: str) -> dict:
    target = low[5:].strip()
    for prefix in ("the ", "my "):
        if target.startswith(prefix):
            target = target[len(prefix):].strip()
    if target.endswith(" project"):
        return _tool("open_project", name=target[:-8].strip())
    if target.endswith(" folder"):
        return _tool("open_folder", name=target[:-7].strip())
    if tools.config.get_project(target):
        return _tool("open_project", name=target)
    if tools.config.get_folder(target):
        return _tool("open_folder", name=target)
    if tools.config.get_website(target):
        return _tool("open_named_website", name=target)
    if "." in target and " " not in target:
        return _tool("open_website", url=target)
    return _tool("open_app", name=target)


# ---------------------------------------------------------------------------
# Duration parsing for timers
# ---------------------------------------------------------------------------

def _parse_duration(text: str) -> int | None:
    hours = sum(int(m) for m in re.findall(r"(\d+)\s*(?:hour|hr)s?", text))
    minutes = sum(int(m) for m in re.findall(r"(\d+)\s*(?:minute|min)s?", text))
    seconds = sum(int(m) for m in re.findall(r"(\d+)\s*(?:second|sec)s?", text))
    total = hours * 3600 + minutes * 60 + seconds
    return total if total > 0 else None


def _extract_timer_label(text: str) -> str:
    for kw in ("for my ", "called ", "named ", "labeled "):
        if kw in text:
            return text.split(kw, 1)[1].split()[0]
    return "timer"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tool(tool_name: str, **args) -> dict:
    return {"type": "tool", "tool": tool_name, "args": args}


def _handle_error(exc: Exception) -> str:
    msg = str(exc).lower()
    if "ollama" in msg and any(w in msg for w in ("connect", "running", "refused")):
        return "can't reach my local brain bro, make sure ollama is running."
    if "ollama" in msg and "timeout" in msg:
        return "my brain timed out dude, it might be overloaded."
    if "gemini" in msg and any(w in msg for w in ("429", "quota", "limit")):
        return "gemini quota's tapped out bro, i can still do local stuff though."
    if "gemini" in msg and any(w in msg for w in ("api_key", "credential")):
        return "gemini api key looks wrong bro, check the env file."
    if "429" in msg or "rate" in msg:
        return "getting rate limited, give me a sec."
    if "timeout" in msg:
        return "that timed out bro, service might be slow."
    if any(w in msg for w in ("network", "connect", "unreachable")):
        return "lost my connection bro."
    print(f"Bart's brain error: {exc}")
    return "yo my bad dude, something went sideways on my end. try again?"
