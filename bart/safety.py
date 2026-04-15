CONFIRMATION_WORDS = {
    "yes",
    "yep",
    "yeah",
    "confirm",
    "confirmed",
    "do it",
    "proceed",
    "carry on",
    "go ahead",
}

CANCEL_WORDS = {
    "no",
    "nope",
    "cancel",
    "stop",
    "abort",
    "never mind",
    "nevermind",
}


def is_confirmation(text):
    normalized = text.strip().lower()
    return normalized in CONFIRMATION_WORDS


def is_cancellation(text):
    normalized = text.strip().lower()
    return normalized in CANCEL_WORDS


def confirmation_prompt(tool_name, args, reason):
    readable_args = ", ".join(f"{key}={value!r}" for key, value in args.items()) or "no arguments"
    return (
        f"Sir, that requires confirmation. Tool: {tool_name}. "
        f"Details: {readable_args}. Reason: {reason}. Shall I proceed?"
    )
