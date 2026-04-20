import re


CONFIRMATION_WORDS = {
    "yes",
    "yep",
    "yeah",
    "yes please",
    "yeah sure",
    "for sure",
    "sounds good",
    "do that",
    "do it",
    "confirm",
    "confirmed",
    "proceed",
    "carry on",
    "go ahead",
    "okay do it",
    "ok do it",
    "sure",
}

CANCEL_WORDS = {
    "no",
    "nope",
    "nah",
    "nah bro",
    "not now",
    "cancel",
    "stop",
    "abort",
    "never mind",
    "nevermind",
    "dont do it",
    "don't do it",
    "leave it",
}


def is_confirmation(text):
    normalized = _normalize_reply(text)
    if normalized in CONFIRMATION_WORDS:
        return True
    return any(
        phrase in normalized
        for phrase in (
            "yeah go ahead",
            "yes go ahead",
            "go for it",
            "you can do it",
            "yep do it",
        )
    )


def is_cancellation(text):
    normalized = _normalize_reply(text)
    if normalized in CANCEL_WORDS:
        return True
    return any(
        phrase in normalized
        for phrase in (
            "no dont",
            "no don't",
            "cancel that",
            "stop that",
            "leave that",
            "actually no",
        )
    )


def confirmation_prompt(tool_name, args, reason):
    readable_args = ", ".join(f"{key}={value!r}" for key, value in args.items()) or "no args"
    return (
        f"yo quick check before i do that. tool: {tool_name}. "
        f"details: {readable_args}. reason: {reason}. say yes to go ahead or no to cancel."
    )


def _normalize_reply(text):
    normalized = text.strip().lower()
    normalized = re.sub(r"[^a-z0-9'\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized
