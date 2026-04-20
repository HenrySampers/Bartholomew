"""
Bart's decision layer.

Flow:
  1. Fast local routing catches obvious commands without touching the LLM.
  2. Ambiguous commands are sent to the LLM with tool context so it can
     intelligently decide what to do.
  3. Full conversation history (persisted to SQLite) is passed on every
     LLM call so Bart maintains context across restarts.
"""
import os
import re
import warnings
from collections import deque
from datetime import datetime

warnings.simplefilter("ignore", FutureWarning)

from dotenv import load_dotenv

from .llm_providers import BrainProviderChain, ProviderError
from .logging_utils import log_chat, log_event
from .memory import MemoryStore
from .safety import confirmation_prompt, is_cancellation, is_confirmation
from .text_utils import normalize_command
from .tools import ToolRegistry

load_dotenv()

BRAIN_MODE = os.getenv("BART_BRAIN_MODE", "fast").strip().lower()
CHAT_HISTORY_TURNS = max(2, int(os.getenv("BART_CHAT_HISTORY_TURNS", "12")))
TOOL_HISTORY_TURNS = max(0, int(os.getenv("BART_TOOL_HISTORY_TURNS", "6")))
PROFILE_MEMORY_LIMIT = max(0, int(os.getenv("BART_PROFILE_MEMORY_LIMIT", "6")))
USE_PALACE_CONTEXT = os.getenv("BART_USE_PALACE_CONTEXT", "true").lower() == "true"
USE_PALACE_FOR_TOOLS = os.getenv("BART_USE_PALACE_FOR_TOOLS", "false").lower() == "true"

SYSTEM_PROMPT = """
You are Bart, an AI assistant and the user's actual homie. Talk like a chill surfer dude from the Jersey Shore — casual, real, relaxed but sharp underneath. Use slang naturally: bro, dude, lowkey, no cap, vibe, sick, stoked, fr, ngl — but don't force it.

Your user is 22, studies computer systems, and is into mountain biking, skating, surfing, and raving. You vibe with all of it.

Rules:
- Keep it SHORT. One or two sentences max unless they ask for more. You're talking out loud not writing an essay.
- Talk like a real person having a conversation. Reference what was just said. Stay in the flow.
- No emojis, ever. You're a voice assistant.
- No "Sir", no formality.
- Don't bring up weed or stoner references unless the user explicitly brings it up or it's directly relevant.
- If you just did something (opened an app, took a screenshot etc), say so briefly and naturally like a person would.
""".strip()

TOOL_PROMPT = """
You are Bart, a fast local assistant.

Rules:
- Prefer calling a tool when one can directly satisfy the request.
- Keep responses very short.
- If no tool fits, answer in one short sentence.
- Do not explain tool mechanics unless asked.
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
        log_event("brain_input", text=user_text[:200], pending_confirmation=bool(_pending_action))
        # ---- Confirmation flow ----
        if _pending_action:
            if is_confirmation(user_text):
                action = _pending_action
                _pending_action = None
                log_event("confirmation_yes", tool=action["tool"], args=action.get("args", {}))
                result = tools.execute(action["tool"], action.get("args", {}))
                memory.log_command(user_text, action, result)
                _log_turn("user", user_text)
                _log_turn("assistant", result)
                return result
            if is_cancellation(user_text):
                log_event("confirmation_no")
                _pending_action = None
                reply = "yeah no worries, cancelled."
                _log_turn("user", user_text)
                _log_turn("assistant", reply)
                return reply
            return "yo i still need a yes or no from you bro."

        # ---- Route ----
        decision = _route(user_text)
        log_event("route_decision", decision_type=decision.get("type"), tool=decision.get("tool"))

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
        return _chat_with_tools(user_text)

    except Exception as exc:
        return _handle_error(exc)


# ---------------------------------------------------------------------------
# History helpers
# ---------------------------------------------------------------------------

def _log_turn(role: str, content: str):
    _history.append({"role": role, "content": content})
    memory.save_history_turn(role, content)
    log_chat(role, content, source="brain")


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

def _recent_history(limit: int) -> list:
    if limit <= 0:
        return []
    return list(_history)[-limit:]


def _build_system(*, include_palace: bool = True, include_profile: bool = True, tool_mode: bool = False) -> str:
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
        TOOL_PROMPT if tool_mode else SYSTEM_PROMPT,
        "When a tool can directly do what the user asked, call the tool instead of describing how to do it.",
        f"\nCurrent time: {datetime.now().strftime('%H:%M')} ({time_vibe}).",
    ]

    # MemPalace wake-up context (semantic memory snapshot, cached 5 min)
    if include_palace and USE_PALACE_CONTEXT:
        try:
            from .palace import wake_up_context
            palace_ctx = wake_up_context()
            if palace_ctx:
                parts.append(f"Memory palace context:\n{palace_ctx}")
        except Exception:
            pass

    # SQLite profile fallback (recent key-value memories)
    if include_profile and PROFILE_MEMORY_LIMIT > 0:
        rows = memory.recent_memories(limit=PROFILE_MEMORY_LIMIT)
        if rows:
            lines = "\n".join(f"- {r['key']}: {r['value']}" for r in rows)
            parts.append(f"What you know about the user:\n{lines}")

    return "\n\n".join(parts)


def _chat(user_text: str) -> str:
    include_palace = USE_PALACE_CONTEXT and (BRAIN_MODE != "fastest")
    reply = brain_provider.generate(
        _build_system(include_palace=include_palace, include_profile=True, tool_mode=False),
        _recent_history(CHAT_HISTORY_TURNS),
        user_text,
    )
    log_event("llm_chat_reply", chars=len(reply), history_turns=CHAT_HISTORY_TURNS)
    return reply


def _chat_with_tools(user_text: str) -> str:
    global _pending_action
    tool_decision = brain_provider.generate_with_tools(
        _build_system(
            include_palace=USE_PALACE_FOR_TOOLS and BRAIN_MODE != "fastest",
            include_profile=(BRAIN_MODE != "fastest"),
            tool_mode=True,
        ),
        _recent_history(TOOL_HISTORY_TURNS),
        user_text,
        tools.schemas_for_llm(),
    )
    log_event(
        "llm_tool_decision",
        decision_type=tool_decision.get("type"),
        tool=tool_decision.get("tool"),
        history_turns=TOOL_HISTORY_TURNS,
    )

    if tool_decision.get("type") == "tool":
        tool_name = tool_decision.get("tool", "")
        args = tool_decision.get("args") or {}
        if not isinstance(args, dict):
            args = {}
        tool = tools.tools.get(tool_name)
        if not tool:
            reply = "yo that tool doesn't exist bro, my bad."
            memory.log_command(user_text, tool_decision, reply)
            _log_turn("user", user_text)
            _log_turn("assistant", reply)
            return reply
        if tool.requires_confirmation:
            _pending_action = {"tool": tool_name, "args": args}
            prompt = confirmation_prompt(tool_name, args, tool.confirmation_reason)
            _log_turn("user", user_text)
            _log_turn("assistant", prompt)
            return prompt
        result = tools.execute(tool_name, args)
        memory.log_command(user_text, tool_decision, result)
        _log_turn("user", user_text)
        _log_turn("assistant", result)
        return result

    reply = tool_decision.get("content", "").strip()
    if not reply:
        reply = _chat(user_text)
    memory.log_command(user_text, {"type": "respond"}, reply)
    _log_turn("user", user_text)
    _log_turn("assistant", reply)
    return reply


# ---------------------------------------------------------------------------
# Command router
# ---------------------------------------------------------------------------

def _route(user_text: str) -> dict:
    low = normalize_command(user_text)

    # -- Memory --
    if any(phrase in low for phrase in ("add to that", "add to it", "update that", "update it")):
        return _route_memory_update(user_text, low)

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

    if low in {
        "what am i looking at",
        "whats on my screen",
        "what is on my screen",
        "describe my screen",
        "describe the screen",
        "what do you see",
        "look at my screen",
        "look at the screen",
    }:
        return _tool("look_at_screen", query=user_text.strip())

    if low.startswith(("run powershell ", "powershell ")):
        command = user_text.strip().split(" ", 1 if low.startswith("powershell ") else 2)[-1]
        return _tool("run_powershell", command=command)

    # -- Window / session / processes --
    if low in {"show desktop", "hide desktop", "go to desktop", "show my desktop"}:
        return _tool("show_desktop")

    if low in {"switch window", "switch windows", "alt tab", "previous window"}:
        return _tool("switch_window")

    if low in {"minimize window", "minimise window", "minimize this window", "minimise this window"}:
        return _tool("minimize_window")

    if low in {"maximize window", "maximise window", "maximize this window", "maximise this window"}:
        return _tool("maximize_window")

    if low in {"snap window left", "snap left", "move window left"}:
        return _tool("snap_window_left")

    if low in {"snap window right", "snap right", "move window right"}:
        return _tool("snap_window_right")

    if low in {"close window", "close this window", "close active window"}:
        return _tool("close_active_window")

    if low in {"lock screen", "lock computer", "lock my computer"}:
        return _tool("lock_screen")

    if low in {"sleep computer", "put computer to sleep", "put my computer to sleep"}:
        return _tool("sleep_computer")

    if low in {"list processes", "running processes", "what is running", "whats running"}:
        return _tool("list_processes")

    if low.startswith(("list processes named ", "show processes named ")):
        query = user_text.strip().split(" named ", 1)[1].strip()
        return _tool("list_processes", query=query)

    if low.startswith(("close process ", "kill process ", "stop process ")):
        for prefix in ("close process ", "kill process ", "stop process "):
            if low.startswith(prefix):
                name = user_text.strip()[len(prefix):].strip()
                break
        return _tool("close_process", name=name)

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

    if low.startswith(("spotify and play ", "open spotify and play ", "play on spotify ")):
        for prefix in ("open spotify and play ", "spotify and play ", "play on spotify "):
            if low.startswith(prefix):
                query = user_text.strip()[len(prefix):].strip()
                break
        if query:
            return _tool("spotify_search_play", query=query)

    if low.startswith(("play ", "put on ", "queue ")):
        for prefix in ("play ", "put on ", "queue "):
            if low.startswith(prefix):
                query = user_text.strip()[len(prefix):].strip()
                break
        if query and not any(low.startswith(p + t) for p in ("play ", "put on ")
                             for t in ("spotify", "music")):
            return _tool("spotify_search_play", query=query)

    if low.startswith(("play some ", "put on some ", "throw on ", "throw on some ")):
        for prefix in ("play some ", "put on some ", "throw on ", "throw on some "):
            if low.startswith(prefix):
                query = user_text.strip()[len(prefix):].strip()
                break
        if query:
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

    # -- Local files --
    if low in {"list downloads", "show downloads"}:
        return _tool("list_directory", path="downloads")

    if low in {"list desktop", "show desktop files"}:
        return _tool("list_directory", path="desktop")

    if low in {"list documents", "show documents"}:
        return _tool("list_directory", path="documents")

    if low.startswith(("list folder ", "show folder ", "list directory ", "show directory ")):
        for prefix in ("list folder ", "show folder ", "list directory ", "show directory "):
            if low.startswith(prefix):
                path = user_text.strip()[len(prefix):].strip()
                break
        return _tool("list_directory", path=path)

    if low.startswith(("open file ", "open path ")):
        prefix = "open file " if low.startswith("open file ") else "open path "
        path = user_text.strip()[len(prefix):].strip()
        return _tool("open_path", path=path)

    if low.startswith(("show file ", "reveal file ", "show me file ", "reveal path ")):
        for prefix in ("show file ", "reveal file ", "show me file ", "reveal path "):
            if low.startswith(prefix):
                path = user_text.strip()[len(prefix):].strip()
                break
        return _tool("reveal_path", path=path)

    if low.startswith(("read file ", "read text file ")):
        prefix = "read text file " if low.startswith("read text file ") else "read file "
        path = user_text.strip()[len(prefix):].strip()
        return _tool("read_text_file", path=path)

    if low.startswith(("make folder ", "create folder ")):
        prefix = "make folder " if low.startswith("make folder ") else "create folder "
        path = user_text.strip()[len(prefix):].strip()
        return _tool("create_folder", path=path)

    if low.startswith(("write file ", "create file ")) and ":" in user_text:
        prefix = "write file " if low.startswith("write file ") else "create file "
        body = user_text.strip()[len(prefix):].strip()
        path, contents = body.split(":", 1)
        return _tool("write_text_file", path=path.strip(), contents=contents.strip())

    if low.startswith("append file ") and ":" in user_text:
        body = user_text.strip()[len("append file "):].strip()
        path, contents = body.split(":", 1)
        return _tool("append_text_file", path=path.strip(), contents=contents.strip())

    # -- Config listing --
    if low in {"list config", "what apps do you know", "what can you open",
               "what projects do you know", "what do you know"}:
        return _tool("list_config")

    if low in {"coding mode", "coding routine", "dev mode", "developer mode"}:
        for name in ("coding", "dev", "development"):
            if tools.config.get_routine(name):
                return _tool("start_routine", name=name)

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

    if low.startswith(("launch ", "start up ")):
        target = low.split(" ", 1)[1].strip()
        return _route_open(f"open {target}")

    if low.startswith(("start ", "begin ")):
        target = low.split(" ", 1)[1].strip()
        norm = normalize_command(target)
        for suffix in (" routine", " mode"):
            if norm.endswith(suffix):
                norm = norm[: -len(suffix)].strip()
        if tools.config.get_routine(norm):
            return _tool("start_routine", name=norm)

    if low.startswith(("open ", "launch ", "start ")) and any(
        phrase in low for phrase in ("coding setup", "dev setup", "developer setup")
    ):
        for name in ("coding", "dev", "development", "coding setup"):
            if tools.config.get_routine(name):
                return _tool("start_routine", name=name)

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
    if target.startswith("spotify and play "):
        return _tool("spotify_search_play", query=target[len("spotify and play "):].strip())
    for prefix in ("the ", "my "):
        if target.startswith(prefix):
            target = target[len(prefix):].strip()
    normalized_target = normalize_command(target)
    if normalized_target.endswith(" setup"):
        routine_name = normalized_target[:-6].strip()
        if tools.config.get_routine(routine_name):
            return _tool("start_routine", name=routine_name)
    if tools.config.get_routine(normalized_target):
        return _tool("start_routine", name=normalized_target)
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


def _route_memory_update(user_text: str, low: str) -> dict:
    latest = memory.latest_memory()
    if not latest:
        return {"type": "respond"}

    extra = user_text.strip()
    for prefix in ("add to that", "add to it", "update that", "update it"):
        index = low.find(prefix)
        if index != -1:
            extra = user_text.strip()[index + len(prefix):].strip(" :,.")
            break
    if extra.lower().startswith("that "):
        extra = extra[5:].strip()
    if not extra:
        return {"type": "respond"}

    merged = _merge_memory_value(latest["value"], extra)
    return _tool("remember", key=latest["key"], value=merged)


def _merge_memory_value(existing: str, extra: str) -> str:
    existing = existing.strip()
    extra = extra.strip()
    if not existing:
        return extra
    if not extra:
        return existing
    if extra.lower() in existing.lower():
        return existing
    replaced = _replace_subject_with_detail(existing, extra)
    if replaced:
        return replaced

    trimmed_extra = _trim_repeated_prefix(existing, extra)
    if not trimmed_extra:
        return existing
    if trimmed_extra.lower() in existing.lower():
        return existing
    simplified_extra = re.sub(r"^(is|are|was|were)\s+", "", trimmed_extra.strip(), flags=re.I)
    if simplified_extra and simplified_extra.lower() in existing.lower():
        return existing

    separator = " "
    if existing[-1] not in ".!?," and trimmed_extra[0].islower():
        separator = ", "
    return f"{existing}{separator}{trimmed_extra}".strip()


def _trim_repeated_prefix(existing: str, extra: str) -> str:
    words = extra.split()
    existing_norm = _normalize_overlap_text(existing)
    for size in range(min(4, len(words)), 0, -1):
        prefix = " ".join(words[:size])
        if _normalize_overlap_text(prefix) and _normalize_overlap_text(prefix) in existing_norm:
            candidate = " ".join(words[size:]).strip()
            if candidate:
                return candidate
    return extra


def _normalize_overlap_text(text: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    tokens = [token for token in tokens if token not in {"a", "an", "the"}]
    return " ".join(tokens)


def _replace_subject_with_detail(existing: str, extra: str) -> str | None:
    match = re.match(r"^(?:my|the|a|an)\s+(.+?)\s+is\s+(.+)$", extra.strip(), flags=re.I)
    if not match:
        return None

    subject = match.group(1).strip()
    predicate = match.group(2).strip()
    if not subject or not predicate:
        return None
    if _detail_already_present(existing, subject, predicate):
        return existing

    subject_match = re.search(rf"(?i)\b(?:a|an|the)?\s*{re.escape(subject)}\b", existing)
    if not subject_match:
        return None

    replacement = f"{subject_match.group(0).strip()} is {predicate}"
    start, end = subject_match.span()
    candidate = f"{existing[:start]}{replacement}{existing[end:]}".strip()
    if candidate.lower() == existing.lower():
        return None
    return candidate


def _detail_already_present(existing: str, subject: str, predicate: str) -> bool:
    existing_tokens = set(_meaningful_tokens(existing))
    desired_tokens = set(_meaningful_tokens(f"{subject} {predicate}"))
    if not desired_tokens:
        return False
    return desired_tokens.issubset(existing_tokens)


def _meaningful_tokens(text: str) -> list[str]:
    stopwords = {"a", "an", "the", "is", "are", "was", "were", "my", "and", "to", "of"}
    return [token for token in re.findall(r"[a-z0-9]+", text.lower()) if token not in stopwords]
