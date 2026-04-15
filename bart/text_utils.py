import re


def normalize_command(text):
    normalized = text.strip().lower()
    normalized = re.sub(r"^[,.\s]*(bart|bartholomew)[,.\s]+", "", normalized)
    normalized = re.sub(r"[^a-z0-9 ]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


_SHUTDOWN_PHRASES = {
    "quit",
    "exit",
    "bye",
    "bye bart",
    "good bye",
    "good bye bart",
    "goodbye",
    "goodbye bart",
    "see ya",
    "see you",
    "see you later",
    "catch you later",
    "talk to you later",
    "later",
    "later bart",
    "peace",
    "peace out",
    "log off",
    "sleep",
    "go to sleep",
    "good night",
    "goodnight",
    "night bart",
    "go offline",
    "power down",
    "shut down",
    "shutdown",
    "shut yourself down",
    "turn off",
    "turn off bart",
    "turn yourself off",
    "close",
    "close bart",
    "stop running",
    "stop listening",
    "end session",
    "end the session",
    "exit program",
    "close the app",
    "thats all",
    "that is all",
    "thatll be all",
    "that will be all",
    "we are done",
    "were done",
    "you can go",
}

_SHUTDOWN_PREFIXES = (
    "ok ",
    "okay ",
    "alright ",
    "aight ",
    "yo ",
    "hey ",
    "thanks ",
    "thank you ",
    "can you ",
    "could you ",
    "would you ",
    "please ",
)

_SHUTDOWN_SUFFIXES = (
    " please",
    " thanks",
    " thank you",
    " for now",
    " now",
    " bro",
    " dude",
    " bart",
    " bartholomew",
)


def _strip_shutdown_fillers(text):
    changed = True
    while changed:
        changed = False
        for prefix in _SHUTDOWN_PREFIXES:
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
                changed = True
        for suffix in _SHUTDOWN_SUFFIXES:
            if text.endswith(suffix):
                text = text[: -len(suffix)].strip()
                changed = True
    return text


def is_shutdown_command(text):
    normalized = normalize_command(text)
    if len(normalized) < 2:
        return False

    candidate = _strip_shutdown_fillers(normalized)
    if candidate in _SHUTDOWN_PHRASES:
        return True

    # Whisper sometimes hears "goodbye" as two words or adds Bart at the end.
    if candidate.startswith(("bye ", "good bye ", "goodbye ")) and candidate.endswith((" bart", " bartholomew")):
        return True

    return False
