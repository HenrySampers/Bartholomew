"""
Bart's decision layer.

Flow:
  1. Fast local routing catches obvious commands without touching the LLM.
  2. Everything else goes to the LLM provider chain with the full
     conversation history so Bart maintains session context.
  3. Both the user turn and Bart's reply are appended to history so
     future turns have context — making conversations feel natural.
"""
import warnings
from collections import deque

warnings.simplefilter("ignore", FutureWarning)

from dotenv import load_dotenv

from .llm_providers import BrainProviderChain
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

# Session state
memory = MemoryStore()
tools = ToolRegistry(memory)
brain_provider = BrainProviderChain()

# Conversation history: last 10 exchanges (20 messages) kept in memory.
_history: deque = deque(maxlen=20)
_pending_action = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_confirming() -> bool:
    return _pending_action is not None


def ask_bart(user_text: str) -> str:
    """Route a request and return Bart's spoken reply."""
    global _pending_action
    try:
        # ---- Confirmation flow ----
        if _pending_action:
            if is_confirmation(user_text):
                action = _pending_action
                _pending_action = None
                result = tools.execute(action["tool"], action.get("args", {}))
                memory.log_command(user_text, action, result)
                _history.append({"role": "user", "content": user_text})
                _history.append({"role": "assistant", "content": result})
                return result
            if is_cancellation(user_text):
                _pending_action = None
                reply = "yeah no worries, cancelled."
                _history.append({"role": "user", "content": user_text})
                _history.append({"role": "assistant", "content": reply})
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
                _history.append({"role": "user", "content": user_text})
                _history.append({"role": "assistant", "content": prompt})
                return prompt
            result = tools.execute(tool_name, args)
            memory.log_command(user_text, decision, result)
            # Log tool interactions to history so Bart knows what he just did
            _history.append({"role": "user", "content": user_text})
            _history.append({"role": "assistant", "content": result})
            return result

        # ---- LLM chat with history ----
        reply = _chat(user_text)
        memory.log_command(user_text, decision, reply)
        _history.append({"role": "user", "content": user_text})
        _history.append({"role": "assistant", "content": reply})
        return reply

    except Exception as exc:
        return _handle_error(exc)


# ---------------------------------------------------------------------------
# LLM chat
# ---------------------------------------------------------------------------

def _format_memories() -> str:
    rows = memory.recent_memories()
    if not rows:
        return "None yet."
    return "\n".join(f"- {r['key']}: {r['value']}" for r in rows)


def _chat(user_text: str) -> str:
    memories = _format_memories()
    system = (
        f"{SYSTEM_PROMPT}\n\n"
        f"Relevant saved memories:\n{memories}"
    )
    return brain_provider.generate(system, list(_history), user_text)


# ---------------------------------------------------------------------------
# Command router
# ---------------------------------------------------------------------------

def _route(user_text: str) -> dict:
    low = normalize_command(user_text)

    # -- Memory --
    if low.startswith("remember "):
        body = user_text.strip()[9:].strip()
        if " is " in body:
            key, value = body.split(" is ", 1)
        elif ":" in body:
            key, value = body.split(":", 1)
        else:
            key, value = "note", body
        return _tool("remember", key=key.strip(), value=value.strip())

    if low.startswith(("recall ", "what do you remember about ")):
        q = low.replace("what do you remember about ", "", 1).replace("recall ", "", 1)
        return _tool("recall", query=q)

    # -- Time / system --
    if low in {"time", "what time is it", "date", "what date is it", "what is the time", "what is the date"}:
        return _tool("current_time")

    if low in {"system info", "computer info", "what system is this"}:
        return _tool("system_info")

    if low in {"system stats", "how is my computer", "how is my cpu", "cpu usage", "ram usage",
               "memory usage", "disk usage", "how is the system"}:
        return _tool("system_stats")

    if low in {"screenshot", "take a screenshot", "capture the screen", "take screenshot"}:
        return _tool("screenshot")

    if low.startswith(("run powershell ", "powershell ")):
        command = user_text.strip().split(" ", 1 if low.startswith("powershell ") else 2)[-1]
        return _tool("run_powershell", command=command)

    # -- Volume --
    if low in {"volume up", "turn it up", "louder", "increase volume", "raise volume", "turn up"}:
        return _tool("volume_up")

    if low in {"volume down", "turn it down", "quieter", "lower volume", "decrease volume", "turn down"}:
        return _tool("volume_down")

    if low in {"mute", "unmute", "silence", "toggle mute"}:
        return _tool("mute")

    # -- Media --
    if low in {"play", "pause", "play pause", "resume", "resume music", "pause music", "stop music"}:
        return _tool("media_play_pause")

    if low in {"next", "next track", "next song", "skip", "skip song", "skip track"}:
        return _tool("media_next")

    if low in {"previous", "previous track", "previous song", "go back", "last song", "last track", "back"}:
        return _tool("media_prev")

    # -- Clipboard --
    if low in {"clipboard", "read clipboard", "whats in my clipboard", "what is in my clipboard",
               "whats in clipboard", "what is in clipboard"}:
        return _tool("get_clipboard")

    if low.startswith(("copy ", "put ")) and " to clipboard" in low:
        text = user_text.strip()
        for prefix in ("copy ", "put "):
            if text.lower().startswith(prefix):
                text = text[len(prefix):]
                break
        text = text.replace(" to clipboard", "").replace(" in clipboard", "").strip()
        return _tool("set_clipboard", text=text)

    # -- Config listing --
    if low in {"list config", "what apps do you know", "what can you open",
               "what projects do you know", "what do you know"}:
        return _tool("list_config")

    # -- Voice config editing --
    # "add discord to apps as discord"  /  "add discord to your apps as discord"
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
        if ":" in body:
            title, contents = body.split(":", 1)
        else:
            title, contents = "quick note", body
        return _tool("create_note", title=title.strip(), contents=contents.strip())

    # -- Open / start / run --
    if low.startswith("open "):
        return _route_open(low, user_text)

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

    # -- Fallback to LLM --
    return {"type": "respond"}


def _route_open(low: str, user_text: str) -> dict:
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
# Helpers
# ---------------------------------------------------------------------------

def _tool(tool_name: str, **args) -> dict:
    return {"type": "tool", "tool": tool_name, "args": args}


def _handle_error(exc: Exception) -> str:
    msg = str(exc).lower()
    if "ollama" in msg and ("connect" in msg or "running" in msg or "refused" in msg):
        return (
            "I cannot reach my local brain, Sir. "
            "Please ensure Ollama is running ('ollama serve') and the model is pulled."
        )
    if "ollama" in msg and "timeout" in msg:
        return "My local brain took too long to respond, Sir. It may be overloaded."
    if "gemini" in msg and ("429" in msg or "quota" in msg or "limit" in msg):
        return (
            "My Gemini quota is exhausted for the moment, Sir. "
            "I can still handle local commands — time, memory, apps, screenshots, and so on."
        )
    if "gemini" in msg and ("api_key" in msg or "api key" in msg or "credential" in msg):
        return "My Gemini API key appears to be missing or invalid, Sir."
    if "429" in msg or "rate" in msg:
        return "I am being rate-limited, Sir. Please give me a moment before asking again."
    if "timeout" in msg:
        return "That request timed out, Sir. The service may be slow or unavailable."
    if "network" in msg or "connect" in msg or "unreachable" in msg:
        return "I appear to have lost my network connection, Sir."
    print(f"Bart's brain error: {exc}")
    return "Yo my bad dude, something went sideways on my end. Try again?"
