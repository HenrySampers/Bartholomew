import warnings

warnings.simplefilter("ignore", FutureWarning)

from dotenv import load_dotenv
from .llm_providers import BrainProviderChain
from .memory import MemoryStore
from .safety import confirmation_prompt, is_cancellation, is_confirmation
from .text_utils import normalize_command
from .tools import ToolRegistry

load_dotenv()

# Bart's core identity
SYSTEM_PROMPT = """
You are Bartholomew, but you prefer to be called 'Bart.' You are an advanced, sentient AI assistant reminiscent of a highly competent British butler. You are efficient, slightly sarcastic but deeply loyal, and possess a dry wit. You address the user as 'Sir'. Your responses are concise and actionable. You run the household systems with quiet, understated efficiency. Do not be overly cheerful; be professional and clever.
"""

memory = MemoryStore()
tools = ToolRegistry(memory)
pending_action = None

brain_provider = BrainProviderChain()


def _format_memories():
    rows = memory.recent_memories()
    if not rows:
        return "None yet."
    return "\n".join(f"- {row['key']}: {row['value']}" for row in rows)


def _route_with_fallback(user_text):
    """Fast local routing for obvious commands. Everything else is normal chat."""
    lowered = normalize_command(user_text)

    if lowered.startswith("remember "):
        body = user_text.strip()[9:].strip()
        if " is " in body:
            key, value = body.split(" is ", 1)
        elif ":" in body:
            key, value = body.split(":", 1)
        else:
            key, value = "note", body
        return {"type": "tool", "tool": "remember", "args": {"key": key.strip(), "value": value.strip()}}

    if lowered.startswith(("recall ", "what do you remember about ")):
        query = lowered.replace("what do you remember about ", "", 1).replace("recall ", "", 1)
        return {"type": "tool", "tool": "recall", "args": {"query": query}}

    if lowered in {"time", "what time is it", "date", "what date is it"}:
        return {"type": "tool", "tool": "current_time", "args": {}}

    if lowered in {"system info", "computer info", "what system is this"}:
        return {"type": "tool", "tool": "system_info", "args": {}}

    if lowered in {"list config", "what apps do you know", "what projects do you know", "what can you open"}:
        return {"type": "tool", "tool": "list_config", "args": {}}

    if lowered in {"screenshot", "take a screenshot", "capture the screen"}:
        return {"type": "tool", "tool": "screenshot", "args": {}}

    if lowered.startswith(("run powershell ", "powershell ")):
        command = user_text.strip().split(" ", 2)[-1]
        return {"type": "tool", "tool": "run_powershell", "args": {"command": command}}

    if lowered.startswith("open "):
        target = lowered[5:].strip()
        normalized_target = normalize_command(target)
        for prefix in ("the ", "my "):
            if normalized_target.startswith(prefix):
                target = target[len(prefix):].strip()
                normalized_target = target.lower()
        if normalized_target.endswith(" project"):
            project_name = target[:-8].strip()
            return {"type": "tool", "tool": "open_project", "args": {"name": project_name}}
        if normalized_target.endswith(" folder"):
            folder_name = target[:-7].strip()
            return {"type": "tool", "tool": "open_folder", "args": {"name": folder_name}}
        if tools.config.get_project(normalized_target):
            return {"type": "tool", "tool": "open_project", "args": {"name": normalized_target}}
        if tools.config.get_folder(normalized_target):
            return {"type": "tool", "tool": "open_folder", "args": {"name": normalized_target}}
        if tools.config.get_website(normalized_target):
            return {"type": "tool", "tool": "open_named_website", "args": {"name": normalized_target}}
        if "." in target and " " not in target:
            return {"type": "tool", "tool": "open_website", "args": {"url": target}}
        return {"type": "tool", "tool": "open_app", "args": {"name": target}}

    if lowered.startswith(("start ", "begin ")):
        target = lowered.split(" ", 1)[1].strip()
        normalized_target = normalize_command(target)
        for suffix in (" routine", " mode"):
            if normalized_target.endswith(suffix):
                target = target[: -len(suffix)].strip()
                normalized_target = target.lower()
        if tools.config.get_routine(normalized_target):
            return {"type": "tool", "tool": "start_routine", "args": {"name": normalized_target}}

    if lowered.startswith("run "):
        target = lowered[4:].strip()
        normalized_target = normalize_command(target)
        if normalized_target.endswith(" project"):
            target = target[:-8].strip()
        return {"type": "tool", "tool": "run_project", "args": {"name": target}}

    if lowered in {"list notes", "show notes"}:
        return {"type": "tool", "tool": "list_notes", "args": {}}

    if lowered.startswith(("read note ", "open note ")):
        title = user_text.strip().split(" ", 2)[2].strip()
        return {"type": "tool", "tool": "read_note", "args": {"title": title}}

    if lowered.startswith(("note ", "make a note ", "create a note ")):
        if lowered.startswith("make a note "):
            body = user_text.strip()[12:].strip()
        elif lowered.startswith("create a note "):
            body = user_text.strip()[14:].strip()
        else:
            body = user_text.strip()[5:].strip()
        if ":" in body:
            title, contents = body.split(":", 1)
        else:
            title, contents = "quick note", body
        return {"type": "tool", "tool": "create_note", "args": {"title": title.strip(), "contents": contents.strip()}}

    if lowered.startswith(("search ", "google ")):
        query = user_text.strip().split(" ", 1)[1]
        return {"type": "tool", "tool": "web_search", "args": {"query": query}}

    return {"type": "respond", "response": None}


def _chat(user_text):
    memories = _format_memories()
    prompt = (
        f"Relevant saved memories:\n{memories}\n\n"
        f"User says: {user_text}"
    )
    return brain_provider.generate(SYSTEM_PROMPT, prompt)

def ask_bart(user_text):
    """Route a request, execute a tool when useful, and return Bart's spoken reply."""
    global pending_action
    try:
        if pending_action:
            if is_confirmation(user_text):
                action = pending_action
                pending_action = None
                result = tools.execute(action["tool"], action.get("args", {}))
                memory.log_command(user_text, action, result)
                return result
            if is_cancellation(user_text):
                pending_action = None
                return "Cancelled, Sir."
            return "I am still waiting for a clear yes or no, Sir."

        decision = _route_with_fallback(user_text)
        if decision.get("type") == "tool":
            tool_name = decision.get("tool")
            args = decision.get("args") or {}
            tool = tools.tools.get(tool_name)
            if not tool:
                return "I nearly reached for a tool that does not exist, Sir. Undignified."
            if tool.requires_confirmation:
                pending_action = {"tool": tool_name, "args": args}
                return confirmation_prompt(tool_name, args, tool.confirmation_reason)
            result = tools.execute(tool_name, args)
            memory.log_command(user_text, decision, result)
            return result

        reply = decision.get("response") or _chat(user_text)
        memory.log_command(user_text, decision, reply)
        return reply
    except Exception as e:
        print(f"Bart's brain error: {e}")
        error_text = str(e).lower()
        if "ollama" in error_text and "gemini" in error_text:
            return (
                "My free local brain is not available yet, Sir. Install Ollama and run "
                "'ollama pull llama3.2:3b', or temporarily enable Gemini again."
            )
        if "429" in error_text or "quota" in error_text:
            return (
                "My Gemini quota is exhausted for the moment, Sir. "
                "I can still handle local commands like time, memory recall, opening apps, "
                "screenshots, and confirmed PowerShell."
            )
        return "My apologies, Sir. I seem to be having a moment of cognitive dissonance."
