"""Timer and alarm tools. Alerts are queued for main.py to speak."""
import threading
from datetime import datetime, timedelta

_alert_queue: list[str] = []
_timers: dict[str, threading.Timer] = {}


def get_alert() -> str | None:
    """Called by the main loop each tick. Returns a pending alert or None."""
    return _alert_queue.pop(0) if _alert_queue else None


def _format_duration(seconds: int) -> str:
    parts = []
    if seconds >= 3600:
        h = seconds // 3600
        parts.append(f"{h} hour{'s' if h > 1 else ''}")
        seconds %= 3600
    if seconds >= 60:
        m = seconds // 60
        parts.append(f"{m} minute{'s' if m > 1 else ''}")
        seconds %= 60
    if seconds:
        parts.append(f"{seconds} second{'s' if seconds > 1 else ''}")
    return " and ".join(parts) or "0 seconds"


def set_timer(seconds: int, label: str = "timer") -> str:
    if label in _timers:
        _timers[label].cancel()

    def _fire():
        _alert_queue.append(f"yo your {label} is done bro")
        _timers.pop(label, None)

    t = threading.Timer(float(seconds), _fire)
    t.daemon = True
    t.start()
    _timers[label] = t
    due = (datetime.now() + timedelta(seconds=seconds)).strftime("%H:%M")
    return f"aight, {label} set for {_format_duration(seconds)}, goes off at {due}."


def cancel_timer(label: str = "timer") -> str:
    if label in _timers:
        _timers[label].cancel()
        del _timers[label]
        return f"cancelled the {label} bro."
    if _timers:
        # Cancel most recent
        last = list(_timers)[-1]
        _timers[last].cancel()
        del _timers[last]
        return f"cancelled the {last} bro."
    return "no timers running rn bro."


def list_timers() -> str:
    if not _timers:
        return "no timers running bro."
    return "active timers: " + ", ".join(_timers.keys())
